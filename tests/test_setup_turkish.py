"""
Open WebUI Turkce locale ve oneri kartlarini ayarlar, ardindan dogrular.
"""

import asyncio
from playwright.async_api import async_playwright


async def main():
    print("=" * 60)
    print("[*] Open WebUI Turkce Ayarlama ve Dogrulama")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="tr-TR")
        page = await context.new_page()

        # 1. Sayfayi yukle
        print("\n[1] Open WebUI yukleniyor...")
        await page.goto("http://localhost:3080", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # 2. localStorage.locale set et
        print("[2] localStorage.locale = 'tr-TR' ayarlaniyor...")
        await page.evaluate("localStorage.setItem('locale', 'tr-TR')")

        # 3. i18n cevirisini yukle
        print("[3] Sayfa yeniden yukleniyor...")
        await page.reload(wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # 4. Icerigi kontrol et
        body_text = await page.inner_text("body")
        print(f"\n[4] Body text (ilk 500):")
        print(f"    {body_text[:500]}")

        # 5. Turkce vs Ingilizce analizi
        turkish_words = [
            "Bugün", "size", "nasıl", "yardımcı", "olabilirim",
            "Önerilen", "Yeni Sohbet", "Ayarlar", "Ara",
            "Varsayılan"
        ]
        english_words = [
            "How can I help", "Suggested", "New Chat", "Settings",
            "Set as default", "today"
        ]

        tr_found = [w for w in turkish_words if w.lower() in body_text.lower()]
        en_found = [w for w in english_words if w.lower() in body_text.lower()]

        print(f"\n    Turkce bulunan: {tr_found}")
        print(f"    Ingilizce bulunan: {en_found}")

        locale_val = await page.evaluate("localStorage.getItem('locale')")
        print(f"    localStorage.locale: {locale_val}")

        # 6. Admin ayarlarindan locale kontrol
        print("\n[5] Admin settings panelini aciyorum...")
        # Sol alttaki kullanici menusune tikla
        user_menu = page.locator("button[aria-label*='User'], button[aria-label*='Kullanıcı'], [data-testid='user-menu']").first
        try:
            await user_menu.click(timeout=3000)
        except:
            # Alternatif: avatar/profil butonuna tikla
            avatar_buttons = await page.locator("button img[class*='rounded']").all()
            if avatar_buttons:
                await avatar_buttons[-1].click()

        await page.wait_for_timeout(1000)

        # Settings/Ayarlar linkine tikla
        settings_link = page.get_by_text("Ayarlar").or_(page.get_by_text("Settings"))
        try:
            await settings_link.first.click(timeout=3000)
            await page.wait_for_timeout(2000)

            # Genel/General sekmesine git
            general_tab = page.get_by_text("Genel").or_(page.get_by_text("General"))
            await general_tab.first.click(timeout=3000)
            await page.wait_for_timeout(1000)

            settings_body = await page.inner_text("body")
            print(f"    Settings sayfasi icerik (ilk 300):")
            print(f"    {settings_body[:300]}")
        except Exception as e:
            print(f"    Settings acilamadi: {e}")

        # 7. Screenshot
        await page.screenshot(path="tests/openwebui_turkish.png", full_page=True)
        print("\n[6] Screenshot: tests/openwebui_turkish.png")

        # 8. Admin panelinden dili kontrol et
        print("\n[7] Admin API uzerinden ayar guncelleniyor...")
        result = await page.evaluate("""
            async () => {
                const token = localStorage.getItem('token');
                if (!token) return {error: 'no token'};

                // Mevcut kullanici ayarlarini al
                const settingsResp = await fetch('/api/v1/users/user/settings', {
                    headers: {'Authorization': 'Bearer ' + token}
                });
                let settings = {};
                if (settingsResp.ok) {
                    settings = await settingsResp.json();
                }

                // Locale'i tr-TR olarak kaydet
                settings.ui = settings.ui || {};
                settings.ui.i18n = 'tr-TR';

                const updateResp = await fetch('/api/v1/users/user/settings/update', {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(settings)
                });

                if (updateResp.ok) {
                    return await updateResp.json();
                }
                return {error: updateResp.status, text: await updateResp.text()};
            }
        """)
        print(f"    Sonuc: {str(result)[:300]}")

        # 9. Tekrar yukle ve kontrol et
        print("\n[8] Son dogrulama...")
        await page.reload(wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        final_body = await page.inner_text("body")
        tr_final = [w for w in turkish_words if w.lower() in final_body.lower()]
        en_final = [w for w in english_words if w.lower() in final_body.lower()]

        print(f"    Turkce: {tr_final}")
        print(f"    Ingilizce: {en_final}")

        await page.screenshot(path="tests/openwebui_turkish_final.png", full_page=True)
        print(f"    Final screenshot: tests/openwebui_turkish_final.png")

        if len(tr_final) > len(en_final):
            print("\n    [OK] Arayuz buyuk olcude Turkce!")
        else:
            print("\n    [!!] Arayuz hala Ingilizce agirlikli")

        await browser.close()

    print("\n" + "=" * 60)
    print("[*] Tamamlandi")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
