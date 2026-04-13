"""
Embedding servisi — iki mod destekler:

1. 'openai': LM Studio veya OpenAI-uyumlu herhangi bir API (EMBEDDING_BACKEND=openai)
2. 'local': sentence-transformers ile lokal CPU/GPU inference (EMBEDDING_BACKEND=local)

Nomic Embed v1.5 Türkçe destekli, 768 boyutlu çıktı verir.
"""

from __future__ import annotations
from app.core.config import settings


_local_model = None


def _get_local_model():
    """sentence-transformers modelini lazy olarak yükler."""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        # Nomic Embed v1.5 HuggingFace üzerinden
        model_name = settings.local_embedding_model
        _local_model = SentenceTransformer(model_name, trust_remote_code=True)
    return _local_model


def _get_openai_client():
    from openai import OpenAI
    return OpenAI(
        base_url=settings.lm_studio_base_url,
        api_key=settings.lm_studio_api_key,
    )


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Metinleri Nomic Embed ile vektöre çevirir."""
    if settings.embedding_backend == "local":
        model = _get_local_model()
        # Nomic v1.5 'search_document: ' prefix bekler (kaynak metin için)
        prefixed = [f"search_document: {t}" for t in texts]
        vecs = model.encode(prefixed, convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)
        return vecs.tolist()

    # OpenAI-uyumlu API
    client = _get_openai_client()
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


def get_embedding(text: str) -> list[float]:
    """Tek bir metni vektöre çevirir (sorgu)."""
    if settings.embedding_backend == "local":
        model = _get_local_model()
        # Sorgu için 'search_query: ' prefix
        vec = model.encode([f"search_query: {text}"], convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)[0]
        return vec.tolist()
    return get_embeddings([text])[0]
