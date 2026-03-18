"""
BDDK Mevzuat Crawler
Tüm BDDK mevzuat sayfalarını ve bağlantılı mevzuat.gov.tr dokümanlarını
recursive olarak tarar, metinleri çıkarır ve vektör veritabanına indeksler.
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Backend app imports
import sys
sys.path.insert(0, os.path.dirname(__file__))
from app.services.document_processor import chunk_text, prepare_document_metadata
from app.services.vector_store import index_document, ensure_collection
from app.models.schemas import DocumentSource, DocumentType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("crawler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Ayarlar
BDDK_BASE = "https://www.bddk.gov.tr"
MEVZUAT_GOV_BASE = "https://mevzuat.gov.tr"
CRAWL_DELAY = 1.5  # Sunucuya nazik olalım (saniye)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "crawled")
STATE_FILE = os.path.join(DATA_DIR, "crawl_state.json")

# BDDK mevzuat kategori sayfaları
CATEGORY_PAGES = {
    "Kanunlar": "/Mevzuat/Liste/49",
    "Bankacılık Kanununa İlişkin Düzenlemeler": "/Mevzuat/Liste/50",
    "Banka Kartları ve Kredi Kartları Kanununa İlişkin Düzenlemeler": "/Mevzuat/Liste/51",
    "Finansal Kiralama Faktoring Finansman Düzenlemeleri": "/Mevzuat/Liste/52",
    "BDDK Kurumuna İlişkin Düzenlemeler": "/Mevzuat/Liste/54",
    "Resmi Gazetede Yayımlanan Kurul Kararları": "/Mevzuat/Liste/55",
    "Resmi Gazetede Yayımlanmayan Kurul Kararları": "/Mevzuat/Liste/56",
    "Düzenleme Taslakları": "/Mevzuat/Liste/58",
    "Mülga Düzenlemeler": "/Mevzuat/Liste/63",
}

# Doküman türü tespiti
DOC_TYPE_MAP = {
    "yönetmelik": DocumentType.YONETMELIK,
    "tebliğ": DocumentType.TEBLIG,
    "kanun": DocumentType.OTHER,
    "karar": DocumentType.DUYURU,
    "genelge": DocumentType.DUYURU,
    "rehber": DocumentType.OTHER,
    "prosedür": DocumentType.PROSEDUR,
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})


def load_state() -> dict:
    """Önceki tarama durumunu yükler (kaldığı yerden devam için)."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"crawled_urls": [], "indexed_docs": [], "errors": []}


def save_state(state: dict):
    """Tarama durumunu kaydeder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_page(url: str) -> BeautifulSoup | None:
    """Sayfayı indirir ve BeautifulSoup nesnesi döner."""
    try:
        logger.info(f"Sayfa indiriliyor: {url}")
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        time.sleep(CRAWL_DELAY)
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.error(f"Sayfa indirilemedi: {url} -> {e}")
        return None


def extract_text_from_html(soup: BeautifulSoup) -> str:
    """HTML'den temiz metin çıkarır."""
    # Script ve style etiketlerini kaldır
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Fazla boş satırları temizle
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def detect_doc_type(title: str) -> DocumentType:
    """Başlıktan doküman türünü tespit eder."""
    title_lower = title.lower()
    for keyword, doc_type in DOC_TYPE_MAP.items():
        if keyword in title_lower:
            return doc_type
    return DocumentType.OTHER


def get_links_from_category_page(category_url: str) -> list[dict]:
    """Kategori sayfasındaki tüm doküman linklerini toplar."""
    full_url = urljoin(BDDK_BASE, category_url)
    soup = fetch_page(full_url)
    if not soup:
        return []

    links = []
    seen_urls = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        text = a_tag.get_text(strip=True)

        if not text or len(text) < 5:
            continue

        # BDDK iç linkleri
        if href.startswith("/Mevzuat/Detay/") or href.startswith("/Mevzuat/DokumanGetir/"):
            full_link = urljoin(BDDK_BASE, href)
            if full_link not in seen_urls:
                seen_urls.add(full_link)
                links.append({
                    "title": text,
                    "url": full_link,
                    "source_type": "bddk_detail",
                })

        # mevzuat.gov.tr linkleri
        elif "mevzuat.gov.tr" in href or "mevzuat.com.tr" in href:
            if href not in seen_urls:
                seen_urls.add(href)
                links.append({
                    "title": text,
                    "url": href,
                    "source_type": "mevzuat_gov",
                })

    return links


def crawl_mevzuat_gov_page(url: str) -> str:
    """mevzuat.gov.tr sayfasından mevzuat metnini çıkarır."""
    soup = fetch_page(url)
    if not soup:
        return ""

    # mevzuat.gov.tr genelde #divMevzuatNo veya .metin içinde tutar
    content_div = (
        soup.find("div", {"id": "divMevzuatDetay"})
        or soup.find("div", {"id": "mepiFrame"})
        or soup.find("div", {"class": "metin"})
        or soup.find("div", {"id": "icerik"})
        or soup.find("article")
        or soup.find("main")
    )

    if content_div:
        return extract_text_from_html(content_div)

    # Fallback: tüm sayfadan çıkar
    return extract_text_from_html(soup)


def crawl_bddk_detail_page(url: str) -> str:
    """BDDK detay sayfasından metin çıkarır."""
    soup = fetch_page(url)
    if not soup:
        return ""

    # PDF linki varsa atla (şimdilik sadece HTML)
    content_div = (
        soup.find("div", {"class": "mevzuat-detay"})
        or soup.find("div", {"class": "content"})
        or soup.find("article")
        or soup.find("main")
    )

    if content_div:
        # İçerideki alt linkleri de topla
        text = extract_text_from_html(content_div)
        return text

    return extract_text_from_html(soup)


def crawl_bddk_document_page(url: str) -> str:
    """BDDK DokumanGetir sayfasından doküman içeriğini çıkarır."""
    # Bu genelde PDF döner, HTML olarak deneyelim
    try:
        logger.info(f"Doküman indiriliyor: {url}")
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        time.sleep(CRAWL_DELAY)

        content_type = resp.headers.get("content-type", "")

        if "pdf" in content_type:
            # PDF'i kaydet ve PyMuPDF ile oku
            pdf_path = os.path.join(DATA_DIR, f"temp_{hashlib.md5(url.encode()).hexdigest()}.pdf")
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(pdf_path, "wb") as f:
                f.write(resp.content)

            import fitz
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text() + "\n"
            doc.close()
            os.remove(pdf_path)
            return text.strip()
        else:
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            return extract_text_from_html(soup)

    except Exception as e:
        logger.error(f"Doküman indirilemedi: {url} -> {e}")
        return ""


def process_and_index(title: str, text: str, category: str, url: str, state: dict) -> bool:
    """Metni chunk'lar ve vektör veritabanına indeksler."""
    if not text or len(text) < 100:
        logger.warning(f"Metin çok kısa, atlanıyor: {title}")
        return False

    doc_type = detect_doc_type(title)
    metadata = prepare_document_metadata(
        filename=f"{hashlib.md5(url.encode()).hexdigest()}.html",
        source=DocumentSource.BDDK,
        doc_type=doc_type,
        title=title,
        date=datetime.now(),
    )

    chunks = chunk_text(text)
    if not chunks:
        logger.warning(f"Chunk oluşturulamadı: {title}")
        return False

    try:
        count = index_document(metadata, chunks)
        logger.info(f"İndekslendi: {title} ({count} chunk)")

        state["indexed_docs"].append({
            "title": title,
            "url": url,
            "category": category,
            "chunk_count": count,
            "text_length": len(text),
            "doc_id": metadata["id"],
            "timestamp": datetime.now().isoformat(),
        })
        return True
    except Exception as e:
        logger.error(f"İndeksleme hatası: {title} -> {e}")
        state["errors"].append({
            "title": title,
            "url": url,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        })
        return False


def save_text_file(title: str, text: str, category: str):
    """Metni dosya olarak da kaydeder (yedek)."""
    # Dosya adı için güvenli karakterler: Türkçe harfler dahil, sadece dosya sistemi karakterlerini temizle
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)[:100].strip(". ")
    safe_category = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", category)[:50].strip(". ")
    # Boş kalırsa hash kullan
    if not safe_title:
        safe_title = hashlib.md5(title.encode()).hexdigest()[:16]
    if not safe_category:
        safe_category = "genel"
    dir_path = os.path.join(DATA_DIR, "texts", safe_category)
    os.makedirs(dir_path, exist_ok=True)

    file_path = os.path.join(dir_path, f"{safe_title}.txt")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"Başlık: {title}\nKategori: {category}\n\n{text}")
    except OSError as e:
        # Dosya adı hâlâ sorunluysa hash'li isimle kaydet
        fallback = os.path.join(dir_path, f"{hashlib.md5(title.encode()).hexdigest()}.txt")
        with open(fallback, "w", encoding="utf-8") as f:
            f.write(f"Başlık: {title}\nKategori: {category}\n\n{text}")
        logger.warning(f"Dosya adı sorunu, fallback kullanıldı: {e}")


def crawl_all():
    """Tüm BDDK mevzuat sayfalarını tarar."""
    state = load_state()
    crawled_set = set(state["crawled_urls"])

    ensure_collection()

    total_indexed = 0
    total_errors = 0
    total_skipped = 0

    logger.info("=" * 60)
    logger.info("BDDK Mevzuat Crawler başlatılıyor...")
    logger.info(f"Taranacak kategori sayısı: {len(CATEGORY_PAGES)}")
    logger.info("=" * 60)

    for category_name, category_path in CATEGORY_PAGES.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"Kategori: {category_name}")
        logger.info(f"{'='*60}")

        # Kategori sayfasındaki linkleri topla
        links = get_links_from_category_page(category_path)
        logger.info(f"Bulunan link sayısı: {len(links)}")

        for i, link in enumerate(links):
            url = link["url"]
            title = link["title"]

            if url in crawled_set:
                logger.info(f"  [{i+1}/{len(links)}] Zaten taranmış: {title[:60]}")
                total_skipped += 1
                continue

            logger.info(f"  [{i+1}/{len(links)}] İşleniyor: {title[:60]}")

            # Metin çıkar
            text = ""
            if link["source_type"] == "mevzuat_gov":
                text = crawl_mevzuat_gov_page(url)
            elif link["source_type"] == "bddk_detail":
                if "/DokumanGetir/" in url:
                    text = crawl_bddk_document_page(url)
                else:
                    text = crawl_bddk_detail_page(url)

            if text:
                # Dosyaya kaydet (yedek)
                save_text_file(title, text, category_name)

                # İndeksle
                success = process_and_index(title, text, category_name, url, state)
                if success:
                    total_indexed += 1
                else:
                    total_errors += 1
            else:
                logger.warning(f"  Metin çıkarılamadı: {title}")
                state["errors"].append({
                    "title": title,
                    "url": url,
                    "error": "Metin çıkarılamadı",
                    "timestamp": datetime.now().isoformat(),
                })
                total_errors += 1

            # URL'yi işaretle
            crawled_set.add(url)
            state["crawled_urls"] = list(crawled_set)

            # Her 10 dokümanda durumu kaydet
            if (i + 1) % 10 == 0:
                save_state(state)
                logger.info(f"  Durum kaydedildi. İndekslenen: {total_indexed}, Hata: {total_errors}")

        # Kategori sonunda kaydet
        save_state(state)

    # Final rapor
    logger.info("\n" + "=" * 60)
    logger.info("TARAMA TAMAMLANDI")
    logger.info(f"Toplam indekslenen: {total_indexed}")
    logger.info(f"Toplam hata: {total_errors}")
    logger.info(f"Atlanan (zaten taranmış): {total_skipped}")
    logger.info("=" * 60)

    save_state(state)
    return state


if __name__ == "__main__":
    crawl_all()
