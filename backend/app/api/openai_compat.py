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


def _build_search_query(question: str, history: list[dict]) -> str:
    """Kısa takip soruları için bağlam ekler."""
    if history and len(question.split()) < 8:
        recent_user = ""
        recent_assistant = ""
        for msg in reversed(history):
            if msg["role"] == "assistant" and not recent_assistant:
                recent_assistant = msg["content"].split(".")[0][:100]
            elif msg["role"] == "user" and not recent_user:
                recent_user = msg["content"]
            if recent_user and recent_assistant:
                break
        return f"{recent_user} {recent_assistant} {question}".strip()
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
    results = search_similar(query=search_query, top_k=5)
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
    return {
        "object": "list",
        "data": [
            {
                "id": "airegs-rag",
                "object": "model",
                "created": 1700000000,
                "owned_by": "airegs",
                "name": "AIRegs RAG Asistanı",
            },
        ],
    }
