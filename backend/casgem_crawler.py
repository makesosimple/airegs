"""
ÇASGEM Mevzuat Crawler
https://casgem.gov.tr/kurumsal/mevzuatlar/ adresindeki tüm mevzuatları
HTML'den çıkarır ve Qdrant vektör veritabanına indeksler.
"""

import os
import sys
import json
import time
import re
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from app.services.document_processor import chunk_text, prepare_document_metadata
from app.services.vector_store import index_document, ensure_collection
from app.models.schemas import DocumentSource, DocumentType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("casgem_crawler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

BASE_URL = "https://casgem.gov.tr"
MEVZUAT_URL = f"{BASE_URL}/kurumsal/mevzuatlar/"
CRAWL_DELAY = 1.5
DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "casgem")
STATE_FILE = os.path.join(DATA_DIR, "casgem_crawl_state.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIRegs Crawler/1.0",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"indexed": [], "errors": [], "last_run": None}


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_mevzuat_links() -> list[dict]:
    """Ana sayfadan tüm mevzuat linklerini çek."""
    resp = requests.get(MEVZUAT_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/poco-pages/mevzuatlar/" in href and href.rstrip("/") != "/poco-pages/mevzuatlar":
            full_url = href if href.startswith("http") else BASE_URL + href
            slug = href.rstrip("/").split("/")[-1]

            # Title: önce link metni, yoksa parent element, yoksa slug'dan üret
            title = a.get_text(strip=True)
            if not title:
                parent = a.find_parent(["li", "div", "td", "article"])
                if parent:
                    title = parent.get_text(strip=True)[:200]
            if not title:
                title = slug.replace("-", " ").upper()

            links.append({
                "title": title,
                "url": full_url,
                "slug": slug,
            })

    # Deduplicate by slug
    seen = set()
    unique = []
    for link in links:
        if link["slug"] not in seen:
            seen.add(link["slug"])
            unique.append(link)

    return unique


def extract_text_from_page(url: str) -> str:
    """Mevzuat sayfasından metin çıkar."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Ana içerik alanını bul
    content = soup.find("div", class_="page-content") or \
              soup.find("div", class_="content") or \
              soup.find("article") or \
              soup.find("main")

    if not content:
        # Fallback: body'den nav/header/footer çıkar
        content = soup.find("body")
        if content:
            for tag in content.find_all(["nav", "header", "footer", "script", "style"]):
                tag.decompose()

    if not content:
        return ""

    text = content.get_text(separator="\n", strip=True)

    # Gereksiz boş satırları temizle
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text = "\n".join(lines)

    return text


def classify_doc_type(title: str) -> DocumentType:
    """Başlığa göre doküman tipini belirle."""
    title_lower = title.lower()
    if "kanun" in title_lower:
        return DocumentType.OTHER  # Kanun
    elif "kararname" in title_lower:
        return DocumentType.OTHER
    elif "tebliğ" in title_lower:
        return DocumentType.TEBLIG
    elif "yönetmelik" in title_lower or "yonetmelik" in title_lower:
        return DocumentType.YONETMELIK
    elif "yönerge" in title_lower or "yonerge" in title_lower:
        return DocumentType.OTHER
    else:
        return DocumentType.OTHER


def crawl_and_index():
    """Tüm ÇASGEM mevzuatlarını indir ve indeksle."""
    ensure_collection()
    state = load_state()
    os.makedirs(DATA_DIR, exist_ok=True)

    stats = {"success": 0, "skipped": 0, "errors": 0, "total_chunks": 0}

    logger.info("ÇASGEM mevzuat listesi alınıyor...")
    links = get_mevzuat_links()
    logger.info(f"{len(links)} mevzuat bulundu")

    for i, doc in enumerate(links, 1):
        slug = doc["slug"]

        if slug in state["indexed"]:
            logger.info(f"[{i}/{len(links)}] ATLA (zaten var): {doc['title'][:60]}")
            stats["skipped"] += 1
            continue

        logger.info(f"[{i}/{len(links)}] İndiriliyor: {doc['title'][:60]}...")

        try:
            text = extract_text_from_page(doc["url"])

            if len(text) < 100:
                logger.warning(f"  Metin çok kısa ({len(text)} karakter), atlanıyor")
                state["errors"].append({"slug": slug, "error": "Metin çok kısa"})
                stats["errors"] += 1
                continue

            # Chunk'la
            chunks = chunk_text(text)
            logger.info(f"  {len(chunks)} chunk oluşturuldu ({len(text)} karakter)")

            # Metadata hazırla
            doc_type = classify_doc_type(doc["title"])
            metadata = prepare_document_metadata(
                filename=f"{slug}.html",
                title=doc["title"],
                source=DocumentSource.OTHER,
                doc_type=doc_type,
            )

            # Qdrant'a indeksle
            index_document(metadata, chunks)

            state["indexed"].append(slug)
            stats["success"] += 1
            stats["total_chunks"] += len(chunks)
            logger.info(f"  OK: {doc['title'][:60]} ({len(chunks)} chunk)")

            # Metni kaydet
            text_path = os.path.join(DATA_DIR, f"{slug}.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text)

        except Exception as e:
            logger.error(f"  HATA: {e}")
            state["errors"].append({"slug": slug, "error": str(e)})
            stats["errors"] += 1

        save_state(state)
        time.sleep(CRAWL_DELAY)

    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    logger.info("=" * 60)
    logger.info(f"ÇASGEM Crawler tamamlandı!")
    logger.info(f"  Başarılı: {stats['success']}")
    logger.info(f"  Atlanan : {stats['skipped']}")
    logger.info(f"  Hatalı  : {stats['errors']}")
    logger.info(f"  Chunk   : {stats['total_chunks']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    crawl_and_index()
