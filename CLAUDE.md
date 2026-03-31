# AIRegs - AI Regulation Assistant

Bankacılık sektörüne yönelik RAG tabanlı regülasyon asistanı.

## Proje Yapısı

```
AIRegs/
├── backend/           # FastAPI Python backend
│   ├── app/
│   │   ├── api/       # REST endpoints (chat.py, documents.py, openai_compat.py)
│   │   ├── core/      # Config (config.py)
│   │   ├── models/    # Pydantic schemas
│   │   └── services/  # İş mantığı (vector_store, llm, embedding, document_processor)
│   ├── crawler.py     # BDDK mevzuat crawler
│   └── spk_crawler.py # SPK PDF crawler
├── frontend/          # Next.js 16 (React + TypeScript) — eski arayüz
├── frontend-vue/      # Nuxt 4 (Vue 3 + TypeScript) — eski arayüz
├── tests/             # E2E testler (Playwright + httpx)
├── backups/           # Qdrant DB yedekleri
└── docker-compose.yml # Qdrant + Open WebUI
```

## Tech Stack

- **Backend:** FastAPI + Qdrant + LM Studio (Qwen 3 14B / Qwen 3.5 35B-A3B) + Nomic Embed v1.5
- **Frontend:** Open WebUI (Docker, port 3080) — RAG backend'e OpenAI-compatible API ile bağlı
- **Veritabanı:** Qdrant (Docker, port 6333), doküman tracking şu an in-memory dict
- **Dil:** Türkçe birincil (prompt'lar, UI locale tr-TR, hata mesajları)

## Mimari

```
Open WebUI (3080) → /v1/chat/completions → FastAPI Backend (8000)
                                              ├── Qdrant vektör arama (6333)
                                              └── LM Studio LLM (1234)
```

Open WebUI sadece arayüz olarak kullanılıyor. RAG pipeline (chunking, vektör arama, prompt oluşturma) tamamen backend'de.

## Geliştirme

```bash
# Backend (venv aktif olmalı)
cd backend && source venv/Scripts/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Docker servisleri (Qdrant + Open WebUI)
docker compose up -d

# E2E testler
cd backend && source venv/Scripts/activate
python tests/test_openwebui_e2e.py

# Qdrant yedekleme
docker exec airegs-qdrant sh -c "cd /qdrant/storage && tar czf /tmp/qdrant_backup.tar.gz ."
docker cp airegs-qdrant:/tmp/qdrant_backup.tar.gz backups/qdrant_backup_$(date +%Y%m%d).tar.gz
```

## API Endpoints

```
# Orijinal API
POST /api/chat/stream   # Streaming RAG Q&A
POST /api/chat          # Non-streaming Q&A
POST /api/documents/upload
GET  /api/documents
DELETE /api/documents/{id}
GET  /api/documents/stats
GET  /api/health

# OpenAI-compatible API (Open WebUI bağlantısı)
POST /v1/chat/completions   # Streaming + non-streaming RAG
GET  /v1/models             # Model listesi (airegs-rag)
```

## Önemli Notlar

- Open WebUI auth aktif — ilk kayıt olan admin olur
- `.env` dosyaları git'e commit edilmemeli
- `backend/data/` dizini (crawled/uploaded content) git'te yok
- `backups/` dizini git'te yok (büyük dosyalar)
- LM Studio lokal olarak çalışıyor (localhost:1234)
- Embedding: 768 boyut, Nomic Embed Text v1.5
- Chunking: Önce madde bazlı (MADDE regex), sonra paragraf, sonra sabit boyut
- Qdrant'ta 22.000+ chunk mevcut (regulations koleksiyonu)
