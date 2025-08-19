# record_login.py
import asyncio, os
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
BASE_URL = os.getenv("BASE_URL")
STORAGE_STATE = os.getenv("STORAGE_STATE", "storage_state.json")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()

        print(">>> Buka halaman login. Silakan login secara manual...")
        await page.goto(BASE_URL, timeout=120000)

        # TUNGGU kamu login sampai terlihat elemen yang hanya muncul setelah login:
        # Ganti selector di bawah dengan yang pasti ada di beranda setelah login
        await page.wait_for_selector('#filter-data', timeout=120000)

        await context.storage_state(path=STORAGE_STATE)
        print(f"✅ Storage state tersimpan ke {STORAGE_STATE}")
        await browser.close()

asyncio.run(main())
