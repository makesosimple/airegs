"""
OpenAI-compatible /v1/chat/completions endpoint.
Open WebUI bu endpoint üzerinden AIRegs RAG pipeline'ını kullanır.
"""

import json
import logging
import time
import uuid
from typing import Any
from pydantic import BaseModel
from fastapi import APIRouter
from fastapi.responses import StreamingResponse, JSONResponse
from app.core.config import settings
from app.services.vector_store import search_similar
from app.services.llm import generate_answer, generate_answer_stream

logger = logging.getLogger("openai_compat")
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/v1", tags=["openai-compat"])


class ChatCompletionMessage(BaseModel):
    role: str = ""
    content: Any = ""

class ChatCompletionRequest(BaseModel):
    model: str = "airegs-rag"
    messages: list[ChatCompletionMessage] = []
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


def _extract_question_and_history(messages: list[ChatCompletionMessage]) -> tuple[str, list[dict]]:
    """OpenAI messages formatından son soruyu ve geçmişi çıkarır."""
    history = []
    question = ""

    for msg in messages:
        content = msg.content
        # content bazen list olabiliyor (multimodal)
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = " ".join(text_parts)
        if not isinstance(content, str):
            content = str(content) if content else ""
        if msg.role == "system":
            continue  # system prompt'u biz ekliyoruz
        if content:
            history.append({"role": msg.role, "content": content})

    if history and history[-1]["role"] == "user":
        question = history[-1]["content"]
        history = history[:-1]

    return question, history


def _normalize_query(question: str) -> str:
    """Türkçe typo'ları düzeltmek ve sorguyu aramaya uygun hale getirmek için LLM rewrite.
    Çok ucuz bir çağrı (~50 token in/out). Başarısız olursa orijinali döner."""
    if not question or len(question.strip()) < 2:
        return question
    try:
        from openai import OpenAI
        from app.core.config import settings
        client = OpenAI(base_url=settings.effective_llm_base_url, api_key=settings.effective_llm_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": "Sen Türkçe arama sorgusu normalize edicisin. Kullanıcının sorusundaki yazım hatalarını düzelt (örn: aydat→aidat, sikret→sirket), kısaltma/argo varsa aç. Sadece normalize edilmiş sorguyu döndür, başka hiçbir şey yazma."},
                {"role": "user", "content": question[:300]},
            ],
            temperature=0,
            max_tokens=80,
        )
        fixed = resp.choices[0].message.content.strip().strip('"').strip("'")
        if fixed and len(fixed) < 300:
            logger.info(f"[Query Rewrite] '{question[:60]}' -> '{fixed[:60]}'")
            return fixed
    except Exception as e:
        logger.warning(f"Query rewrite failed: {e}")
    return question


def _build_search_query(question: str, history: list[dict]) -> str:
    """Takip soruları için son konuşma bağlamından arama sorgusu oluşturur."""
    # Önce typo/normalize düzelt
    question = _normalize_query(question)

    if not history:
        return question

    # Özel isim / spesifik terim tespit: büyük harfle başlayan 2+ ardışık kelime
    # varsa soru kendi başına yeterince spesifiktir, geçmişi katma
    import re
    proper_noun_match = re.search(r"\b[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+){1,}", question)
    if proper_noun_match:
        return question

    # Zamir/bağlam göstergesi yoksa geçmişi katma
    pronoun_refs = ["bu", "şu", "o ", "bunun", "onun", "bununla", "bunlar",
                    "onlar", "yukarıdaki", "bahsettiğin", "dediğin", "söylediğin"]
    has_pronoun = any(w in question.lower() for w in pronoun_refs)
    # Çok kısa ve zamir içeren sorular bağlam ister
    very_short = len(question.split()) < 6

    if has_pronoun or very_short:
        # Son 3 user+assistant çiftinden bağlam topla (en yeni önce)
        recent_context_parts = []
        count = 0
        for msg in reversed(history):
            if count >= 6:  # max 3 çift (6 mesaj)
                break
            if msg["role"] == "user":
                recent_context_parts.append(msg["content"][:150])
            elif msg["role"] == "assistant":
                # Assistant cevabından anahtar cümleleri al
                sentences = msg["content"].split(".")
                key_sentences = [s.strip() for s in sentences[:2] if s.strip()]
                recent_context_parts.append(" ".join(key_sentences)[:150])
            count += 1

        recent_context_parts.reverse()
        context_str = " ".join(recent_context_parts)
        query = f"{context_str} {question}".strip()
        # Çok uzun olmasın, embedding modeli için kısalt
        return query[:500]

    return question


def _filter_think_tags(text: str, state: dict) -> str:
    """<think> bloklarını filtreler."""
    result = ""
    for char_chunk in [text]:
        if "<think>" in char_chunk:
            state["in_think"] = True
            char_chunk = char_chunk.split("<think>")[0]
        if state["in_think"]:
            if "</think>" in char_chunk:
                state["in_think"] = False
                char_chunk = char_chunk.split("</think>", 1)[-1]
            else:
                return ""
        result += char_chunk
    return result


@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    messages = request.messages
    stream = request.stream
    model = request.model

    logger.info(f"[OpenAI Compat] model={model}, stream={stream}, messages={len(messages)}")

    question, history = _extract_question_and_history(messages)

    logger.info(f"[OpenAI Compat] question='{question[:100]}', history_len={len(history)}")

    if not question:
        if stream:
            return StreamingResponse(
                iter(["data: [DONE]\n\n"]),
                media_type="text/event-stream",
            )
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Lütfen bir soru sorun."},
                "finish_reason": "stop",
            }],
        })

    # RAG: vektör araması
    search_query = _build_search_query(question, history)
    logger.info(f"[OpenAI Compat] search_query='{search_query[:100]}'")
    results = search_similar(query=search_query, top_k=settings.rag_top_k)
    logger.info(f"[OpenAI Compat] RAG results={len(results)} chunks found")

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())

    if not results:
        no_result_msg = "Üzgünüm, bu soruyla ilgili kaynak bulunamadı."
        if stream:
            def empty_stream():
                chunk = {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": no_result_msg}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                done_chunk = {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(done_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(empty_stream(), media_type="text/event-stream")
        return JSONResponse({
            "id": completion_id, "object": "chat.completion",
            "created": created, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": no_result_msg}, "finish_reason": "stop"}],
        })

    if stream:
        def event_stream():
            # İlk chunk: role
            first = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"

            think_state = {"in_think": False}
            for token in generate_answer_stream(question, results, history):
                text = _filter_think_tags(token, think_state)
                if text:
                    chunk = {
                        "id": completion_id, "object": "chat.completion.chunk",
                        "created": created, "model": model,
                        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            # Son chunk: finish
            done = {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # Non-streaming
    answer = generate_answer(question, results, history)
    return JSONResponse({
        "id": completion_id, "object": "chat.completion",
        "created": created, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@router.get("/models")
async def list_models():
    """Open WebUI model listesi için."""
    model_id = settings.collection_name.replace("_", "-") + "-rag"
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": 1700000000,
                "owned_by": settings.app_name.lower(),
                "name": settings.app_name,
            },
        ],
    }
