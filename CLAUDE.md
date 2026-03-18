# AIRegs - AI Regulation Assistant

Bankacılık sektörüne yönelik RAG tabanlı regülasyon asistanı.

## Proje Yapısı

```
AIRegs/
├── backend/           # FastAPI Python backend
│   ├── app/
│   │   ├── api/       # REST endpoints (chat.py, documents.py)
│   │   ├── core/      # Config (config.py)
│   │   ├── models/    # Pydantic schemas
│   │   └── services/  # İş mantığı (vector_store, llm, embedding, document_processor)
│   ├── crawler.py     # BDDK mevzuat crawler
│   └── spk_crawler.py # SPK PDF crawler
├── frontend/          # Next.js 16 (React + TypeScript)
├── frontend-vue/      # Nuxt 4 (Vue 3 + TypeScript)
└── docker-compose.yml # Qdrant vektör DB
```

## Tech Stack

- **Backend:** FastAPI + Qdrant + LM Studio (Qwen 3 14B) + Nomic Embed v1.5
- **Frontend:** Next.js 16 veya Nuxt 4 (iki seçenek)
- **Veritabanı:** Qdrant (Docker), doküman tracking şu an in-memory dict
- **Dil:** Türkçe birincil (prompt'lar, UI, hata mesajları)

## Geliştirme

```bash
# Backend
cd backend && python -m uvicorn app.main:app --reload  # port 8000

# Frontend (Next.js)
cd frontend && npm run dev  # port 3000

# Frontend (Nuxt)
cd frontend-vue && pnpm dev

# Qdrant
docker-compose up -d
```

## API Endpoints

```
POST /api/chat/stream   # Streaming RAG Q&A
POST /api/chat          # Non-streaming Q&A
POST /api/documents/upload
GET  /api/documents
DELETE /api/documents/{id}
GET  /api/documents/stats
GET  /api/health
```

## Önemli Notlar

- Auth/RBAC henüz yok — production öncesi eklenmeli
- `.env` dosyaları git'e commit edilmemeli
- `backend/data/` dizini (crawled/uploaded content) git'te yok
- LM Studio lokal olarak çalışıyor (localhost:1234)
- Embedding: 768 boyut, Nomic Embed Text v1.5
- Chunking: Önce madde bazlı (MADDE regex), sonra paragraf, sonra sabit boyut
