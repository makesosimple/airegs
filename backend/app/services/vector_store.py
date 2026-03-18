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

    results = client.query_points(
        collection_name=settings.collection_name,
        query=query_vector,
        query_filter=search_filter,
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "text": point.payload["text"],
            "title": point.payload["title"],
            "source": point.payload["source"],
            "doc_type": point.payload["doc_type"],
            "score": point.score,
        }
        for point in results.points
    ]


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
