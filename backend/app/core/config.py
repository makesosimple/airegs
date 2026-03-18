from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_api_key: str = "lm-studio"
    llm_model: str = "qwen3-14b"
    embedding_model: str = "text-embedding-nomic-embed-text-v1.5"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    collection_name: str = "regulations"
    chunk_size: int = 512
    chunk_overlap: int = 50

    model_config = {"env_file": ".env"}


settings = Settings()
