# worker_cancel.py
# ------------------------------------------------------------
# ENV (.env):
#   BASE_URL_CANCEL=https://matchapro.web.bps.go.id/profiling/mandiri
#   STORAGE_STATE=storage_state.json
#   WORKER_NAME=pc-jakpus-01
#   HEADLESS_CANCEL=false
#   TIMEOUT_MS=120000
#   LOG_LEVEL=INFO
#   CANCEL_SELECTOR=           # optional override if site changes
#   STATUS_FILTER=OPEN         # OPEN/DRAFT/SUBMITTED/...
# ------------------------------------------------------------

import os
import argparse
import asyncio
from dotenv import load_dotenv
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()

BASE_URL = os.getenv("BASE_URL_CANCEL", "https://matchapro.web.bps.go.id/profiling/mandiri")
STORAGE_STATE = os.getenv("STORAGE_STATE", "storage_state.json")
WORKER_NAME = os.getenv("WORKER_NAME", "worker-cancel")
HEADLESS = os.getenv("HEADLESS_CANCEL", "false").lower() == "true"
TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "120000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CANCEL_SELECTOR_ENV = os.getenv("CANCEL_SELECTOR", "").strip()
STATUS_FILTER = os.getenv("STATUS_FILTER", "OPEN").strip().upper()

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level=LOG_LEVEL,
)

SEL = {
    "select_status": "#select2-status_form_mandiri",            # real hidden select (Select2)
    "reload_btn": "#reload-mandiri",                            # reload button in toolbar
    "datatable": "#data_profiling_mandiri",                     # main table
    "dt_processing": "#data_profiling_mandiri_processing",      # DataTables spinner
    "next_page": "#data_profiling_mandiri_next",                # <li id="..._next">
    "block_ui": ".blockUI",                                     # site-wide overlay (if used)
    "confirm_button": ".swal2-confirm",
    "success_popup": ".swal2-icon-success",
    "ok_button": ".swal2-confirm",
}

# Reasonable guesses for a Cancel action in "Aksi" column
CANCEL_CANDIDATES = [
    # Your app may use different ones across statuses; env takes precedence
    ".cancel-button",
    ".btn-cancel",
    "button[title*='Cancel' i]",
    "button:has-text('Cancel')",
    "a:has(button):has(svg.feather-x)",
    "button:has(svg.feather-x)",
    "a:has(button):has(svg.feather-trash-2)",
    "button:has(svg.feather-trash-2)",
]
if CANCEL_SELECTOR_ENV:
    CANCEL_CANDIDATES.insert(0, CANCEL_SELECTOR_ENV)

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type((PWTimeout, asyncio.TimeoutError)))
async def with_retry(coro, *args, **kwargs):
    return await coro(*args, **kwargs)

async def wait_idle(page):
    # DataTables spinner
    try:
        await page.wait_for_selector(SEL["dt_processing"], state="hidden", timeout=7000)
    except PWTimeout:
        pass
    # Optional BlockUI
    try:
        if await page.is_visible(SEL["block_ui"]):
            await page.wait_for_selector(SEL["block_ui"], state="hidden", timeout=TIMEOUT_MS)
    except PWTimeout:
        pass
    await page.wait_for_load_state("networkidle")

async def apply_status_filter(page, status_value: str):
    logger.info(f"Setting Status Form filter to {status_value}")
    await page.select_option(SEL["select_status"], value=status_value)
    # Some pages auto-refresh on change; but we also have an explicit reload
    if await page.locator(SEL["reload_btn"]).count():
        await page.click(SEL["reload_btn"])
    await wait_idle(page)
    # Optional: log first row status after filter
    badge = page.locator(f"{SEL['datatable']} tbody tr td:nth-child(4) .badge").first
    try:
        txt = (await badge.text_content() or "").strip()
        logger.info(f"First row status: {txt}")
    except Exception:
        logger.warning("Could not read first row status")

async def find_cancel_buttons(page):
    for css in CANCEL_CANDIDATES:
        loc = page.locator(css)
        if await loc.count():
            logger.info(f"Found cancel buttons with selector: {css} (count={await loc.count()})")
            return loc, css
    return None, None

async def handle_swal_success(page):
    # Confirm
    try:
        await page.wait_for_selector(SEL["confirm_button"], state="visible", timeout=8000)
        await page.click(SEL["confirm_button"])
    except PWTimeout:
        logger.warning("No confirm button; action might be immediate")
    await wait_idle(page)
    # Success toast/modal
    try:
        await page.wait_for_selector(SEL["success_popup"], state="visible", timeout=10000)
        logger.info("Success popup detected")
        await page.click(SEL["ok_button"])
    except PWTimeout:
        logger.warning("No success popup detected")
    await wait_idle(page)

async def process_cancel_on_current_page(page, cap=None):
    processed = 0
    while True:
        loc, used = await find_cancel_buttons(page)
        if not loc:
            break
        try:
            btn = loc.first
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await handle_swal_success(page)
            processed += 1
            if cap and processed >= cap:
                break
            await asyncio.sleep(0.4)
        except Exception as e:
            logger.error(f"Click error on cancel [{used}]: {e}")
            break
    return processed

async def next_datatable_page(page):
    # The <li id="..._next"> toggles disabled class
    next_li = page.locator(SEL["next_page"])
    try:
        disabled = await next_li.evaluate("el => el.classList.contains('disabled')")
    except Exception:
        disabled = True
    if disabled:
        return False
    await next_li.locator("a.page-link").click()
    await wait_idle(page)
    return True

async def run_cancel_worker():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS, args=["--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(
                storage_state=STORAGE_STATE if os.path.exists(STORAGE_STATE) else None,
                viewport={"width": 1366, "height": 768},
            )
            context.set_default_timeout(TIMEOUT_MS)
            page = await context.new_page()
            try:
                logger.info(f"Navigating to {BASE_URL}")
                await page.goto(BASE_URL, timeout=TIMEOUT_MS)
                await page.wait_for_load_state("domcontentloaded")
                await wait_idle(page)
                await asyncio.sleep(0.5)

                await with_retry(apply_status_filter, page, STATUS_FILTER)

                total = 0
                page_idx = 1
                while True:
                    logger.info(f"Scanning page {page_idx}")
                    count = await process_cancel_on_current_page(page)
                    total += count
                    logger.info(f"Page {page_idx}: canceled {count} item(s)")
                    if not await next_datatable_page(page):
                        break
                    page_idx += 1

                logger.info(f"Done. Total canceled: {total}")

                if not HEADLESS:
                    logger.info("Keeping browser open for 3 minutes for manual inspection")
                    await asyncio.sleep(180)

            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                await context.close()
        finally:
            await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cancel Worker for Matcha Master")
    parser.parse_args()
    logger.info(f"Starting Cancel Worker ({WORKER_NAME})")
    asyncio.run(run_cancel_worker())
    logger.info("Cancel Worker completed")
