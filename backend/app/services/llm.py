import re
from typing import Generator

from openai import OpenAI
from app.core.config import settings


client = OpenAI(
    base_url=settings.lm_studio_base_url,
    api_key=settings.lm_studio_api_key,
)

SYSTEM_PROMPT = """Sen bir bankacılık regülasyon asistanısın. Kullanıcının sorularını sana verilen kaynak metinlere dayanarak yanıtla.

Kurallar:
- Kaynak metinlere dayanarak cevap ver, ilgili madde ve kaynağı belirt.
- Kaynaklarda bilgi yoksa bunu kısaca belirt, uydurma.
- Türkçe yanıt ver.
- Özet ve net ol.
- Madde numaralarını ve tarihlerini doğru aktar.
- Doğrudan cevap ver, iç monolog veya düşünce süreci paylaşma.
- Önceki konuşma bağlamını dikkate al.

/no_think"""


def _trim_history(history: list[dict], max_pairs: int = 4) -> list[dict]:
    """Son N user-assistant çiftini korur, gerisini atar.
    Çok uzun geçmiş LLM'in dikkatini dağıtır ve bağlam takibini bozar."""
    if not history:
        return []
    # Son max_pairs * 2 mesajı al
    max_msgs = max_pairs * 2
    if len(history) <= max_msgs:
        return history
    return history[-max_msgs:]


def _build_messages(
    question: str,
    context_chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> list[dict]:
    context_text = "\n\n---\n\n".join(
        f"[Kaynak: {c['title']} | {c['source']} | {c['doc_type']}]\n{c['text']}"
        for c in context_chunks
    )

    messages = [
        {
            "role": "system",
            "content": f"{SYSTEM_PROMPT}\n\nKaynak metinler:\n\n{context_text}",
        },
    ]

    # Son konuşma geçmişini ekle (max 4 çift = 8 mesaj)
    if conversation_history:
        trimmed = _trim_history(conversation_history)
        for msg in trimmed:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

    # Son soruyu ekle
    messages.append({"role": "user", "content": question})

    return messages


def generate_answer(
    question: str,
    context_chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> str:
    """Kaynak metinlerle birlikte soruyu LLM'e gönderir."""
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=_build_messages(question, context_chunks, conversation_history),
        temperature=0.1,
        max_tokens=2048,
    )
    content = response.choices[0].message.content
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return content


def generate_answer_stream(
    question: str,
    context_chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """Kaynak metinlerle birlikte soruyu LLM'e gönderir, streaming olarak."""
    stream = client.chat.completions.create(
        model=settings.llm_model,
        messages=_build_messages(question, context_chunks, conversation_history),
        temperature=0.1,
        max_tokens=2048,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
