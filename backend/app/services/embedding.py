from openai import OpenAI
from app.core.config import settings


client = OpenAI(
    base_url=settings.lm_studio_base_url,
    api_key=settings.lm_studio_api_key,
)


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Metinleri Nomic Embed ile vektöre çevirir."""
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


def get_embedding(text: str) -> list[float]:
    """Tek bir metni vektöre çevirir."""
    return get_embeddings([text])[0]
