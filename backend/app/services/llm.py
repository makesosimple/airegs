from __future__ import annotations
import re
from typing import Generator, NamedTuple

from openai import OpenAI
from app.core.config import settings


class LLMProfile(NamedTuple):
    base_url: str
    api_key: str
    model: str


# Ön tanımlı profiller — model adına göre backend seçer
LLM_PROFILES: dict[str, LLMProfile] = {
    "ito-docs-rag": LLMProfile(
        base_url=settings.effective_llm_base_url,
        api_key=settings.effective_llm_api_key,
        model=settings.llm_model,
    ),
    "ito-qwen-rag": LLMProfile(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        model="qwen3:1.7b",
    ),
}


def get_profile(model_name: str) -> LLMProfile:
    """Model adına göre doğru LLM profilini döner, yoksa default."""
    return LLM_PROFILES.get(model_name, LLM_PROFILES["ito-docs-rag"])


# Her profil için bir client instance cache
_clients: dict[str, OpenAI] = {}


def _get_client(profile: LLMProfile) -> OpenAI:
    key = profile.base_url
    if key not in _clients:
        _clients[key] = OpenAI(base_url=profile.base_url, api_key=profile.api_key)
    return _clients[key]


SYSTEM_PROMPT = settings.system_prompt


def _trim_history(history: list[dict], max_pairs: int = 4) -> list[dict]:
    """Son N user-assistant çiftini korur, gerisini atar."""
    if not history:
        return []
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

    if conversation_history:
        trimmed = _trim_history(conversation_history)
        for msg in trimmed:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

    messages.append({"role": "user", "content": question})
    return messages


def generate_answer(
    question: str,
    context_chunks: list[dict],
    conversation_history: list[dict] | None = None,
    model_name: str = "ito-docs-rag",
) -> str:
    profile = get_profile(model_name)
    client = _get_client(profile)
    response = client.chat.completions.create(
        model=profile.model,
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
    model_name: str = "ito-docs-rag",
) -> Generator[str, None, None]:
    profile = get_profile(model_name)
    client = _get_client(profile)
    stream = client.chat.completions.create(
        model=profile.model,
        messages=_build_messages(question, context_chunks, conversation_history),
        temperature=0.1,
        max_tokens=2048,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
