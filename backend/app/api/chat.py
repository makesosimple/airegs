import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, ChatResponse, SourceReference
from app.services.vector_store import search_similar
from app.services.llm import generate_answer, generate_answer_stream

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_sources(results: list[dict]) -> list[SourceReference]:
    return [
        SourceReference(
            document_title=r["title"],
            source=r["source"],
            doc_type=r["doc_type"],
            chunk_text=r["text"][:300] + "..." if len(r["text"]) > 300 else r["text"],
            score=round(r["score"], 3),
        )
        for r in results
    ]


def _parse_messages(body: dict) -> tuple[str, list[dict]]:
    """AI SDK messages'dan son soruyu ve konuşma geçmişini çıkarır."""
    messages = body.get("messages", [])
    question = ""
    history = []

    for msg in messages:
        role = msg.get("role", "")
        # parts formatından text çıkar
        parts = msg.get("parts", [])
        text = ""
        for part in parts:
            if part.get("type") == "text":
                text = part.get("text", "")
                break
        if not text:
            text = msg.get("content", "")

        if text:
            history.append({"role": role, "content": text})

    # Son user mesajı = soru, geri kalanı = geçmiş
    if history and history[-1]["role"] == "user":
        question = history[-1]["content"]
        history = history[:-1]  # Son soruyu geçmişten çıkar

    return question, history


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Kullanıcı sorusunu alır, ilgili kaynakları bulur ve cevap üretir."""
    source_filter = request.source_filter.value if request.source_filter else None
    doc_type_filter = request.doc_type_filter.value if request.doc_type_filter else None

    results = search_similar(
        query=request.question, top_k=10,
        source_filter=source_filter, doc_type_filter=doc_type_filter,
    )

    if not results:
        return ChatResponse(answer="Üzgünüm, bu soruyla ilgili kaynak bulunamadı.", sources=[])

    answer = generate_answer(request.question, results)
    return ChatResponse(answer=answer, sources=_get_sources(results))


@router.post("/stream")
async def chat_stream(request: Request):
    """Düz text stream — TextStreamChatTransport uyumlu, bağlam takipli."""
    body = await request.json()

    # Messages array'inden soru ve geçmişi çıkar
    if "messages" in body:
        question, history = _parse_messages(body)
    else:
        question = body.get("question", "")
        history = []

    if not question:
        return StreamingResponse(
            iter(["Lütfen bir soru sorun."]),
            media_type="text/plain; charset=utf-8",
        )

    # RAG aramasını konuşma bağlamıyla zenginleştir
    # Takip soruları için son user sorusu + son assistant cevabının ilk cümlesini kullan
    search_query = question
    if history and len(question.split()) < 8:
        # Kısa takip sorusu — bağlam lazım
        recent_user = ""
        recent_assistant = ""
        for msg in reversed(history):
            if msg["role"] == "assistant" and not recent_assistant:
                # İlk cümleyi al (max 100 karakter)
                first_sentence = msg["content"].split(".")[0][:100]
                recent_assistant = first_sentence
            elif msg["role"] == "user" and not recent_user:
                recent_user = msg["content"]
            if recent_user and recent_assistant:
                break
        search_query = f"{recent_user} {recent_assistant} {question}".strip()

    results = search_similar(query=search_query, top_k=10)

    def text_stream():
        if not results:
            yield "Üzgünüm, bu soruyla ilgili kaynak bulunamadı."
            return

        in_think = False
        for chunk_text in generate_answer_stream(question, results, history):
            text = chunk_text
            if "<think>" in text:
                in_think = True
                text = text.split("<think>")[0]
            if in_think:
                if "</think>" in text:
                    in_think = False
                    text = text.split("</think>", 1)[-1]
                else:
                    continue
            if text:
                yield text

    return StreamingResponse(
        text_stream(),
        media_type="text/plain; charset=utf-8",
    )
