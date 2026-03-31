from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import chat, documents, openai_compat
from app.services.vector_store import ensure_collection

app = FastAPI(
    title="AI Regülasyon Asistanı",
    description="Bankacılık regülasyonları için AI destekli soru-cevap sistemi",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(openai_compat.router)


@app.on_event("startup")
async def startup():
    ensure_collection()


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "AI Regülasyon Asistanı"}
