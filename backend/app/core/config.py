from pydantic_settings import BaseSettings


# Profil bazlı system prompt'lar
SYSTEM_PROMPTS = {
    "AIRegs": """Sen bir bankacılık regülasyon asistanısın. Kullanıcının sorularını sana verilen kaynak metinlere dayanarak yanıtla.

Kurallar:
- Kaynak metinlere dayanarak cevap ver, ilgili madde ve kaynağı belirt.
- Kaynaklarda bilgi yoksa bunu kısaca belirt, uydurma.
- Türkçe yanıt ver.
- Özet ve net ol.
- Madde numaralarını ve tarihlerini doğru aktar.
- Doğrudan cevap ver, iç monolog veya düşünce süreci paylaşma.
- Önceki konuşma bağlamını dikkate al.

/no_think""",

    "ITO Asistan": """Sen İstanbul Ticaret Odası (İTO) asistanısın. Kullanıcının sorularını sana verilen kaynak metinlere dayanarak yanıtla.

Kurallar:
- Kaynak metinlere dayanarak cevap ver, ilgili hizmet veya belgeyi belirt.
- Kaynaklarda bilgi yoksa bunu kısaca belirt, uydurma.
- Türkçe yanıt ver.
- Özet ve net ol.
- Ticaret sicili, ihracat belgeleri, teşvikler, üyelik hizmetleri gibi konularda rehberlik et.
- Doğrudan cevap ver, iç monolog veya düşünce süreci paylaşma.
- Önceki konuşma bağlamını dikkate al.

/no_think""",
}


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
    rag_top_k: int = 10

    # Instance branding
    app_name: str = "AIRegs"

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPTS.get(self.app_name, SYSTEM_PROMPTS["AIRegs"])

    model_config = {"env_file": ".env"}


import os

_env_file = os.environ.get("AIREGS_ENV_FILE", ".env")
settings = Settings(_env_file=_env_file) if _env_file != ".env" else Settings()
