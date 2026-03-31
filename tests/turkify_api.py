"""
Open WebUI Turkcelestirme - API uzerinden.
"""
import json, sys, httpx
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:3080"

def main():
    # 1. Login
    print("=== LOGIN ===")
    r = httpx.post(f"{BASE}/api/v1/auths/signin",
                   json={"email": "admin@airegs.local", "password": "AiRegs2026"},
                   headers={"Content-Type": "application/json; charset=utf-8"})
    token = r.json().get("token")
    if not token:
        print(f"Login basarisiz: {r.text}")
        return
    print(f"Token: {token[:20]}...")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    # 2. Kullanici locale
    print("\n=== LOCALE ===")
    r = httpx.get(f"{BASE}/api/v1/users/user/settings", headers=headers)
    settings = r.json() if r.status_code == 200 else {}
    if not isinstance(settings, dict):
        settings = {}
    settings.setdefault("ui", {})["i18n"] = "tr-TR"
    r = httpx.post(f"{BASE}/api/v1/users/user/settings/update", headers=headers, json=settings)
    print(f"Locale: {'OK' if r.status_code == 200 else r.text}")

    # 3. Site adi + oneriler + locale
    print("\n=== SITE CONFIG ===")
    config_payload = {
        "name": "AIRegs - Regülasyon Asistanı",
        "default_locale": "tr-TR",
        "default_prompt_suggestions": [
            {"title": ["Sermaye yeterliliği", "oranları hakkında bilgi ver"]},
            {"title": ["BDDK düzenlemeleri", "nelerdir, özetle"]},
            {"title": ["Risk yönetimi", "çerçevesini açıkla"]},
            {"title": ["Bankacılık mevzuatı", "son değişiklikler neler"]},
            {"title": ["Kredi sınırlamaları", "hakkında ne biliyorsun"]},
            {"title": ["İç denetim", "gereklilikleri nelerdir"]},
        ],
    }
    r = httpx.post(f"{BASE}/api/v1/configs/update", headers=headers, json=config_payload)
    if r.status_code == 200:
        d = r.json()
        print(f"Site adı: {d.get('name')}")
        print(f"Locale: {d.get('default_locale')}")
        print(f"Öneri sayısı: {len(d.get('default_prompt_suggestions', []))}")
        for s in d.get("default_prompt_suggestions", []):
            print(f"  - {' / '.join(s.get('title', []))}")
    else:
        print(f"Config hata: {r.status_code} - {r.text[:200]}")

    # 4. Model bilgisi
    print("\n=== MODEL ===")
    model_payload = {
        "id": "airegs-rag",
        "name": "AIRegs Regülasyon Asistanı",
        "meta": {
            "description": "Bankacılık regülasyonları için RAG tabanlı Türkçe soru-cevap asistanı. BDDK, SPK ve diğer düzenleyici kurum mevzuatlarını bilir.",
            "profile_image_url": "",
            "suggestion_prompts": [
                {"title": "Sermaye yeterliliği", "subtitle": "oranları hakkında bilgi ver"},
                {"title": "BDDK düzenlemeleri", "subtitle": "nelerdir, özetle"},
                {"title": "Risk yönetimi", "subtitle": "çerçevesini açıkla"},
                {"title": "Bankacılık mevzuatı", "subtitle": "son değişiklikler neler"},
            ],
        },
        "params": {},
        "base_model_id": "airegs-rag",
        "access_control": None,
    }
    r = httpx.post(f"{BASE}/api/v1/models/create", headers=headers, json=model_payload)
    if r.status_code == 200:
        print(f"Model oluşturuldu: {r.json().get('name')}")
    else:
        r = httpx.post(f"{BASE}/api/v1/models/update", headers=headers, json=model_payload)
        print(f"Model güncellendi: {'OK' if r.status_code == 200 else r.text[:200]}")

    # 5. Banner
    print("\n=== BANNER ===")
    banner_payload = {
        "banners": [
            {
                "id": "welcome-tr",
                "type": "info",
                "title": "",
                "content": "AIRegs Regülasyon Asistanına hoş geldiniz. Bankacılık mevzuatı hakkında sorularınızı sorabilirsiniz.",
                "dismissible": True,
                "timestamp": 1774950000,
            }
        ]
    }
    r = httpx.post(f"{BASE}/api/v1/configs/banners", headers=headers, json=banner_payload)
    print(f"Banner: {'OK' if r.status_code == 200 else r.text[:200]}")

    # 6. Dogrulama
    print("\n=== DOGRULAMA ===")
    r = httpx.get(f"{BASE}/api/config")
    config = r.json()
    print(f"Site adı: {config.get('name')}")
    print(f"Locale: {config.get('default_locale')}")
    print(f"Signup: {config.get('features', {}).get('enable_signup')}")
    for s in config.get("default_prompt_suggestions", []):
        print(f"  Öneri: {' / '.join(s.get('title', []))}")

    print("\nTÜRKÇELEŞTİRME TAMAMLANDI!")


if __name__ == "__main__":
    main()
