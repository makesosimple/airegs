from pydantic import BaseModel
from datetime import datetime
from enum import Enum


class DocumentSource(str, Enum):
    BDDK = "BDDK"
    SPK = "SPK"
    TCMB = "TCMB"
    INTERNAL = "Kurum İçi"
    OTHER = "Diğer"


class DocumentType(str, Enum):
    TEBLIG = "Tebliğ"
    YONETMELIK = "Yönetmelik"
    DUYURU = "Duyuru"
    PROSEDUR = "Prosedür"
    OTHER = "Diğer"


class DocumentUpload(BaseModel):
    source: DocumentSource = DocumentSource.OTHER
    doc_type: DocumentType = DocumentType.OTHER
    title: str | None = None
    date: datetime | None = None


class DocumentInfo(BaseModel):
    id: str
    filename: str
    title: str
    source: DocumentSource
    doc_type: DocumentType
    date: datetime | None
    chunk_count: int
    status: str
    created_at: datetime


class ChatRequest(BaseModel):
    question: str
    source_filter: DocumentSource | None = None
    doc_type_filter: DocumentType | None = None


class SourceReference(BaseModel):
    document_title: str
    source: str
    doc_type: str
    chunk_text: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
