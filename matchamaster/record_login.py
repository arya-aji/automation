# record_login.py
import os
import asyncio
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()
BASE_URL = os.getenv("BASE_URL", "https://matchapro.web.bps.go.id").rstrip("/")
STORAGE_STATE = os.getenv("STORAGE_STATE", "storage_state.json")
HEADLESS = os.getenv("HEADLESS_RECORD", "false").lower() == "true"
LOGIN_USERNAME = os.getenv("LOGIN_USERNAME", "")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "")

SEL = {
    # indikator app sudah login
    "main_menu": "#main-menu-navigation",
    "direktori_link": "a[href='https://matchapro.web.bps.go.id/direktori-usaha'], a[href='/direktori-usaha']",
    "filter_btn": "#filter-data",
    # SSO form
    "sso_user": "#username",
    "sso_pass": "#password",
    "sso_submit": "#kc-login",
}

async def goto_safely(page, url: str, timeout: int = 120000):
    await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    await page.wait_for_timeout(300)

async def click_sso_button(page):
    """
    Cari dan klik tombol 'Sign in with SSO BPS' dengan beberapa strategi:
    1) get_by_role('link', name=...)
    2) a:has-text('Sign in with SSO BPS')
    3) a[href*='sso.bps.go.id'] yang juga memuat kata 'SSO'
    4) XPath contains()
    5) Fallback: cari anchor yang innerText mengandung 'Sign in with SSO BPS'
    """
    strategies = [
        lambda: page.get_by_role("link", name="Sign in with SSO BPS"),
        lambda: page.locator("a:has-text('Sign in with SSO BPS')"),
        lambda: page.locator("a[href*='sso.bps.go.id']:has-text('SSO')"),
        lambda: page.locator("//a[contains(., 'Sign in with SSO BPS')]"),
    ]

    # Coba strategi satu per satu
    for i, strat in enumerate(strategies, start=1):
        loc = strat()
        try:
            await loc.first.scroll_into_view_if_needed()
            await loc.first.wait_for(state="visible", timeout=2000)
            await loc.first.click()
            print(f"✅ Klik tombol SSO via strategi #{i}")
            return
        except Exception:
            pass

    # Fallback terakhir: evaluasi manual seluruh anchor dan klik yang cocok
    anchors = page.locator("a")
    count = await anchors.count()
    print(f"ℹ️  Fallback: memeriksa {count} <a>…")
    for idx in range(count):
        a = anchors.nth(idx)
        try:
            text = (await a.inner_text()).strip()
            href = (await a.get_attribute("href")) or ""
            if "sign in with sso bps" in text.lower() or ("sso.bps.go.id" in href and "sso" in text.lower()):
                await a.scroll_into_view_if_needed()
                await a.click()
                print(f"✅ Klik tombol SSO via fallback (idx={idx}, text='{text[:40]}', href contains sso.bps.go.id={ 'sso.bps.go.id' in href })")
                return
        except Exception:
            continue

    raise RuntimeError("Tombol 'Sign in with SSO BPS' tidak ditemukan dengan semua strategi.")

async def ensure_logged_in_and_save(context, page):
    print(">>> Membuka BASE_URL…")
    await goto_safely(page, BASE_URL)

    # Sudah login?
    try:
        await page.wait_for_selector(SEL["main_menu"], timeout=4000)
        print("✅ Sudah login (main menu terlihat).")
    except PWTimeout:
        # Belum login → klik tombol SSO
        print("ℹ️  Belum login, mencari tombol 'Sign in with SSO BPS'…")
        await click_sso_button(page)

        # Tunggu domain SSO
        try:
            await page.wait_for_url(lambda u: "sso.bps.go.id" in u, timeout=30000)
        except PWTimeout:
            pass  # kadang langsung render form tanpa ganti URL dulu

        # Isi form SSO
        print(">>> Mengisi form SSO…")
        await page.wait_for_selector(SEL["sso_user"], timeout=60000)
        await page.fill(SEL["sso_user"], LOGIN_USERNAME)
        await page.fill(SEL["sso_pass"], LOGIN_PASSWORD)
        await page.click(SEL["sso_submit"])

        # Tunggu kembali ke app
        try:
            await page.wait_for_url(lambda u: "matchapro.web.bps.go.id" in u, timeout=60000)
        except PWTimeout:
            pass
        await page.wait_for_selector(SEL["main_menu"], timeout=60000)
        print("✅ Login SSO berhasil.")

    # Buka Direktori untuk validasi sesi
    print(">>> Membuka halaman Direktori Usaha untuk validasi sesi…")
    try:
        if await page.locator(SEL["direktori_link"]).count() > 0:
            await page.locator(SEL["direktori_link"]).first.click()
        else:
            await goto_safely(page, f"{BASE_URL}/direktori-usaha")
    except Exception:
        await goto_safely(page, f"{BASE_URL}/direktori-usaha")

    await page.wait_for_selector(SEL["filter_btn"], timeout=60000)
    print("✅ Halaman Direktori siap (#filter-data ditemukan).")

    await context.storage_state(path=STORAGE_STATE)
    print(f"💾 Storage state tersimpan: {STORAGE_STATE}")

async def main():
    if not LOGIN_USERNAME or not LOGIN_PASSWORD:
        raise RuntimeError("LOGIN_USERNAME / LOGIN_PASSWORD belum diisi di .env")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        # stealth ringan
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['id-ID','id','en-US','en'] });
        """)

        page = await context.new_page()
        page.set_default_timeout(120000)
        page.set_default_navigation_timeout(120000)

        try:
            await ensure_logged_in_and_save(context, page)
        finally:
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
