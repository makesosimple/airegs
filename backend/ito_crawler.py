"""
İTO (İstanbul Ticaret Odası) Crawler
ito.org.tr sitesinden hizmetler, SSS, meslek komiteleri, kurumsal,
duyurular ve fuarlar içeriklerini tarar ve vektör veritabanına indeksler.

Desteklenen içerik türleri: HTML, DOCX, PDF, JPG/PNG (OCR).
"""

import os
import re
import json
import sys
import time
import hashlib
import logging
import tempfile
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Backend app imports
sys.path.insert(0, os.path.dirname(__file__))
from app.services.document_processor import chunk_text, prepare_document_metadata, extract_text
from app.services.vector_store import index_document, ensure_collection
from app.models.schemas import DocumentSource, DocumentType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ito_crawler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# --- Ayarlar ---
ITO_BASE = "https://www.ito.org.tr"
CRAWL_DELAY = 1.0
DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "ito")
STATE_FILE = os.path.join(DATA_DIR, "ito_crawl_state.json")

# Türkçe ay adları -> ay numarası
TR_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4,
    "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
    "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})


# ============================================================
# Yardımcı fonksiyonlar
# ============================================================

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"crawled_urls": [], "indexed_docs": [], "errors": [], "downloaded_files": []}


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_page(url: str) -> BeautifulSoup | None:
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


def download_file(url: str, suffix: str) -> str | None:
    """Dosyayı indirir, geçici dosya yolunu döner."""
    try:
        logger.info(f"Dosya indiriliyor: {url}")
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=DATA_DIR)
        tmp.write(resp.content)
        tmp.close()
        time.sleep(CRAWL_DELAY)
        return tmp.name
    except Exception as e:
        logger.error(f"Dosya indirilemedi: {url} -> {e}")
        return None


def extract_text_from_image(file_path: str) -> str:
    """Görsellerden OCR ile metin çıkarır."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang="tur+eng")
        return text.strip()
    except ImportError:
        logger.warning("pytesseract/Pillow yüklü değil, OCR atlanıyor")
        return ""
    except Exception as e:
        logger.warning(f"OCR hatası: {e}")
        return ""


def parse_turkish_date(date_str: str) -> datetime | None:
    """'06 Nisan 2026' formatını parse eder."""
    try:
        parts = date_str.strip().split()
        if len(parts) >= 3:
            day = int(parts[0])
            month = TR_MONTHS.get(parts[1].lower(), 0)
            year = int(parts[2])
            if month:
                return datetime(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def extract_page_content(soup: BeautifulSoup) -> str:
    """ITO sayfasından ana içeriği çıkarır."""
    # Ana içerik alanı
    content_div = soup.select_one("div.col-md-12.col-lg-9")
    if not content_div:
        content_div = soup.select_one("section.detail-section")
    if not content_div:
        return ""

    # Script/style temizle
    for tag in content_div(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Accordion içeriklerini de dahil et
    text_parts = []

    # Sayfa başlığı
    title_el = content_div.select_one("h2.sm.blue.searchTitle")
    if title_el:
        text_parts.append(title_el.get_text(strip=True))

    # Ana metin blokları
    for div in content_div.select("div.searchContent.custom-content"):
        text = div.get_text(separator="\n", strip=True)
        if text:
            text_parts.append(text)

    # Accordion öğeleri (soru-cevap veya genişleyen bölümler)
    for item in content_div.select("div.accordion-section-item"):
        q_el = item.select_one("a.accordion-section-item-button")
        a_el = item.select_one("article div.searchContent")
        if q_el:
            q_text = q_el.get_text(strip=True)
            text_parts.append(f"\n### {q_text}")
        if a_el:
            a_text = a_el.get_text(separator="\n", strip=True)
            if a_text:
                text_parts.append(a_text)

    # Legislation plugin linkleri
    for link in content_div.select("a.announcements-box.download"):
        h4 = link.select_one("h4")
        if h4:
            text_parts.append(f"Mevzuat: {h4.get_text(strip=True)}")

    return "\n\n".join(text_parts)


def find_file_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Sayfadaki dosya linklerini bulur (PDF, DOCX, DOC, JPG, PNG)."""
    files = []
    seen = set()
    extensions = (".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png")

    content_div = soup.select_one("div.col-md-12.col-lg-9") or soup

    for a_tag in content_div.find_all("a", href=True):
        href = a_tag["href"].strip()
        href_lower = href.lower()

        if not any(href_lower.endswith(ext) for ext in extensions):
            continue

        full_url = urljoin(base_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)

        link_text = a_tag.get_text(strip=True) or os.path.basename(urlparse(href).path)
        ext = os.path.splitext(urlparse(href).path)[1].lower()

        files.append({
            "url": full_url,
            "title": link_text,
            "extension": ext,
        })

    # background-image'lardaki görselleri de bul
    for el in content_div.find_all(style=True):
        style = el["style"]
        match = re.search(r"url\(['\"]?([^'\")\s]+)['\"]?\)", style)
        if match:
            img_url = match.group(1)
            if any(img_url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                full_url = urljoin(base_url, img_url)
                if full_url not in seen:
                    seen.add(full_url)
                    files.append({
                        "url": full_url,
                        "title": os.path.basename(urlparse(img_url).path),
                        "extension": os.path.splitext(img_url)[1].lower(),
                    })

    return files


def find_external_legislation_links(soup: BeautifulSoup) -> list[dict]:
    """mevzuat.gov.tr gibi dış mevzuat linklerini bulur."""
    links = []
    seen = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if "mevzuat.gov.tr" in href and href not in seen:
            seen.add(href)
            links.append({
                "url": href,
                "title": a_tag.get_text(strip=True) or href,
            })
    return links


def crawl_mevzuat_gov(url: str) -> str:
    """mevzuat.gov.tr sayfasından metin çıkarır."""
    soup = fetch_page(url)
    if not soup:
        return ""

    content_div = (
        soup.find("div", {"id": "divMevzuatDetay"})
        or soup.find("div", {"id": "mepiFrame"})
        or soup.find("div", {"class": "metin"})
        or soup.find("div", {"id": "icerik"})
        or soup.find("article")
        or soup.find("main")
    )

    if content_div:
        for tag in content_div(["script", "style"]):
            tag.decompose()
        return content_div.get_text(separator="\n", strip=True)

    return soup.get_text(separator="\n", strip=True)


def process_file(file_info: dict, page_title: str, state: dict) -> bool:
    """Dosyayı indirir, metin çıkarır ve indeksler."""
    url = file_info["url"]
    ext = file_info["extension"]

    if url in state.get("downloaded_files", []):
        return False

    suffix = ext if ext.startswith(".") else f".{ext}"
    file_path = download_file(url, suffix)
    if not file_path:
        return False

    try:
        text = ""
        if ext in (".pdf",):
            text = extract_text(file_path, "application/pdf")
        elif ext in (".docx",):
            text = extract_text(file_path, "application/word")
        elif ext in (".doc",):
            # .doc eski format — python-docx desteklemiyor, metin olarak deneyelim
            try:
                text = extract_text(file_path, "application/word")
            except Exception:
                logger.warning(f".doc dosyası okunamadı: {url}")
                text = ""
        elif ext in (".jpg", ".jpeg", ".png"):
            text = extract_text_from_image(file_path)

        if text and len(text.strip()) > 20:
            doc_title = f"{page_title} - {file_info['title']}"
            _index_text(doc_title, text, DocumentType.HIZMET, url, state)
            state.setdefault("downloaded_files", []).append(url)
            return True
        else:
            logger.warning(f"Dosyadan yeterli metin çıkmadı: {url}")
    finally:
        try:
            os.unlink(file_path)
        except OSError:
            pass

    return False


def _index_text(title: str, text: str, doc_type: DocumentType, url: str, state: dict) -> bool:
    """Metni chunk'layıp Qdrant'a yazar."""
    if not text or len(text.strip()) < 50:
        return False

    metadata = prepare_document_metadata(
        filename=hashlib.md5(url.encode()).hexdigest() + ".html",
        source=DocumentSource.ITO,
        doc_type=doc_type,
        title=title,
    )

    chunks = chunk_text(text)
    if not chunks:
        return False

    try:
        count = index_document(metadata, chunks)
        logger.info(f"İndekslendi: {title[:80]} ({count} chunk)")
        state["indexed_docs"].append({
            "title": title,
            "url": url,
            "chunk_count": count,
            "doc_id": metadata["id"],
            "timestamp": datetime.now().isoformat(),
        })
        return True
    except Exception as e:
        logger.error(f"İndeksleme hatası: {title[:80]} -> {e}")
        state["errors"].append({
            "title": title,
            "url": url,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        })
        return False


# ============================================================
# Crawl modülleri
# ============================================================

def discover_hizmetler_urls(soup: BeautifulSoup) -> list[str]:
    """Hizmetler ana sayfasından tüm alt sayfa URL'lerini bulur."""
    urls = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if "/tr/hizmetler/" in href and href != "/tr/hizmetler/":
            full = urljoin(ITO_BASE, href)
            urls.add(full)
    return sorted(urls)


def crawl_hizmetler(state: dict) -> int:
    """Hizmetler bölümünü tarar — tüm alt sayfalar + dosyalar."""
    logger.info("=" * 60)
    logger.info("HIZMETLER bölümü taranıyor...")
    logger.info("=" * 60)

    crawled_set = set(state["crawled_urls"])
    indexed = 0

    # Ana sayfa
    main_soup = fetch_page(f"{ITO_BASE}/tr/hizmetler")
    if not main_soup:
        return 0

    # Tüm alt sayfa URL'lerini topla
    urls = discover_hizmetler_urls(main_soup)
    logger.info(f"Hizmetler altında {len(urls)} sayfa bulundu")

    # Her sayfayı recursive olarak tara — sidebar'dan da yeni URL'ler bul
    queue = list(urls)
    visited = set()

    while queue:
        url = queue.pop(0)
        if url in visited or url in crawled_set:
            continue
        visited.add(url)

        soup = fetch_page(url)
        if not soup:
            continue

        # Sidebar'dan yeni URL'ler
        sidebar = soup.select_one("aside.accordion-sidebar")
        if sidebar:
            for a_tag in sidebar.find_all("a", href=True):
                href = a_tag["href"].strip()
                if "/tr/hizmetler/" in href:
                    new_url = urljoin(ITO_BASE, href)
                    if new_url not in visited:
                        queue.append(new_url)

        # Sayfa içeriği
        page_title = ""
        title_el = soup.select_one("h2.sm.blue.searchTitle")
        if title_el:
            page_title = title_el.get_text(strip=True)
        if not page_title:
            og = soup.find("meta", property="og:title")
            page_title = og["content"] if og else urlparse(url).path.split("/")[-1]

        content = extract_page_content(soup)
        if content and len(content.strip()) > 50:
            if _index_text(page_title, content, DocumentType.HIZMET, url, state):
                indexed += 1

        # Dosya linkleri (PDF, DOCX, JPG vb.)
        file_links = find_file_links(soup, url)
        for fl in file_links:
            if process_file(fl, page_title, state):
                indexed += 1

        # Dış mevzuat linkleri
        ext_links = find_external_legislation_links(soup)
        for link in ext_links:
            if link["url"] not in crawled_set and link["url"] not in visited:
                logger.info(f"Dış mevzuat taranıyor: {link['title'][:60]}")
                text = crawl_mevzuat_gov(link["url"])
                if text and len(text) > 100:
                    if _index_text(f"Mevzuat: {link['title']}", text, DocumentType.YONETMELIK, link["url"], state):
                        indexed += 1
                crawled_set.add(link["url"])

        crawled_set.add(url)
        state["crawled_urls"] = list(crawled_set)

        if len(visited) % 10 == 0:
            save_state(state)

    save_state(state)
    logger.info(f"Hizmetler tamamlandı: {indexed} içerik indekslendi")
    return indexed


def crawl_sss(state: dict) -> int:
    """Sıkça Sorulan Sorular sayfasını tarar."""
    logger.info("=" * 60)
    logger.info("SSS bölümü taranıyor...")
    logger.info("=" * 60)

    url = f"{ITO_BASE}/tr/iletisim/sikca-sorulan-sorular"
    if url in state["crawled_urls"]:
        logger.info("SSS zaten taranmış, atlanıyor")
        return 0

    soup = fetch_page(url)
    if not soup:
        return 0

    indexed = 0
    items = soup.select("div.accordion-section-item")
    logger.info(f"SSS'de {len(items)} soru bulundu")

    # Her soruyu ayrı bir doküman olarak indeksle (daha iyi retrieval)
    for item in items:
        q_el = item.select_one("a.accordion-section-item-button")
        a_el = item.select_one("article div.searchContent")

        if not q_el or not a_el:
            continue

        question = q_el.get_text(strip=True)
        answer = a_el.get_text(separator="\n", strip=True)

        if not question or not answer:
            continue

        text = f"Soru: {question}\n\nCevap: {answer}"
        q_hash = hashlib.md5(question.encode()).hexdigest()[:8]
        doc_url = f"{url}#sss-{q_hash}"

        if _index_text(f"SSS: {question}", text, DocumentType.SSS, doc_url, state):
            indexed += 1

    state["crawled_urls"].append(url)
    save_state(state)
    logger.info(f"SSS tamamlandı: {indexed} soru indekslendi")
    return indexed


def crawl_meslek_komiteleri(state: dict) -> int:
    """81 meslek komitesini tarar."""
    logger.info("=" * 60)
    logger.info("MESLEK KOMİTELERİ taranıyor...")
    logger.info("=" * 60)

    crawled_set = set(state["crawled_urls"])
    indexed = 0

    # Ana sayfa — komite listesi
    soup = fetch_page(f"{ITO_BASE}/tr/meslek-komiteleri")
    if not soup:
        return 0

    # Komite linkleri
    komite_links = []
    for a_tag in soup.select("div.col-md-4 a[href*='/tr/meslek-komiteleri/']"):
        href = a_tag["href"].strip()
        full_url = urljoin(ITO_BASE, href)
        pure_box = a_tag.select_one("div.pure-box")
        if pure_box:
            num = pure_box.select_one("span")
            name = pure_box.select_one("strong")
            komite_links.append({
                "url": full_url,
                "number": num.get_text(strip=True) if num else "",
                "name": name.get_text(strip=True) if name else "",
            })

    logger.info(f"{len(komite_links)} meslek komitesi bulundu")

    for komite in komite_links:
        url = komite["url"]
        if url in crawled_set:
            continue

        soup = fetch_page(url)
        if not soup:
            continue

        title = f"{komite['number']}. Grup - {komite['name']} Meslek Komitesi"

        # Komite hakkında bilgi
        text_parts = [title]

        # Aktiviteler
        for activity in soup.select("a.komite-activity-section-list-item"):
            time_el = activity.select_one("time")
            p_el = activity.select_one("p")
            if time_el and p_el:
                text_parts.append(f"{time_el.get_text(strip=True)}: {p_el.get_text(strip=True)}")

        # Duyurular
        for ann in soup.select("a.announcements-box"):
            time_el = ann.select_one("time")
            h4 = ann.select_one("h4")
            p_el = ann.select_one("p")
            parts = []
            if time_el:
                parts.append(time_el.get_text(strip=True))
            if h4:
                parts.append(h4.get_text(strip=True))
            if p_el:
                parts.append(p_el.get_text(strip=True))
            if parts:
                text_parts.append(" - ".join(parts))

        content = "\n\n".join(text_parts)
        if len(content) > 50:
            if _index_text(title, content, DocumentType.KURUMSAL, url, state):
                indexed += 1

        crawled_set.add(url)
        state["crawled_urls"] = list(crawled_set)

    save_state(state)
    logger.info(f"Meslek komiteleri tamamlandı: {indexed} komite indekslendi")
    return indexed


def crawl_kurumsal(state: dict) -> int:
    """Kurumsal/Hakkımızda bölümünü ve alt sayfalarını tarar."""
    logger.info("=" * 60)
    logger.info("KURUMSAL bölümü taranıyor...")
    logger.info("=" * 60)

    crawled_set = set(state["crawled_urls"])
    indexed = 0

    # Hakkımızda sayfasından sidebar URL'lerini bul
    soup = fetch_page(f"{ITO_BASE}/tr/kurumsal/hakkimizda")
    if not soup:
        return 0

    # Sidebar'dan tüm kurumsal linkleri topla
    urls = set()
    sidebar = soup.select_one("aside.accordion-sidebar")
    if sidebar:
        for a_tag in sidebar.find_all("a", href=True):
            href = a_tag["href"].strip()
            if "/tr/kurumsal/" in href:
                urls.add(urljoin(ITO_BASE, href))

    # Hakkımızda'nın kendisini de ekle
    urls.add(f"{ITO_BASE}/tr/kurumsal/hakkimizda")

    logger.info(f"Kurumsal altında {len(urls)} sayfa bulundu")

    for url in sorted(urls):
        if url in crawled_set:
            continue

        # Dış siteler (gazete vb.) atla
        if urlparse(url).netloc and "ito.org.tr" not in urlparse(url).netloc:
            continue

        soup = fetch_page(url)
        if not soup:
            continue

        page_title = ""
        title_el = soup.select_one("h2.sm.blue.searchTitle")
        if title_el:
            page_title = title_el.get_text(strip=True)
        if not page_title:
            og = soup.find("meta", property="og:title")
            page_title = og["content"] if og else url.split("/")[-1]

        content = extract_page_content(soup)
        if content and len(content.strip()) > 50:
            if _index_text(f"Kurumsal: {page_title}", content, DocumentType.KURUMSAL, url, state):
                indexed += 1

        # Dosya linkleri
        file_links = find_file_links(soup, url)
        for fl in file_links:
            if process_file(fl, page_title, state):
                indexed += 1

        # Dış mevzuat linkleri (oda-mevzuati sayfasında olacak)
        ext_links = find_external_legislation_links(soup)
        for link in ext_links:
            if link["url"] not in crawled_set:
                logger.info(f"Dış mevzuat: {link['title'][:60]}")
                text = crawl_mevzuat_gov(link["url"])
                if text and len(text) > 100:
                    if _index_text(f"Mevzuat: {link['title']}", text, DocumentType.YONETMELIK, link["url"], state):
                        indexed += 1
                crawled_set.add(link["url"])

        crawled_set.add(url)
        state["crawled_urls"] = list(crawled_set)

    save_state(state)
    logger.info(f"Kurumsal tamamlandı: {indexed} içerik indekslendi")
    return indexed


def crawl_duyurular(state: dict, min_year: int = 2026) -> int:
    """Duyuruları tarar — sadece min_year ve sonrası."""
    logger.info("=" * 60)
    logger.info(f"DUYURULAR taranıyor (>= {min_year})...")
    logger.info("=" * 60)

    crawled_set = set(state["crawled_urls"])
    indexed = 0
    page_num = 1
    stop = False

    while not stop:
        url = f"{ITO_BASE}/tr/duyurular" if page_num == 1 else f"{ITO_BASE}/tr/duyurular?page={page_num}"

        if url in crawled_set:
            page_num += 1
            if page_num > 50:  # güvenlik sınırı
                break
            continue

        soup = fetch_page(url)
        if not soup:
            break

        items = soup.select("a.announcements-box")
        if not items:
            break

        old_count = 0
        for item in items:
            time_el = item.select_one("time")
            h4 = item.select_one("h4")
            p_el = item.select_one("p")

            if not time_el or not h4:
                continue

            date_str = time_el.get_text(strip=True)
            date = parse_turkish_date(date_str)

            if date and date.year < min_year:
                old_count += 1
                continue

            title = h4.get_text(strip=True)
            desc = p_el.get_text(strip=True) if p_el else ""
            href = item.get("href", "")
            detail_url = urljoin(ITO_BASE, href) if href else ""

            # Detay sayfasını çek
            detail_text = ""
            if detail_url and detail_url not in crawled_set:
                detail_soup = fetch_page(detail_url)
                if detail_soup:
                    detail_text = extract_page_content(detail_soup)

                    # Detaydaki dosyalar
                    file_links = find_file_links(detail_soup, detail_url)
                    for fl in file_links:
                        process_file(fl, title, state)

            text = f"Duyuru: {title}\nTarih: {date_str}\n\n{desc}"
            if detail_text:
                text += f"\n\n{detail_text}"

            if len(text) > 50:
                source_url = detail_url or url
                if _index_text(f"Duyuru: {title}", text, DocumentType.DUYURU, source_url, state):
                    indexed += 1
                crawled_set.add(source_url)

        # Tüm öğeler eski ise dur
        if old_count == len(items):
            logger.info(f"Sayfa {page_num}: tüm duyurular {min_year} öncesi, durduruluyor")
            stop = True

        crawled_set.add(url)
        state["crawled_urls"] = list(crawled_set)
        save_state(state)
        page_num += 1

    logger.info(f"Duyurular tamamlandı: {indexed} duyuru indekslendi")
    return indexed


def crawl_fuarlar(state: dict, min_year: int = 2026) -> int:
    """Fuarları tarar — sadece min_year ve sonrası."""
    logger.info("=" * 60)
    logger.info(f"FUARLAR taranıyor (>= {min_year})...")
    logger.info("=" * 60)

    crawled_set = set(state["crawled_urls"])
    indexed = 0

    # Yıl filtresi URL'de var
    page_num = 1
    while True:
        url = f"{ITO_BASE}/tr/fuarlar?year={min_year}"
        if page_num > 1:
            url += f"&page={page_num}"

        if url in crawled_set:
            page_num += 1
            if page_num > 20:
                break
            continue

        soup = fetch_page(url)
        if not soup:
            break

        items = soup.select("a.list-box")
        if not items:
            break

        for item in items:
            time_el = item.select_one("time")
            h4 = item.select_one("h4")
            p_el = item.select_one("p")
            href = item.get("href", "")

            title = h4.get_text(strip=True) if h4 else ""
            date_str = time_el.get_text(strip=True) if time_el else ""
            desc = p_el.get_text(strip=True) if p_el else ""
            detail_url = urljoin(ITO_BASE, href) if href else ""

            # Detay sayfasını çek
            detail_text = ""
            if detail_url and detail_url not in crawled_set:
                detail_soup = fetch_page(detail_url)
                if detail_soup:
                    detail_text = extract_page_content(detail_soup)

            text = f"Fuar: {title}\nTarih: {date_str}\n\n{desc}"
            if detail_text:
                text += f"\n\n{detail_text}"

            if len(text) > 50:
                source_url = detail_url or url
                if _index_text(f"Fuar: {title}", text, DocumentType.FUAR, source_url, state):
                    indexed += 1
                crawled_set.add(source_url)

        crawled_set.add(url)
        state["crawled_urls"] = list(crawled_set)
        save_state(state)

        # Sonraki sayfa var mı?
        pagination = soup.select("div.pagination a.pagination-list-item")
        max_page = max((int(a.get_text(strip=True)) for a in pagination if a.get_text(strip=True).isdigit()), default=1)
        if page_num >= max_page:
            break
        page_num += 1

    logger.info(f"Fuarlar tamamlandı: {indexed} fuar indekslendi")
    return indexed


# ============================================================
# TOBB Mevzuat
# ============================================================

TOBB_BASE = "https://www.tobb.org.tr"
TOBB_PAGES = [
    "/HukukMusavirligi/Sayfalar/Mevzuat.php",
    "/HukukMusavirligi/Sayfalar/Yonetmelikler.php",
    "/HukukMusavirligi/Sayfalar/PersonelYonetmelikleri.php",
    "/HukukMusavirligi/Sayfalar/DigerYonetmelikler.php",
    "/HukukMusavirligi/Sayfalar/Esaslar.php",
    "/HukukMusavirligi/Sayfalar/Genelgeler.php",
    "/HukukMusavirligi/Sayfalar/OdalarBorsalarveBirlikMevzuati.php",
    "/HukukMusavirligi/Sayfalar/5300Yonetmelikler.php",
    "/HukukMusavirligi/Sayfalar/UyulmasiZorunluMeslekiKaralar.php",
]

# SSL sorunu var, verify=False gerekli
tobb_session = requests.Session()
tobb_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})
tobb_session.verify = False

# SSL uyarılarını bastır
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def fetch_tobb_page(url: str) -> BeautifulSoup | None:
    try:
        logger.info(f"TOBB sayfa indiriliyor: {url}")
        resp = tobb_session.get(url, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        time.sleep(CRAWL_DELAY)
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.error(f"TOBB sayfa indirilemedi: {url} -> {e}")
        return None


def download_tobb_file(url: str, suffix: str) -> str | None:
    try:
        logger.info(f"TOBB dosya indiriliyor: {url}")
        resp = tobb_session.get(url, timeout=60)
        resp.raise_for_status()
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=DATA_DIR)
        tmp.write(resp.content)
        tmp.close()
        time.sleep(CRAWL_DELAY)
        return tmp.name
    except Exception as e:
        logger.error(f"TOBB dosya indirilemedi: {url} -> {e}")
        return None


def crawl_tobb(state: dict) -> int:
    """TOBB Hukuk Müşavirliği mevzuat sayfalarını tarar."""
    logger.info("=" * 60)
    logger.info("TOBB MEVZUAT taranıyor...")
    logger.info("=" * 60)

    crawled_set = set(state["crawled_urls"])
    indexed = 0

    for page_path in TOBB_PAGES:
        page_url = urljoin(TOBB_BASE, page_path)
        if page_url in crawled_set:
            continue

        soup = fetch_tobb_page(page_url)
        if not soup:
            continue

        # Sayfa başlığı
        page_title = page_path.split("/")[-1].replace(".php", "")

        # Sayfadaki tüm linkleri topla
        all_links = soup.find_all("a", href=True)

        for a_tag in all_links:
            href = a_tag["href"].strip()
            text = a_tag.get_text(strip=True)
            if not text or len(text) < 5:
                continue

            full_url = urljoin(page_url, href)

            if full_url in crawled_set:
                continue

            # mevzuat.gov.tr linkleri
            if "mevzuat.gov.tr" in href:
                logger.info(f"  TOBB mevzuat: {text[:60]}")
                mev_text = crawl_mevzuat_gov(full_url)
                if mev_text and len(mev_text) > 100:
                    if _index_text(f"TOBB Mevzuat: {text}", mev_text, DocumentType.YONETMELIK, full_url, state):
                        indexed += 1
                crawled_set.add(full_url)

            # PDF dosyaları
            elif href.lower().endswith(".pdf"):
                file_path = download_tobb_file(full_url, ".pdf")
                if file_path:
                    try:
                        pdf_text = extract_text(file_path, "application/pdf")
                        if pdf_text and len(pdf_text.strip()) > 50:
                            if _index_text(f"TOBB: {text}", pdf_text, DocumentType.YONETMELIK, full_url, state):
                                indexed += 1
                    finally:
                        try:
                            os.unlink(file_path)
                        except OSError:
                            pass
                crawled_set.add(full_url)

            # DOCX dosyaları
            elif href.lower().endswith(".docx"):
                file_path = download_tobb_file(full_url, ".docx")
                if file_path:
                    try:
                        doc_text = extract_text(file_path, "application/word")
                        if doc_text and len(doc_text.strip()) > 50:
                            if _index_text(f"TOBB: {text}", doc_text, DocumentType.YONETMELIK, full_url, state):
                                indexed += 1
                    finally:
                        try:
                            os.unlink(file_path)
                        except OSError:
                            pass
                crawled_set.add(full_url)

            # DOC dosyaları (eski format)
            elif href.lower().endswith(".doc"):
                file_path = download_tobb_file(full_url, ".doc")
                if file_path:
                    try:
                        doc_text = extract_text(file_path, "application/word")
                        if doc_text and len(doc_text.strip()) > 50:
                            if _index_text(f"TOBB: {text}", doc_text, DocumentType.YONETMELIK, full_url, state):
                                indexed += 1
                        else:
                            logger.warning(f"  .doc okunamadı: {text[:40]}")
                    except Exception:
                        logger.warning(f"  .doc parse hatası: {text[:40]}")
                    finally:
                        try:
                            os.unlink(file_path)
                        except OSError:
                            pass
                crawled_set.add(full_url)

            # XLS dosyaları — metin olarak kaydetmeye değmez, atla
            elif href.lower().endswith((".xls", ".xlsx")):
                logger.info(f"  Excel atlanıyor: {text[:40]}")
                crawled_set.add(full_url)

        # Sayfa metnini de indeksle (açıklama içeriği varsa)
        page_text_parts = []
        for el in soup.find_all(["p", "li", "td"]):
            t = el.get_text(strip=True)
            if t and len(t) > 20 and "mevzuat" not in t.lower()[:10]:
                page_text_parts.append(t)
        page_text = "\n".join(page_text_parts)
        if page_text and len(page_text) > 100:
            _index_text(f"TOBB {page_title}", page_text, DocumentType.KURUMSAL, page_url, state)

        crawled_set.add(page_url)
        state["crawled_urls"] = list(crawled_set)
        save_state(state)

    logger.info(f"TOBB tamamlandı: {indexed} mevzuat indekslendi")
    return indexed


# ============================================================
# Ana çalıştırıcı
# ============================================================

def crawl_all():
    """Tüm İTO içeriklerini tarar."""
    state = load_state()
    ensure_collection()

    logger.info("=" * 60)
    logger.info("İTO CRAWLER başlatılıyor...")
    logger.info("=" * 60)

    totals = {}

    totals["sss"] = crawl_sss(state)
    totals["hizmetler"] = crawl_hizmetler(state)
    totals["meslek_komiteleri"] = crawl_meslek_komiteleri(state)
    totals["kurumsal"] = crawl_kurumsal(state)
    totals["duyurular"] = crawl_duyurular(state, min_year=2026)
    totals["fuarlar"] = crawl_fuarlar(state, min_year=2026)
    totals["tobb"] = crawl_tobb(state)

    total = sum(totals.values())

    logger.info("\n" + "=" * 60)
    logger.info("İTO CRAWLER TAMAMLANDI")
    for section, count in totals.items():
        logger.info(f"  {section}: {count} içerik")
    logger.info(f"  TOPLAM: {total}")
    logger.info(f"  Hatalar: {len(state['errors'])}")
    logger.info("=" * 60)

    state["last_run"] = datetime.now().isoformat()
    save_state(state)
    return state


if __name__ == "__main__":
    crawl_all()
