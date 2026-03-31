"""
Open WebUI Türkçe locale ve RAG entegrasyon testi (Playwright).
"""

import asyncio
import sys
from playwright.async_api import async_playwright


async def main():
    print("=" * 60)
    print("[*] Open WebUI Playwright E2E Test")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="tr-TR")
        page = await context.new_page()

        # 1. Open WebUI'a git
        print("\n[1] Open WebUI sayfasi yukleniyor...")
        await page.goto("http://localhost:3080", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        title = await page.title()
        print(f"    Sayfa basligi: {title}")

        # 2. Sayfanin icerigi
        body_text = await page.inner_text("body")
        print(f"    Body text (ilk 500 karakter):")
        print(f"    {body_text[:500]}")

        # 3. Turkce icerik kontrolu
        turkish_keywords = ["Basla", "Yeni", "Sohbet", "Ayar", "Model", "Kayit", "Giris", "Hosgeldiniz", "Ara"]
        english_keywords = ["Get started", "Sign in", "Sign up", "New Chat", "Settings", "Welcome"]

        tr_found = []
        en_found = []
        for kw in turkish_keywords:
            if kw.lower() in body_text.lower():
                tr_found.append(kw)
        for kw in english_keywords:
            if kw.lower() in body_text.lower():
                en_found.append(kw)

        print(f"\n    Turkce kelimeler: {tr_found}")
        print(f"    Ingilizce kelimeler: {en_found}")

        # 4. Screenshot
        screenshot_path = "tests/openwebui_screenshot.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"\n    Screenshot: {screenshot_path}")

        # 5. Signup sayfasi mi, chat sayfasi mi?
        url = page.url
        print(f"    Mevcut URL: {url}")

        # 6. Eger auth sayfasiysa, kayit ol
        if "auth" in url.lower() or "sign" in body_text.lower() or "Get started" in body_text:
            print("\n[2] Auth sayfasi tespit edildi, kayit yapiliyor...")

            # Admin kullanici olustur
            name_input = page.locator('input[name="name"], input[placeholder*="Name"], input[aria-label*="name"]').first
            email_input = page.locator('input[name="email"], input[type="email"], input[placeholder*="email"]').first
            password_input = page.locator('input[name="password"], input[type="password"], input[placeholder*="password"]').first

            # Formu bul
            all_inputs = await page.locator("input").all()
            print(f"    Toplam input sayisi: {len(all_inputs)}")
            for i, inp in enumerate(all_inputs):
                inp_type = await inp.get_attribute("type") or "text"
                inp_name = await inp.get_attribute("name") or ""
                inp_placeholder = await inp.get_attribute("placeholder") or ""
                print(f"    Input {i}: type={inp_type}, name={inp_name}, placeholder={inp_placeholder}")

            # Butonlar
            all_buttons = await page.locator("button").all()
            print(f"    Toplam button sayisi: {len(all_buttons)}")
            for i, btn in enumerate(all_buttons):
                btn_text = (await btn.inner_text()).strip()
                print(f"    Button {i}: '{btn_text}'")

        # 7. Config API kontrolu
        print("\n[3] Config API kontrolu...")
        config_response = await page.evaluate("""
            async () => {
                const r = await fetch('/api/config');
                return await r.json();
            }
        """)
        print(f"    default_locale: {config_response.get('default_locale', 'N/A')}")
        print(f"    name: {config_response.get('name', 'N/A')}")

        # 8. localStorage kontrolu
        locale_value = await page.evaluate("localStorage.getItem('locale')")
        print(f"    localStorage.locale: {locale_value}")

        # 9. Supported locales
        print("\n[4] Desteklenen dil dosyalari aranacak...")
        supported = await page.evaluate("""
            async () => {
                try {
                    const r = await fetch('/api/v1/configs');
                    const d = await r.json();
                    return d;
                } catch(e) {
                    return {error: e.message};
                }
            }
        """)
        print(f"    Configs: {str(supported)[:300]}")

        await browser.close()

    print("\n" + "=" * 60)
    print("[*] Test tamamlandi")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
