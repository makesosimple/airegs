import os
import uuid
from datetime import datetime

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from bs4 import BeautifulSoup

from app.core.config import settings
from app.models.schemas import DocumentSource, DocumentType


def extract_text(file_path: str, content_type: str) -> str:
    """Dosyadan metin çıkarır (PDF, DOCX, HTML, TXT)."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf" or "pdf" in content_type:
        return _extract_pdf(file_path)
    elif ext == ".docx" or "word" in content_type:
        return _extract_docx(file_path)
    elif ext in (".html", ".htm") or "html" in content_type:
        return _extract_html(file_path)
    else:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()


def _extract_pdf(file_path: str) -> str:
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    doc.close()
    return text


def _extract_docx(file_path: str) -> str:
    doc = DocxDocument(file_path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_html(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    return soup.get_text(separator="\n", strip=True)


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> list[str]:
    """Metni madde/paragraf bazlı veya sabit boyutlu parçalara böler."""
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap

    # Önce madde bazlı bölmeyi dene (Madde 1, MADDE 1, vb.)
    import re
    article_pattern = re.compile(
        r"(?=(?:MADDE|Madde)\s+\d+)", re.IGNORECASE
    )
    articles = article_pattern.split(text)
    articles = [a.strip() for a in articles if a.strip()]

    # Madde bazlı bölme başarılıysa (en az 3 madde bulunduysa)
    if len(articles) >= 3:
        chunks = []
        for article in articles:
            if len(article) <= chunk_size * 2:
                chunks.append(article)
            else:
                # Uzun maddeleri alt parçalara böl
                chunks.extend(_split_by_size(article, chunk_size, overlap))
        return chunks

    # Paragraf bazlı bölme
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) >= 3:
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) > chunk_size and current:
                chunks.append(current.strip())
                # Overlap: son cümleyi sonraki chunk'a taşı
                sentences = current.split(".")
                current = sentences[-1] + ". " if len(sentences) > 1 else ""
            current += para + "\n\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks

    # Son çare: sabit boyut
    return _split_by_size(text, chunk_size, overlap)


def _split_by_size(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


def prepare_document_metadata(
    filename: str,
    source: DocumentSource,
    doc_type: DocumentType,
    title: str | None = None,
    date: datetime | None = None,
) -> dict:
    """Doküman metadata'sını hazırlar."""
    return {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "title": title or os.path.splitext(filename)[0],
        "source": source.value,
        "doc_type": doc_type.value,
        "date": (date or datetime.now()).isoformat(),
        "created_at": datetime.now().isoformat(),
    }
