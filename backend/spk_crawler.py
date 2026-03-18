"""
SPK Mevzuat Crawler
SPK mevzuat sisteminden tüm mevzuat ve rehberleri PDF olarak indirir,
metinleri çıkarır ve Qdrant vektör veritabanına indeksler.
"""

import os
import sys
import json
import time
import logging
import tempfile
from datetime import datetime

import requests
import urllib3

# SSL uyarılarını bastır (SPK sertifika sorunu var)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Backend app imports
sys.path.insert(0, os.path.dirname(__file__))
from app.services.document_processor import extract_text, chunk_text, prepare_document_metadata
from app.services.vector_store import index_document, ensure_collection
from app.models.schemas import DocumentSource, DocumentType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("spk_crawler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

SPK_API = "https://mevzuat.spk.gov.tr/api"
CRAWL_DELAY = 1.0
DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "spk")
STATE_FILE = os.path.join(DATA_DIR, "spk_crawl_state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"indexed": [], "errors": [], "last_run": None}


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_list(endpoint: str) -> list[dict]:
    """SPK API'den liste çek."""
    url = f"{SPK_API}/{endpoint}"
    resp = requests.get(url, verify=False, timeout=30)
    resp.raise_for_status()
    return resp.json()


def download_pdf(endpoint: str, doc_id: int) -> str | None:
    """PDF indir, geçici dosya yolunu döndür."""
    url = f"{SPK_API}/{endpoint}/File/{doc_id}"
    resp = requests.get(url, verify=False, timeout=60)

    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or "html" in content_type:
        return None

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=DATA_DIR)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


def map_doc_type(tur: str) -> DocumentType:
    """SPK doküman türünü enum'a çevir."""
    tur_lower = tur.lower() if tur else ""
    if "tebliğ" in tur_lower:
        return DocumentType.TEBLIG
    elif "yönetmelik" in tur_lower:
        return DocumentType.YONETMELIK
    else:
        return DocumentType.OTHER


def crawl_and_index():
    """Tüm SPK mevzuat ve rehberlerini indir ve indeksle."""
    ensure_collection()
    state = load_state()
    os.makedirs(DATA_DIR, exist_ok=True)

    stats = {"success": 0, "skipped": 0, "errors": 0, "total_chunks": 0}

    # 1) Mevzuatlar
    logger.info("SPK mevzuat listesi alınıyor...")
    mevzuatlar = fetch_list("Mevzuat/List")
    logger.info(f"{len(mevzuatlar)} mevzuat bulundu")

    # 2) Rehberler
    logger.info("SPK rehber listesi alınıyor...")
    rehberler = fetch_list("Rehber/List")
    logger.info(f"{len(rehberler)} rehber bulundu")

    # Hepsini birleştir
    all_docs = []
    for m in mevzuatlar:
        all_docs.append({
            "id": m["id"],
            "title": m["title"],
            "tur": m.get("tur", "Diğer"),
            "endpoint": "Mevzuat",
            "key": f"mevzuat_{m['id']}",
            "date": m.get("resmiGazeteTarih"),
        })
    for r in rehberler:
        all_docs.append({
            "id": r["id"],
            "title": r.get("title", r.get("isim", f"Rehber {r['id']}")),
            "tur": "Rehber",
            "endpoint": "Rehber",
            "key": f"rehber_{r['id']}",
            "date": r.get("resmiGazeteTarih"),
        })

    logger.info(f"Toplam {len(all_docs)} doküman işlenecek")

    for i, doc in enumerate(all_docs, 1):
        key = doc["key"]

        if key in state["indexed"]:
            logger.info(f"[{i}/{len(all_docs)}] ATLA (zaten var): {doc['title'][:60]}")
            stats["skipped"] += 1
            continue

        logger.info(f"[{i}/{len(all_docs)}] İndiriliyor: {doc['title'][:60]}...")

        try:
            pdf_path = download_pdf(doc["endpoint"], doc["id"])
            if not pdf_path:
                logger.warning(f"  PDF indirilemedi: {doc['title'][:60]}")
                state["errors"].append({"key": key, "error": "PDF indirilemedi"})
                stats["errors"] += 1
                continue

            # Text çıkar
            text = extract_text(pdf_path, "application/pdf")

            # Geçici PDF'i sil
            try:
                os.unlink(pdf_path)
            except OSError:
                pass

            if not text or len(text.strip()) < 50:
                logger.warning(f"  Metin çok kısa/boş: {doc['title'][:60]}")
                state["errors"].append({"key": key, "error": "Metin boş"})
                stats["errors"] += 1
                continue

            # Chunk'la
            chunks = chunk_text(text)
            logger.info(f"  {len(chunks)} chunk oluşturuldu ({len(text)} karakter)")

            # Tarih parse
            doc_date = None
            if doc.get("date"):
                try:
                    doc_date = datetime.fromisoformat(doc["date"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            # Metadata hazırla
            metadata = prepare_document_metadata(
                filename=f"spk_{doc['endpoint'].lower()}_{doc['id']}.pdf",
                source=DocumentSource.SPK,
                doc_type=map_doc_type(doc["tur"]),
                title=doc["title"],
                date=doc_date,
            )

            # Qdrant'a yaz
            n_indexed = index_document(metadata, chunks)
            stats["total_chunks"] += n_indexed

            state["indexed"].append(key)
            save_state(state)

            stats["success"] += 1
            logger.info(f"  OK — {n_indexed} chunk indekslendi")

        except Exception as e:
            logger.error(f"  HATA: {e}")
            state["errors"].append({"key": key, "error": str(e)})
            stats["errors"] += 1

        time.sleep(CRAWL_DELAY)

    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    logger.info(
        f"\n{'='*50}\n"
        f"SPK Crawler Tamamlandı!\n"
        f"Başarılı: {stats['success']}\n"
        f"Atlanan: {stats['skipped']}\n"
        f"Hata: {stats['errors']}\n"
        f"Toplam chunk: {stats['total_chunks']}\n"
        f"{'='*50}"
    )


if __name__ == "__main__":
    crawl_and_index()
