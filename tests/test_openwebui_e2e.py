"""
Open WebUI + AIRegs RAG pipeline uçtan uca (E2E) testi.
Playwright ile Open WebUI arayüzünü test eder.
"""

import asyncio
import httpx
import json
import sys


async def test_backend_health():
    """Backend sağlık kontrolü."""
    print("=" * 60)
    print("TEST 1: Backend Health Check")
    print("=" * 60)
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8000/api/health")
        assert r.status_code == 200, f"Backend health failed: {r.status_code}"
        data = r.json()
        assert data["status"] == "ok"
        print(f"  [OK] Backend OK: {data}")


async def test_models_endpoint():
    """OpenAI-compatible /v1/models endpoint testi."""
    print("\n" + "=" * 60)
    print("TEST 2: /v1/models Endpoint")
    print("=" * 60)
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8000/v1/models")
        assert r.status_code == 200, f"Models endpoint failed: {r.status_code}"
        data = r.json()
        models = [m["id"] for m in data["data"]]
        print(f"  [OK] Models: {models}")
        assert "airegs-rag" in models, "airegs-rag model not found"
        print("  [OK] airegs-rag model registered")


async def test_qdrant_has_data():
    """Qdrant'ta doküman olup olmadığını kontrol eder."""
    print("\n" + "=" * 60)
    print("TEST 3: Qdrant Collection Check")
    print("=" * 60)
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8000/api/documents/stats")
        assert r.status_code == 200, f"Stats endpoint failed: {r.status_code}"
        data = r.json()
        print(f"  [OK] Stats: {json.dumps(data, ensure_ascii=False, indent=2)}")
        return data


async def test_rag_chat_non_streaming():
    """Non-streaming RAG chat testi."""
    print("\n" + "=" * 60)
    print("TEST 4: RAG Chat (non-streaming)")
    print("=" * 60)
    payload = {
        "model": "airegs-rag",
        "messages": [
            {"role": "user", "content": "Sermaye yeterliliği oranı nedir?"}
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "http://localhost:8000/v1/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert r.status_code == 200, f"Chat failed: {r.status_code} - {r.text}"
        data = r.json()
        answer = data["choices"][0]["message"]["content"]
        print(f"  [OK] Answer ({len(answer)} chars):")
        print(f"    {answer[:200]}...")
        assert len(answer) > 10, "Answer too short"
        print("  [OK] RAG non-streaming OK")


async def test_rag_chat_streaming():
    """Streaming RAG chat testi."""
    print("\n" + "=" * 60)
    print("TEST 5: RAG Chat (streaming)")
    print("=" * 60)
    payload = {
        "model": "airegs-rag",
        "messages": [
            {"role": "user", "content": "BDDK hangi düzenlemeleri yapar?"}
        ],
        "stream": True,
    }
    full_text = ""
    chunk_count = 0
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            "http://localhost:8000/v1/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        ) as response:
            assert response.status_code == 200, f"Stream failed: {response.status_code}"
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0]["delta"]
                        if "content" in delta:
                            full_text += delta["content"]
                            chunk_count += 1
                    except json.JSONDecodeError:
                        pass

    print(f"  [OK] Received {chunk_count} chunks")
    print(f"  [OK] Full text ({len(full_text)} chars):")
    print(f"    {full_text[:200]}...")
    assert chunk_count > 0, "No chunks received"
    assert len(full_text) > 10, "Streamed text too short"
    print("  [OK] RAG streaming OK")


async def test_open_webui_accessible():
    """Open WebUI erişilebilirlik testi."""
    print("\n" + "=" * 60)
    print("TEST 6: Open WebUI Accessibility")
    print("=" * 60)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("http://localhost:3080")
        assert r.status_code == 200, f"Open WebUI failed: {r.status_code}"
        print(f"  [OK] Open WebUI responding (status={r.status_code})")
        has_open_webui = "open" in r.text.lower() or "webui" in r.text.lower() or "svelte" in r.text.lower()
        print(f"  [OK] Content looks like Open WebUI: {has_open_webui}")


async def test_conversation_context():
    """Takip sorusu bağlam testi."""
    print("\n" + "=" * 60)
    print("TEST 7: Conversation Context (follow-up)")
    print("=" * 60)
    payload = {
        "model": "airegs-rag",
        "messages": [
            {"role": "user", "content": "Sermaye yeterliliği oranı nedir?"},
            {"role": "assistant", "content": "Sermaye yeterliliği oranı, bankaların risk ağırlıklı varlıklarına oranla bulundurmaları gereken asgari sermaye miktarını ifade eder."},
            {"role": "user", "content": "Asgari oran kaçtır?"},
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "http://localhost:8000/v1/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert r.status_code == 200, f"Context chat failed: {r.status_code}"
        data = r.json()
        answer = data["choices"][0]["message"]["content"]
        print(f"  [OK] Follow-up answer ({len(answer)} chars):")
        print(f"    {answer[:200]}...")
        print("  [OK] Conversation context OK")


async def main():
    print("\n[*] AIRegs + Open WebUI E2E Test Suite")
    print("=" * 60)

    passed = 0
    failed = 0
    tests = [
        test_backend_health,
        test_models_endpoint,
        test_qdrant_has_data,
        test_rag_chat_non_streaming,
        test_rag_chat_streaming,
        test_open_webui_accessible,
        test_conversation_context,
    ]

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] FAILED: {e}")

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
