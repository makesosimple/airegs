import os
import shutil
from datetime import datetime

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from app.core.config import settings
from app.models.schemas import DocumentInfo, DocumentSource, DocumentType
from app.services.document_processor import (
    chunk_text,
    extract_text,
    prepare_document_metadata,
)
from app.services.vector_store import (
    delete_document,
    get_collection_info,
    index_document,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Basit in-memory doküman kaydı (production'da DB kullanılır)
_documents: dict[str, DocumentInfo] = {}

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "documents")


@router.post("/upload", response_model=DocumentInfo)
async def upload_document(
    file: UploadFile = File(...),
    source: DocumentSource = Form(DocumentSource.OTHER),
    doc_type: DocumentType = Form(DocumentType.OTHER),
    title: str = Form(None),
    date: str = Form(None),
):
    """Doküman yükler, parse eder, chunk'lar ve indeksler."""

    # Dosyayı kaydet
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        # Metin çıkar
        text = extract_text(file_path, file.content_type or "")
        if not text.strip():
            raise HTTPException(status_code=400, detail="Dosyadan metin çıkarılamadı.")

        # Chunk'la
        chunks = chunk_text(text)

        # Metadata hazırla
        parsed_date = datetime.fromisoformat(date) if date else None
        metadata = prepare_document_metadata(
            filename=file.filename,
            source=source,
            doc_type=doc_type,
            title=title,
            date=parsed_date,
        )

        # Vektör veritabanına indeksle
        chunk_count = index_document(metadata, chunks)

        # Kayıt oluştur
        doc_info = DocumentInfo(
            id=metadata["id"],
            filename=file.filename,
            title=metadata["title"],
            source=source,
            doc_type=doc_type,
            date=parsed_date,
            chunk_count=chunk_count,
            status="indexed",
            created_at=datetime.now(),
        )
        _documents[doc_info.id] = doc_info

        return doc_info

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Doküman işlenirken hata: {str(e)}")


@router.get("", response_model=list[DocumentInfo])
async def list_documents():
    """Yüklenen dokümanları listeler."""
    return list(_documents.values())


@router.delete("/{document_id}")
async def remove_document(document_id: str):
    """Dokümanı ve indeksini siler."""
    if document_id not in _documents:
        raise HTTPException(status_code=404, detail="Doküman bulunamadı.")

    delete_document(document_id)
    doc = _documents.pop(document_id)

    # Dosyayı da sil
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    return {"message": "Doküman silindi.", "id": document_id}


@router.get("/stats")
async def document_stats():
    """Koleksiyon istatistiklerini döner."""
    return get_collection_info()
