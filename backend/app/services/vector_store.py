from __future__ import annotations
import re

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.services.embedding import get_embedding, get_embeddings

import uuid


def get_client() -> QdrantClient:
    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        check_compatibility=False,
    )


def ensure_collection():
    """Collection yoksa oluşturur."""
    client = get_client()
    collections = [c.name for c in client.get_collections().collections]
    if settings.collection_name not in collections:
        # Nomic embed text v1.5 -> 768 boyut
        client.create_collection(
            collection_name=settings.collection_name,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )


def index_document(doc_metadata: dict, chunks: list[str]) -> int:
    """Doküman chunk'larını vektör veritabanına yazar."""
    client = get_client()
    ensure_collection()

    embeddings = get_embeddings(chunks)

    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = str(uuid.uuid4())
        points.append(
            PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "text": chunk,
                    "chunk_index": i,
                    "document_id": doc_metadata["id"],
                    "title": doc_metadata["title"],
                    "source": doc_metadata["source"],
                    "doc_type": doc_metadata["doc_type"],
                    "date": doc_metadata["date"],
                    "filename": doc_metadata["filename"],
                    "url": doc_metadata.get("url", ""),
                },
            )
        )

    # Batch olarak yükle (100'erli)
    batch_size = 100
    for i in range(0, len(points), batch_size):
        client.upsert(
            collection_name=settings.collection_name,
            points=points[i : i + batch_size],
        )

    return len(points)


def search_similar(
    query: str,
    top_k: int = 10,
    source_filter: str | None = None,
    doc_type_filter: str | None = None,
) -> list[dict]:
    """Sorguya en benzer chunk'ları getirir."""
    client = get_client()
    query_vector = get_embedding(query)

    # Filtre oluştur
    conditions = []
    if source_filter:
        conditions.append(
            FieldCondition(key="source", match=MatchValue(value=source_filter))
        )
    if doc_type_filter:
        conditions.append(
            FieldCondition(key="doc_type", match=MatchValue(value=doc_type_filter))
        )

    search_filter = Filter(must=conditions) if conditions else None

    # Hibrit arama: vektör aramasıyla geniş aday havuzu çek, sonra terim eşleşmesiyle yeniden sırala
    results = client.query_points(
        collection_name=settings.collection_name,
        query=query_vector,
        query_filter=search_filter,
        limit=top_k * settings.rerank_candidate_factor,
        with_payload=True,
    )

    candidates = [
        {
            "text": point.payload["text"],
            "title": point.payload["title"],
            "source": point.payload["source"],
            "doc_type": point.payload["doc_type"],
            "url": point.payload.get("url", ""),
            "score": point.score,
        }
        for point in results.points
    ]
    return _rerank(query, candidates)[:top_k]


# Aramada anlam taşımayan Türkçe soru/bağlaç kelimeleri
_STOPWORDS = {
    "ne", "nedir", "neler", "nelerdir", "kaç", "kaçtır", "nasıl", "hangi", "hangisi", "mi", "mı",
    "mu", "mü", "midir", "mıdır", "ve", "veya", "ile", "bir", "bu", "şu", "için", "olan", "olarak",
    "olmalı", "olmalıdır", "gerekir", "gerekiyor", "var", "yok", "da", "de", "ki", "en", "çok",
    "hakkında", "bilgi", "ver", "açıkla",
}


def _stems(text: str) -> list[str]:
    """Türkçe-duyarlı küçük harf + 5 harflik kök yaklaşımı (ekleri kabaca atar)."""
    text = text.replace("İ", "i").replace("I", "ı").lower()
    words = re.findall(r"[%\w,]+", text)
    return [w.rstrip(",")[:5] for w in words if len(w) >= 2 and w not in _STOPWORDS]


def _rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Vektör skorunu sorgu terimlerinin chunk'ta geçme oranıyla harmanlar.
    Unigram kapsama + ardışık terim (bigram) kapsama; ağırlık settings.rerank_weight."""
    q_stems = _stems(query)
    if not q_stems or settings.rerank_weight <= 0:
        return candidates
    q_bigrams = list(zip(q_stems, q_stems[1:]))
    for c in candidates:
        c_stems = _stems(c["title"] + " " + c["text"])
        c_set = set(c_stems)
        c_bigrams = set(zip(c_stems, c_stems[1:]))
        uni = sum(s in c_set for s in q_stems) / len(q_stems)
        bi = sum(b in c_bigrams for b in q_bigrams) / len(q_bigrams) if q_bigrams else uni
        c["vector_score"] = c["score"]
        c["score"] = c["score"] + settings.rerank_weight * (uni + bi) / 2
    return sorted(candidates, key=lambda c: c["score"], reverse=True)


def delete_document(document_id: str):
    """Bir dokümanın tüm chunk'larını siler."""
    client = get_client()
    client.delete(
        collection_name=settings.collection_name,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="document_id", match=MatchValue(value=document_id)
                )
            ]
        ),
    )


def _document_filter(document_id: str) -> Filter:
    return Filter(
        must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
    )


def get_document(document_id: str) -> dict | None:
    """Dokümanın ilk chunk'ının payload'ını döner, yoksa None."""
    client = get_client()
    points, _ = client.scroll(
        collection_name=settings.collection_name,
        scroll_filter=_document_filter(document_id),
        limit=1,
        with_vectors=False,
    )
    return points[0].payload if points else None


def list_documents() -> list[dict]:
    """Qdrant payload'larından doküman listesini çıkarır (chunk'ları document_id'ye göre gruplar)."""
    client = get_client()
    fields = ["document_id", "filename", "title", "source", "doc_type", "date", "url"]
    docs: dict[str, dict] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.collection_name,
            limit=1000,
            offset=offset,
            with_payload=fields,
            with_vectors=False,
        )
        for p in points:
            doc_id = p.payload.get("document_id")
            if not doc_id:
                continue
            if doc_id in docs:
                docs[doc_id]["chunk_count"] += 1
            else:
                docs[doc_id] = {**p.payload, "id": doc_id, "chunk_count": 1}
        if offset is None:
            break
    return list(docs.values())


def get_collection_info() -> dict:
    """Collection bilgilerini döner."""
    client = get_client()
    try:
        info = client.get_collection(settings.collection_name)
        return {
            "name": settings.collection_name,
            "points_count": info.points_count,
            "status": info.status.value,
        }
    except Exception:
        return {"name": settings.collection_name, "points_count": 0, "status": "not_created"}
