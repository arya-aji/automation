# worker_playwright.py
# ------------------------------------------------------------
# Requirements:
#   pip install playwright asyncpg tenacity loguru python-dotenv rapidfuzz
#   python -m playwright install chromium
#
# ENV (.env):
#   PGHOST=your-neon-host
#   PGDATABASE=your_db
#   PGUSER=your_user
#   PGPASSWORD=your_pass
#   PGPORT=5432
#   PGSSLMODE=require
#
#   BASE_URL=https://matchapro.web.bps.go.id/direktori-usaha
#   STORAGE_STATE=storage_state.json
#   NUM_WORKERS=3
#   WORKER_NAME=pc-jakpus-01
#   HEADLESS=false
#   TIMEOUT_MS=120000
#   LOG_LEVEL=INFO
# ------------------------------------------------------------

import os
import re
import argparse
import asyncio
from dotenv import load_dotenv
from loguru import logger
from tenacity import (
    retry, stop_after_attempt, wait_fixed, RetryError,
    retry_if_exception_type
)
import asyncpg
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from rapidfuzz import fuzz

load_dotenv()

# ---------- Konfigurasi ----------
PGHOST = os.getenv("PGHOST")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")
PGPORT = int(os.getenv("PGPORT", "5432"))
PGSSLMODE = os.getenv("PGSSLMODE", "require")

BASE_URL = os.getenv("BASE_URL", "https://example.com")
STORAGE_STATE = os.getenv("STORAGE_STATE", "storage_state.json")
NUM_WORKERS = int(os.getenv("NUM_WORKERS", "2"))
WORKER_NAME = os.getenv("WORKER_NAME", "worker-1")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "120000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level=LOG_LEVEL,
)

# ---------- Selector ----------
SEL = {
    "search_input": 'input[name="idsbr"]',
    "btn_filter": "#filter-data",
    "edit_buttons": 'a.btn-edit-perusahaan[aria-label="Edit"]',

    # SweetAlert2
    "swal_confirm": "button.swal2-confirm.swal2-styled",
    "swal_primary": "button.swal2-confirm.btn.btn-primary",
    "swal_popup": ".swal2-popup",
    "swal_text": ".swal2-html-container",

    # Form fields
    "alamat": "#alamat_usaha",
    "sumber": "#sumber_profiling",
    "catatan": "#catatan_profiling",
    "sls": "#sls",
    "lat": "#latitude",
    "lng": "#longitude",
    "email": "#email",
    "email_checkbox": "#check-email",
    "website": "#website",
    "telepon": "#telepon",
    "whatsapp": "#whatsapp",

    # Keberadaan Usaha (STATUS)
    "status_radios": "input[type='radio'][name='kondisi_usaha']",

    # Wilayah
    "provinsi": "#provinsi",          # value "116" -> [31] DKI JAKARTA
    "kabupaten": "#kabupaten_kota",   # value "2319" -> [73] JAKARTA PUSAT

    # Bentuk badan usaha
    "bentuk_badan_usaha": "#badan_usaha",

    # Tahun berdiri
    "tahun_berdiri": "#tahun_berdiri",

    # Jaringan usaha
    "jaringan_usaha_radios": "input[type='radio'][name='jaringan_usaha']",

    "cek_peta": "#cek-peta",
    "submit": "#submit-final",
    "confirm_consistency": "#confirm-consistency",
    "ignore_consistency": "#ignore-consistency",

    # Cancel submit (indikasi sudah pernah submit)
    "cancel_submit": "#cancel-submit-final",

    # Overlay loading
    "block_ui": ".blockUI",

    # Locked page indicators
    "form_header": 'h4:has-text("Form Update Usaha/Perusahaan")',
    "approval_alert": "div.alert.alert-warning",
}

# ---------- Error Kategori ----------
class InfraIssue(Exception): ...
class LockedByOther(Exception): ...
class AlreadyDone(Exception): ...
class ApprovalInProgress(Exception): ...

# ---------- Koneksi DB ----------
async def get_pool():
    return await asyncpg.create_pool(
        host=PGHOST, database=PGDATABASE, user=PGUSER, password=PGPASSWORD,
        port=PGPORT, ssl=True, min_size=1, max_size=max(2, NUM_WORKERS + 1)
    )

CLAIM_SQL = """
WITH cte AS (
  SELECT id
  FROM direktori_ids
  WHERE automation_status = 'new'
  ORDER BY attempt_count ASC, id ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED
)
UPDATE direktori_ids d
SET automation_status = 'in_progress',
    assigned_to = $1,
    first_taken_at = COALESCE(first_taken_at, NOW()),
    last_updated = NOW()
FROM cte
WHERE d.id = cte.id
RETURNING d.*;
"""

async def claim_one(pool, who):
    async with pool.acquire() as c:
        async with c.transaction():
            return await c.fetchrow(CLAIM_SQL, who)

async def mark_done(pool, id_, note: str | None = None):
    async with pool.acquire() as c:
        if note:
            await c.execute("""UPDATE direktori_ids
                SET automation_status='done', error=left($2,1000), last_updated=NOW()
                WHERE id=$1""", id_, note)
        else:
            await c.execute("""UPDATE direktori_ids
                SET automation_status='done', last_updated=NOW()
                WHERE id=$1""", id_)

async def mark_failed(pool, id_, err):
    async with pool.acquire() as c:
        await c.execute("""UPDATE direktori_ids
            SET automation_status='failed', error=left($2,1000),
                attempt_count=attempt_count+1, last_updated=NOW()
            WHERE id=$1""", id_, err)

async def mark_locked(pool, id_, note="locked_by_other"):
    async with pool.acquire() as c:
        await c.execute("""UPDATE direktori_ids
            SET automation_status='locked', error=left($2,1000), last_updated=NOW()
            WHERE id=$1""", id_, note)

async def release_to_new(pool, id_, note):
    async with pool.acquire() as c:
        await c.execute("""UPDATE direktori_ids
            SET automation_status='new', error=left($2,1000),
                attempt_count=attempt_count+1, last_updated=NOW()
            WHERE id=$1""", id_, note)

# ---------- Helpers ----------
async def wait_blockui_gone(page, timeout=15000):
    try:
        if await page.locator(SEL["block_ui"]).count() > 0:
            await page.wait_for_selector(SEL["block_ui"], state="detached", timeout=timeout)
    except PWTimeout:
        logger.warning("blockUI mungkin masih ada.")

async def click_if_visible(page, sel, timeout=1500):
    try:
        await page.locator(sel).click(timeout=timeout); return True
    except: return False

async def handle_any_swal(page):
    try:
        if await page.locator(SEL["swal_text"]).is_visible():
            _ = (await page.locator(SEL["swal_text"]).inner_text()).strip()
        await click_if_visible(page, SEL["swal_confirm"], 1200)
        await click_if_visible(page, SEL["swal_primary"], 1200)
    except: pass

def to_str(x): return "" if x is None else str(x)

async def dismiss_intro_popup(page):
    try:
        for _ in range(5):
            if await page.locator(".shepherd-content").count() == 0: break
            skip_btn = page.locator(".shepherd-content footer .shepherd-button",
                                    has_text=re.compile(r"^\s*skip\s*$", re.I))
            if await skip_btn.count() > 0:
                await skip_btn.first.click(); await page.wait_for_timeout(250); continue
            close_btn = page.locator(".shepherd-cancel-icon")
            if await close_btn.count() > 0:
                await close_btn.first.click(); await page.wait_for_timeout(250); continue
            await page.keyboard.press("Escape"); await page.wait_for_timeout(200)
    except: pass

async def ensure_logged_in(page):
    logger.info("➡️  buka BASE_URL & pastikan login")
    await page.goto(BASE_URL, timeout=TIMEOUT_MS)
    if "login" in page.url.lower():
        raise InfraIssue("Session expired. Re-record storage_state.")
    await dismiss_intro_popup(page)
    await page.wait_for_selector(SEL["btn_filter"], timeout=TIMEOUT_MS)
    logger.info("✅ landing siap")

# ---------- Deteksi ----------
async def is_locked_by_other(page) -> bool:
    try:
        await page.wait_for_load_state("domcontentloaded")
        title = (await page.title() or "").strip().lower()
        if title == "not authorized - matchapro":
            return True
        h2 = page.get_by_role("heading", name=re.compile(r"profiling\s*info", re.I))
        if await h2.count() > 0: return True
        p = page.locator("p", has_text=re.compile(
            r"tidak bisa melakukan edit.*sedang diedit oleh user lain", re.I))
        return await p.count() > 0
    except: return False

async def is_form_page(page) -> bool:
    try:
        await page.wait_for_load_state("domcontentloaded")
        if await page.locator(SEL["form_header"]).is_visible(): return True
        h = page.get_by_role("heading", name=re.compile(r"form\s+update\s+usaha/perusahaan", re.I))
        return await h.is_visible()
    except: return False

async def is_approval_in_progress(page) -> bool:
    try:
        await page.wait_for_load_state("domcontentloaded")
        alert = page.locator(SEL["approval_alert"])
        if await alert.count() == 0:
            return False
        head = alert.locator("h4.alert-heading")
        if await head.count() == 0:
            return False
        head_txt = (await head.first.inner_text()).strip().lower()
        if "info approval" not in head_txt:
            return False
        body = alert.locator(".alert-body")
        if await body.count() == 0:
            return True
        btxt = (await body.first.inner_text()).lower()
        return "sedang melalui proses approval" in btxt
    except:
        return False

# ---------- Email helpers ----------
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
def _is_valid_email(s: str | None) -> bool:
    return bool(s and EMAIL_RE.match(s.strip()))

# ---------- Field Setters ----------
async def set_email(page, email_value: str | None):
    """
    - Jika form sudah ada email valid -> biarkan & pastikan checkbox tetap tercentang.
    - Jika form kosong/tidak valid & DB punya email valid -> isi dari DB & centang.
    - Jika dua-duanya tidak valid -> kosongkan & uncheck.
    """
    has_input = await page.locator(SEL["email"]).count() > 0
    has_check = await page.locator(SEL["email_checkbox"]).count() > 0
    if not has_input and not has_check:
        return

    cur = ""
    try:
        if has_input:
            cur = (await page.locator(SEL["email"]).input_value()) or ""
    except:
        cur = ""

    cur_is_valid = _is_valid_email(cur)
    db_is_valid  = _is_valid_email(email_value)

    if cur_is_valid:
        if has_check:
            try:
                cb = page.locator(SEL["email_checkbox"]).first
                if not await cb.is_checked():
                    await cb.check()
            except: pass
        return

    if db_is_valid:
        if has_input:
            await page.fill(SEL["email"], email_value.strip())
        if has_check:
            try:
                cb = page.locator(SEL["email_checkbox"]).first
                if not await cb.is_checked():
                    await cb.check()
            except: pass
        return

    if has_input:
        try: await page.fill(SEL["email"], "")
        except: pass
    if has_check:
        try:
            cb = page.locator(SEL["email_checkbox"]).first
            if await cb.is_checked():
                await cb.uncheck()
        except:
            try: await page.locator(SEL["email_checkbox"]).click()
            except: pass

async def set_telepon(page, telepon_value: str | None):
    """
    - Jika form sudah ada nomor telepon & DB kosong -> biarkan nomor yang lama
    - Jika DB punya nomor telepon -> isi dari DB
    """
    has_input = await page.locator(SEL["telepon"]).count() > 0
    if not has_input:
        return

    cur = ""
    try:
        cur = (await page.locator(SEL["telepon"]).input_value()) or ""
    except:
        cur = ""

    # Jika form sudah ada nomor telepon & DB kosong -> biarkan nomor yang lama
    if cur.strip() and (not telepon_value or not telepon_value.strip()):
        return

    # Jika DB punya nomor telepon -> isi dari DB
    if telepon_value and telepon_value.strip():
        await page.fill(SEL["telepon"], telepon_value.strip())

async def set_whatsapp(page, whatsapp_value: str | None):
    """
    - Jika form sudah ada nomor whatsapp & DB kosong -> biarkan nomor yang lama
    - Jika DB punya nomor whatsapp -> isi dari DB
    """
    has_input = await page.locator(SEL["whatsapp"]).count() > 0
    if not has_input:
        return

    cur = ""
    try:
        cur = (await page.locator(SEL["whatsapp"]).input_value()) or ""
    except:
        cur = ""

    # Jika form sudah ada nomor whatsapp & DB kosong -> biarkan nomor yang lama
    if cur.strip() and (not whatsapp_value or not whatsapp_value.strip()):
        return

    # Jika DB punya nomor whatsapp -> isi dari DB
    if whatsapp_value and whatsapp_value.strip():
        await page.fill(SEL["whatsapp"], whatsapp_value.strip())

async def set_website(page, website_value: str | None):
    if await page.locator(SEL["website"]).count() > 0 and website_value and website_value.strip():
        await page.fill(SEL["website"], website_value.strip())

async def set_wilayah(page):
    """
    - Jika provinsi & kabupaten sudah terisi → skip.
    - Jika belum, pilih provinsi (116) → delay 600ms → pilih kabupaten (2319).
    - Guard: tunggu opsi kabupaten tersedia.
    """
    if await page.locator(SEL["provinsi"]).count() == 0 or await page.locator(SEL["kabupaten"]).count() == 0:
        return

    try:
        prov_val = await page.locator(SEL["provinsi"]).input_value()
    except:
        prov_val = ""
    try:
        kab_val = await page.locator(SEL["kabupaten"]).input_value()
    except:
        kab_val = ""

    if (prov_val or "").strip() and (kab_val or "").strip():
        logger.info(f"🔁 Wilayah sudah terisi (prov={prov_val}, kab={kab_val}) — skip set_wilayah")
        return

    logger.info("🗺️  Set wilayah: provinsi DKI JAKARTA, kab/kota JAKARTA PUSAT")
    try:
        await page.select_option(SEL["provinsi"], value="116")
    except:
        try:
            await page.select_option(SEL["provinsi"], label=re.compile(r"\[31\].*DKI.*JAKARTA", re.I))
        except:
            logger.warning("Gagal set provinsi via value/label.")

    await page.wait_for_timeout(600)

    kab_opt = page.locator(f"{SEL['kabupaten']} option[value='2319']")
    try:
        await kab_opt.wait_for(state="attached", timeout=5000)
    except:
        try:
            await page.wait_for_function(
                """(sel)=>document.querySelector(sel)?.querySelectorAll('option').length>1""",
                arg=SEL["kabupaten"],
                timeout=5000
            )
        except:
            logger.warning("Opsi kabupaten belum terload, lanjut coba select langsung.")

    try:
        await page.select_option(SEL["kabupaten"], value="2319")
    except:
        try:
            await page.select_option(SEL["kabupaten"], label=re.compile(r"\[73\].*JAKARTA\\s*PUSAT", re.I))
        except:
            logger.warning("Gagal set kabupaten via value/label.")

async def set_bentuk_badan_usaha(page, text_value: str | None):
    if await page.locator(SEL["bentuk_badan_usaha"]).count() == 0: return
    sel = page.locator(SEL["bentuk_badan_usaha"]).first
    
    # Cek apakah bentuk_badan_usaha sudah terisi di form
    try:
        current_value = await sel.evaluate("el => el.value")
        current_text = await sel.evaluate("el => el.options[el.selectedIndex].text")
        
        # Jika sudah terisi dan bukan "Lainnya", pertahankan nilai yang ada
        if current_value and current_value != "0" and current_text and "pilih" not in current_text.lower():
            # Cek apakah nilai saat ini adalah "Lainnya"
            if "lainnya" not in current_text.lower():
                return
    except: pass
    
    # Jika bentuk_badan_usaha dari database adalah "Lainnya" atau kosong, pilih opsi default "-- Pilih Badan Hukum/Usaha --"
    if not text_value or text_value.strip().lower() == "lainnya":
        try:
            # Pilih opsi pertama (biasanya opsi default "--Pilih....--")
            await sel.select_option(index=0)
            return
        except: pass
    
    try:
        options = await sel.locator("option").all_inner_texts()
        values  = await sel.locator("option").evaluate_all("opts=>opts.map(o=>o.value)")
        if not options or not values: return
        target = text_value.strip().lower()
        best_idx, best_score = -1, -1
        for i, opt in enumerate(options):
            score = fuzz.token_set_ratio(target, (opt or "").lower())
            if score > best_score:
                best_idx, best_score = i, score
        if best_idx >= 0 and best_idx < len(values):
            await sel.select_option(value=values[best_idx])
    except: pass

async def set_tahun_berdiri(page, year_value: str | None):
    if not year_value: return
    if await page.locator(SEL["tahun_berdiri"]).count() > 0:
        s = re.sub(r"[^\d]", "", str(year_value))
        if len(s) >= 4:
            await page.fill(SEL["tahun_berdiri"], s[:4])

async def set_jaringan_usaha(page, text_value: str | None):
    if not text_value: return
    radios = page.locator(SEL["jaringan_usaha_radios"])
    n = await radios.count()
    if n == 0: return
    target = text_value.strip().lower()
    best_idx, best_score = -1, -1
    for i in range(n):
        r = radios.nth(i)
        val = (await r.get_attribute("value")) or ""
        rid = (await r.get_attribute("id")) or ""
        label_text = ""
        try:
            if rid:
                lbl = page.locator(f"label[for='{rid}']")
                if await lbl.count() > 0:
                    label_text = (await lbl.first.inner_text()) or ""
            if not label_text:
                parent_label = r.locator("xpath=ancestor::label[1]")
                if await parent_label.count() > 0:
                    label_text = (await parent_label.first.inner_text()) or ""
        except: pass
        cand = f"{val} {label_text}".lower()
        score = fuzz.token_set_ratio(target, cand)
        if score > best_score:
            best_idx, best_score = i, score
    if best_idx >= 0:
        try: await radios.nth(best_idx).check()
        except:
            try: await radios.nth(best_idx).click()
            except: pass

async def set_keberadaan_usaha(page, status_text: str | None):
    if not status_text: return
    status = status_text.strip().lower()
    if status == "aktif":
        try:
            r = page.locator("input#kondisi_aktif")
            if await r.count() > 0:
                await r.first.check()
                return
        except: pass
    radios = page.locator(SEL["status_radios"])
    n = await radios.count()
    if n == 0: return
    best_idx, best_score = -1, -1
    for i in range(n):
        r = radios.nth(i)
        val = (await r.get_attribute("value")) or ""
        rid = (await r.get_attribute("id")) or ""
        label_text = ""
        try:
            if rid:
                lbl = page.locator(f"label[for='{rid}']")
                if await lbl.count() > 0:
                    label_text = (await lbl.first.inner_text()) or ""
        except: pass
        cand = f"{val} {label_text}".lower()
        score = fuzz.token_set_ratio(status, cand)
        if score > best_score:
            best_idx, best_score = i, score
    if best_idx >= 0:
        try: await radios.nth(best_idx).check()
        except:
            try: await radios.nth(best_idx).click()
            except: pass

# ---------- Open Edit ----------
async def open_edit_page(page):
    edit = page.locator(SEL["edit_buttons"]).first
    await edit.wait_for(state="visible", timeout=TIMEOUT_MS)
    try: await edit.evaluate("(a)=>a.removeAttribute('target')")
    except: pass
    
    # Buat task untuk menunggu halaman baru
    popup_task = asyncio.create_task(page.context.wait_for_event("page", timeout=5000))
    
    # Klik tombol edit
    await edit.click()
    await click_if_visible(page, SEL["swal_confirm"], 1500)
    await click_if_visible(page, SEL["swal_primary"], 1500)
    
    try:
        # Coba dapatkan halaman baru
        new_page = await popup_task
        await new_page.wait_for_load_state("domcontentloaded")
        await dismiss_intro_popup(new_page); await handle_any_swal(new_page)
        return new_page
    except Exception as e:
        logger.warning(f"Gagal mendapatkan halaman baru: {e}")
        # Tunggu sebentar untuk memastikan navigasi selesai
        await asyncio.sleep(1)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            return page
        except Exception as e2:
            logger.error(f"Gagal menunggu load state: {e2}")
            # Jika masih gagal, coba buat halaman baru
            new_page = await page.context.new_page()
            await new_page.goto(page.url)
            return new_page

# ---------- Proses 1 row ----------
@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(InfraIssue),
    reraise=True,
)
async def process_row(page, row):
    idsbr = row["idsbr"]

    # 0) beranda siap
    try: await ensure_logged_in(page)
    except PWTimeout: raise InfraIssue("Timeout memastikan beranda.")
    await dismiss_intro_popup(page)

    # 1) search
    logger.info(f"[{idsbr}] step: search")
    await page.fill(SEL["search_input"], to_str(idsbr))
    await wait_blockui_gone(page)
    await page.click(SEL["btn_filter"])
    await page.wait_for_timeout(800)

    # 2) cek hasil
    await page.wait_for_timeout(1500)  # Tambah delay untuk memastikan hasil pencarian sudah dimuat
    
    try:
        # Tunggu halaman stabil sebelum mencari tombol edit
        await page.wait_for_load_state("networkidle", timeout=5000)
        edits = await page.locator(SEL["edit_buttons"]).all()
        logger.info(f"[{idsbr}] hasil edit buttons = {len(edits)}")
        
        # Coba lagi jika tidak ada hasil
        if len(edits) == 0:
            logger.warning(f"[{idsbr}] Tidak ada hasil, mencoba lagi...")
            await page.click(SEL["btn_filter"])
            await page.wait_for_timeout(2000)  # Tambah delay lebih lama
            await page.wait_for_load_state("networkidle", timeout=5000)
            edits = await page.locator(SEL["edit_buttons"]).all()
            logger.info(f"[{idsbr}] hasil edit buttons setelah coba ulang = {len(edits)}")
        
        if len(edits) != 1:
            raise Exception(f"IDSBR {idsbr} tidak unik/0 hasil (len={len(edits)})")
    except Exception as e:
        if "Execution context was destroyed" in str(e):
            logger.warning(f"[{idsbr}] Konteks eksekusi rusak, mencoba ulang pencarian...")
            # Refresh halaman dan coba lagi
            await page.reload()
            await page.wait_for_timeout(2000)
            await page.fill(SEL["search_input"], to_str(idsbr))
            await wait_blockui_gone(page)
            await page.click(SEL["btn_filter"])
            await page.wait_for_timeout(2000)
            await page.wait_for_load_state("networkidle", timeout=5000)
            edits = await page.locator(SEL["edit_buttons"]).all()
            logger.info(f"[{idsbr}] hasil edit buttons setelah reload = {len(edits)}")
            
            if len(edits) != 1:
                raise Exception(f"IDSBR {idsbr} tidak unik/0 hasil setelah reload (len={len(edits)})")
        else:
            raise

    # 3) buka edit
    logger.info(f"[{idsbr}] step: open edit page")
    page = await open_edit_page(page)
    try:
        logger.info(f"[{idsbr}] after edit -> url={page.url} | title={await page.title()}")
    except: pass

    # 4) race: locked atau form
    try:
        for _ in range(3):
            await wait_blockui_gone(page, timeout=20000)
            await dismiss_intro_popup(page)
            if await is_locked_by_other(page):
                raise LockedByOther(idsbr)
            if await is_form_page(page):
                break
            await page.wait_for_timeout(800)
        if await is_locked_by_other(page):
            raise LockedByOther(idsbr)
        if not await is_form_page(page):
            raise InfraIssue("Form tidak muncul setelah edit.")
    except PWTimeout:
        raise InfraIssue("Timeout menunggu locked/form.")

    # 4a) approval in progress?
    if await is_approval_in_progress(page):
        logger.info(f"[{idsbr}] 🟡 approval in progress, skip as done")
        raise ApprovalInProgress(idsbr)

    # 4b) sudah pernah submit?
    try:
        if await page.locator(SEL["cancel_submit"]).is_visible():
            raise AlreadyDone(idsbr)
    except: pass

    # 5) isi field dasar
    logger.info(f"[{idsbr}] step: fill core fields")
    
    # Cek status untuk menentukan pengisian alamat
    status = row.get("status") if isinstance(row, dict) else row["status"]
    alamat = to_str(row["alamat"])
    nama_sls = to_str(row["nama_sls"])
    
    # Jika status "Aktif" dan alamat kosong, gunakan nama_sls sebagai alamat
    if status and status.strip().lower() == "aktif" and not alamat.strip():
        alamat = nama_sls
    
    await page.fill(SEL["alamat"], alamat)
    await page.fill(SEL["sumber"], to_str(row["sumber_profiling"]))
    await page.fill(SEL["catatan"], to_str(row["catatan_profiling"]))
    await page.fill(SEL["sls"], nama_sls)

    # 6) email & website
    await set_email(page, row.get("email") if isinstance(row, dict) else row["email"])
    await set_telepon(page, row.get("nomor_telepon") if isinstance(row, dict) else row["nomor_telepon"])
    await set_whatsapp(page, row.get("nomor_whatsapp") if isinstance(row, dict) else row["nomor_whatsapp"])
    await set_website(page, row.get("website") if isinstance(row, dict) else row["website"])

    # 7) lat/lng
    await page.fill(SEL["lat"], ""); await page.fill(SEL["lng"], "")
    lat = row.get("latitude") if isinstance(row, dict) else row["latitude"]
    lng = row.get("longitude") if isinstance(row, dict) else row["longitude"]
    if lat is not None and str(lat).strip(): await page.fill(SEL["lat"], str(lat))
    if lng is not None and str(lng).strip(): await page.fill(SEL["lng"], str(lng))

    # 8) status
    await set_keberadaan_usaha(page, row.get("status") if isinstance(row, dict) else row["status"])

    # 9) wilayah
    await set_wilayah(page)

    # 10) bentuk badan usaha
    await set_bentuk_badan_usaha(page, row.get("bentuk_badan_usaha") if isinstance(row, dict) else row["bentuk_badan_usaha"])

    # 11) tahun berdiri
    await set_tahun_berdiri(page, row.get("tahun_berdiri") if isinstance(row, dict) else row["tahun_berdiri"])

    # 12) jaringan usaha
    await set_jaringan_usaha(page, row.get("jaringan_usaha") if isinstance(row, dict) else row["jaringan_usaha"])

    # 13) cek peta & submit
    logger.info(f"[{idsbr}] step: cek-peta")
    await page.click(SEL["cek_peta"])
    await wait_blockui_gone(page, timeout=25000)

    logger.info(f"[{idsbr}] step: submit")
    await page.click(SEL["submit"])
    await click_if_visible(page, SEL["confirm_consistency"], 2000)
    await click_if_visible(page, SEL["ignore_consistency"], 2000)
    ok = await click_if_visible(page, SEL["swal_primary"], 5000)
    if not ok: await click_if_visible(page, SEL["swal_confirm"], 5000)
    await page.wait_for_selector(SEL["swal_popup"], timeout=TIMEOUT_MS)
    await handle_any_swal(page)
    logger.info(f"[{idsbr}] ✅ submitted")

# ---------- Worker loop ----------
async def run_worker(idx: int, pool):
    logger.info(f"[{WORKER_NAME}:{idx}] started")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-notifications",
                "--mute-audio",
                "--window-position=0,0",
                "--window-size=1366,768",
            ],
        )

        if not os.path.exists(STORAGE_STATE):
            logger.error(f"Storage state '{STORAGE_STATE}' tidak ditemukan. Jalankan login recorder dulu.")
            await browser.close()
            return

        NORMAL_UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        context = await browser.new_context(
            storage_state=STORAGE_STATE,
            user_agent=NORMAL_UA,
            viewport={"width": 1366, "height": 768},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            color_scheme="light",
            device_scale_factor=1.0,
        )

        # --- Stealth patches (anti headless detection) ---
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
            if (originalQuery) {
              window.navigator.permissions.query = (parameters) => (
                parameters && parameters.name === 'notifications'
                  ? Promise.resolve({ state: Notification.permission })
                  : originalQuery(parameters)
              );
            }
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['id-ID','id','en-US','en'] });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(window, 'devicePixelRatio', { get: () => 1 });
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
              const debugInfo = this.getExtension('WEBGL_debug_renderer_info');
              if (debugInfo) {
                if (parameter === debugInfo.UNMASKED_VENDOR_WEBGL) return 'Intel Inc.';
                if (parameter === debugInfo.UNMASKED_RENDERER_WEBGL) return 'Intel Iris OpenGL Engine';
              }
              return getParameter.apply(this, [parameter]);
            };
        """)

        # Paksa window.open → same-tab
        await context.add_init_script("""
          (function(){
            const _open = window.open;
            window.open = function(url, name, feats){
              try { if (url) { window.location.href = url; return window; } }
              catch(e){}
              return _open.apply(window, arguments);
            };
          })();
        """)

        while True:
            row = await claim_one(pool, f"{WORKER_NAME}:{idx}")
            if not row:
                logger.info(f"[{WORKER_NAME}:{idx}] no more rows. exiting.")
                break

            id_db, idsbr = row["id"], row["idsbr"]
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT_MS)
            page.set_default_navigation_timeout(TIMEOUT_MS)

            try:
                await process_row(page, row)
                await mark_done(pool, id_db)
                logger.info(f"[{WORKER_NAME}:{idx}] ✅ done idsbr={idsbr}")

            except ApprovalInProgress:
                await mark_done(pool, id_db, "approval_in_progress")
                logger.info(f"[{WORKER_NAME}:{idx}] 🟡 approval in progress -> mark done idsbr={idsbr}")

            except AlreadyDone:
                await mark_done(pool, id_db, "already_submitted_cancel_present")
                logger.info(f"[{WORKER_NAME}:{idx}] ⏩ skip (already submitted) idsbr={idsbr}")

            except LockedByOther:
                await mark_locked(pool, id_db, "locked_by_other")
                logger.info(f"[{WORKER_NAME}:{idx}] 🔒 locked idsbr={idsbr}")

            except RetryError as e:
                await release_to_new(pool, id_db, f"retry_timeout:{str(e)[:180]}")
                logger.warning(f"[{WORKER_NAME}:{idx}] ⏳ retry timeout, release idsbr={idsbr}")

            except InfraIssue as e:
                await release_to_new(pool, id_db, str(e)[:180])
                logger.warning(f"[{WORKER_NAME}:{idx}] 🌐 infra issue, release idsbr={idsbr}: {e}")

            except Exception as e:
                await mark_failed(pool, id_db, str(e)[:1000])
                logger.error(f"[{WORKER_NAME}:{idx}] ❌ failed idsbr={idsbr} err={e}")

            finally:
                await page.close()

        await browser.close()

# ---------- DEBUG MODE (single IDsBR) ----------
async def get_pool_oneoff():
    return await asyncpg.create_pool(
        host=PGHOST, database=PGDATABASE, user=PGUSER, password=PGPASSWORD,
        port=PGPORT, ssl=True, min_size=1, max_size=1
    )

async def fetch_row_by_idsbr(idsbr: int | str):
    pool = await get_pool_oneoff()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM direktori_ids
                 WHERE idsbr = $1::text
                 LIMIT 1
            """, str(idsbr))
            if not row:
                raise RuntimeError(f"IDsBR {idsbr} tidak ditemukan di direktori_ids.")
            return row
    finally:
        await pool.close()

async def run_debug_single(idsbr: int | str, slowmo: int = 200, devtools: bool = False):
    row = await fetch_row_by_idsbr(idsbr)
    logger.info(f"[DEBUG] Load row IDsBR={idsbr} id_db={row['id']}")

    if not os.path.exists(STORAGE_STATE):
        raise RuntimeError(f"Storage state '{STORAGE_STATE}' tidak ditemukan. Jalankan recorder login dulu.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=slowmo,
            devtools=devtools,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"]
        )
        context = await browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1366, "height": 768},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        await context.add_init_script("""
          (function(){
            const _open = window.open;
            window.open = function(url, name, feats){
              try { if (url) { window.location.href = url; return window; } }
              catch(e){}
              return _open.apply(window, arguments);
            };
          })();
        """)
        page = await context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.set_default_navigation_timeout(TIMEOUT_MS)

        logger.info(f"[DEBUG] ▶️ mulai flow IDsBR={idsbr} (slowmo={slowmo}ms)")
        try:
            await process_row(page, row)
            logger.info("[DEBUG] ✅ submit selesai")
        except AlreadyDone:
            logger.info("[DEBUG] ⏩ sudah pernah submit (Cancel Submit terdeteksi) — skip")
        except ApprovalInProgress:
            logger.info("[DEBUG] 🟡 sedang approval — skip as done")
        except LockedByOther:
            logger.info("[DEBUG] 🔒 dikunci user lain (Profiling Info)")
        except InfraIssue as e:
            logger.error(f"[DEBUG] 🌐 infra issue: {e}")
        except Exception as e:
            logger.exception(f"[DEBUG] ❌ error umum: {e}")

        logger.info("[DEBUG] ⏳ biarkan browser terbuka 25 detik untuk inspeksi manual…")
        await asyncio.sleep(25)
        await context.close()
        await browser.close()

# ---------- Entry point ----------
def parse_args():
    ap = argparse.ArgumentParser(description="Worker/Debug MatchaPro")
    ap.add_argument("--debug-idsbr", type=str, help="Jalankan 1 IDsBR (headful) untuk melihat seluruh tahapan")
    ap.add_argument("--slowmo", type=int, default=200, help="Delay ms antar aksi saat debug (default 200)")
    ap.add_argument("--devtools", action="store_true", help="Buka DevTools saat debug")
    return ap.parse_args()

async def main():
    args = parse_args()
    missing = [k for k,v in {"PGHOST":PGHOST,"PGDATABASE":PGDATABASE,"PGUSER":PGUSER,"PGPASSWORD":PGPASSWORD}.items() if not v]
    if missing: raise RuntimeError(f"ENV kurang: {', '.join(missing)}")

    if args.debug_idsbr:
        await run_debug_single(args.debug_idsbr, slowmo=args.slowmo, devtools=args.devtools)
        return

    pool = await get_pool()
    try:
        await asyncio.gather(*[run_worker(i+1, pool) for i in range(NUM_WORKERS)])
    finally:
        await pool.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("Dihentikan oleh user.")
