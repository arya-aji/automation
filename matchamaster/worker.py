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

    # Wilayah (cascade select2 di atas <select> asli)
    "provinsi": "#provinsi",           # contoh value "116" untuk [31] DKI JAKARTA
    "kabupaten": "#kabupaten_kota",    # contoh value "2319" untuk [73] JAKARTA PUSAT
    "kecamatan": "#kecamatan",         # ← NEW
    "kelurahan": "#kelurahan_desa",    # ← NEW

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

    # Halaman/form indikator
    "form_header": 'h4:has-text("Form Update Usaha/Perusahaan")',
    "approval_alert": "div.alert.alert-warning",

    # KBLI/Kegiatan Usaha
    "container_repeater": "#container-kegiatan-usaha-repeater",
    "btn_add_kegiatan": "#add-kegiatan-usaha",
    "row_kegiatan": "[data-repeater-item]",
    "inp_kegiatan": "input.l_kegiatan_usaha",
    "sel_kategori": "select.l_kategori_usaha",
    "sel_kbli": "select.l_kbli",
    "inp_produk": "input.l_produk_utama",
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
    first_taken_at = COALESCE(first_taken_at, NOW() ),
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
    """Klik OK semua SweetAlert yang terlihat (termasuk error lat/lng)."""
    try:
        if await page.locator(SEL["swal_text"]).is_visible():
            txt = (await page.locator(SEL["swal_text"]).inner_text()).strip()
            logger.info(f"SWAL: {txt}")
        await click_if_visible(page, SEL["swal_confirm"], 2000)
        await click_if_visible(page, SEL["swal_primary"], 2000)
    except: pass

def to_str(x): return "" if x is None else str(x)

async def dismiss_intro_popup(page):
    """Tutup shepherd tour (Skip/Close/Escape)."""
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

# ---------- Email/Phone helpers ----------
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
def _is_valid_email(s: str | None) -> bool:
    return bool(s and EMAIL_RE.match(s.strip()))

def _only_digits(s: str | None) -> str:
    if not s: return ""
    return re.sub(r"\D", "", str(s))

# ---------- Field Setters ----------
async def set_keberadaan_usaha(page, keberadaan: str):
    """
    Mengatur keberadaan usaha (aktif/tidak aktif/dll) sesuai data database.

    keberadaan: string, misalnya "Aktif", "Tidak Aktif", "Tutup Sementara"
    """
    try:
        # Pastikan ada elemen select/radio box untuk keberadaan
        locator = page.locator("#keberadaan_usaha")
        if await locator.count() > 0:
            await locator.select_option(label=keberadaan)
            print(f"✅ Keberadaan usaha diset ke {keberadaan}")
        else:
            print("⚠️ Elemen keberadaan usaha tidak ditemukan, skip.")
    except Exception as e:
        print(f"❌ Gagal set keberadaan usaha: {e}")

async def set_alamat(page, alamat_value: str | None):
    has_input = await page.locator(SEL["alamat"]).count() > 0
    if not has_input:
        return

    # Baca nilai yang sekarang ada di field form
    cur = ""
    try:
        cur = (await page.locator(SEL["alamat"]).input_value()) or ""
    except:
        cur = ""

    db_value = (alamat_value or "").strip()

    # Kalau DB kosong → jangan ubah isi lama
    if not db_value:
        return

    # Kalau DB ada isinya → isi ulang
    await page.fill(SEL["alamat"], db_value)

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
    has_input = await page.locator(SEL["telepon"]).count() > 0
    if not has_input: return

    cur = ""
    try: cur = (await page.locator(SEL["telepon"]).input_value()) or ""
    except: cur = ""

    db_digits = _only_digits(telepon_value)
    if cur.strip() and not db_digits:
        return
    if db_digits:
        await page.fill(SEL["telepon"], db_digits)

async def set_whatsapp(page, whatsapp_value: str | None):
    has_input = await page.locator(SEL["whatsapp"]).count() > 0
    if not has_input: return

    cur = ""
    try: cur = (await page.locator(SEL["whatsapp"]).input_value()) or ""
    except: cur = ""

    db_digits = _only_digits(whatsapp_value)
    if cur.strip() and not db_digits:
        return
    if db_digits:
        await page.fill(SEL["whatsapp"], db_digits)

async def set_website(page, website_value: str | None):
    if await page.locator(SEL["website"]).count() > 0 and website_value and website_value.strip():
        await page.fill(SEL["website"], website_value.strip())

# ---- Wilayah helpers (KD-based) ----
def _norm_code(v) -> str | None:
    """Ambil digit saja + buang leading zero. '073' -> '73'; '010' -> '10'."""
    if v is None:
        return None
    s = re.sub(r"\D", "", str(v))
    s = s.lstrip("0")
    return s or None

async def _wait_options_loaded(page, sel_css: str, min_count: int = 2, timeout: int = 6000):
    """Tunggu select punya >= min_count option (umumnya setelah cascade)."""
    try:
        await page.wait_for_function(
            """(sel,minCount)=>{ const el=document.querySelector(sel);
                                  return !!el && el.querySelectorAll('option').length>=minCount }""",
            arg=(sel_css, min_count),
            timeout=timeout
        )
    except:
        pass

async def _select_by_label_code(page, sel_css: str, code_norm: str) -> bool:
    """
    Pilih option berdasar label yang mengandung [code_norm] (toleran leading zero).
    Return True jika berhasil.
    """
    label_re = re.compile(rf"\[\s*0*{re.escape(code_norm)}\s*\]", re.I)
    try:
        await page.select_option(sel_css, label=label_re)
        return True
    except:
        pass
    try:
        opts = page.locator(f"{sel_css} option")
        n = await opts.count()
        for i in range(n):
            txt = (await opts.nth(i).inner_text() or "").strip()
            if label_re.search(txt):
                val = await opts.nth(i).get_attribute("value")
                if val:
                    await page.select_option(sel_css, value=val)
                    return True
    except:
        pass
    return False

def _pad3(x) -> str:
    """Pastikan kode 3 digit, misal '10' -> '010'."""
    try:
        return f"{int(str(x).strip()):03d}"
    except:
        s = str(x or "").strip()
        return (("000"+s)[-3:]) if s else ""

async def _get_selected_text(page, sel_css: str) -> str:
    try:
        return await page.locator(sel_css).evaluate("el => el.options?.[el.selectedIndex]?.text || ''")
    except:
        return ""

async def set_wilayah_from_db(page, kdkab: str | int | None, kdkec: str | int | None, kddesa: str | int | None):
    """
    Mengisi:
      - Provinsi: tetap DKI (value='116') jika belum terisi.
      - Kabupaten/Kota: pilih berdasarkan kdkab (label seperti '[73] JAKARTA PUSAT').
      - Kecamatan: pilih berdasarkan kdkec (label seperti '[010] TANAH ABANG').
      - Kelurahan/Desa: pilih berdasarkan kddesa (label seperti '[001] GELORA').

    Semua pemilihan berbasis label (teks option) agar robust terhadap value dinamis.
    """
    # Pastikan elemen ada
    if await page.locator(SEL["provinsi"]).count() == 0:
        return

    # 0) Pastikan Provinsi DKI JAKARTA (116) bila kosong
    try:
        prov_text = (await _get_selected_text(page, SEL["provinsi"])).lower()
    except:
        prov_text = ""
    if not prov_text or "jakarta" not in prov_text:
        try:
            await page.select_option(SEL["provinsi"], value="116")
        except:
            try:
                await page.select_option(SEL["provinsi"], label=re.compile(r"\[31\].*DKI.*JAKARTA", re.I))
            except:
                logger.warning("Gagal set provinsi DKI, lanjut tetap coba kab/kec/desa.")
    # Beri waktu load dependent dropdown
    await page.wait_for_timeout(600)

    # Jika DB tidak menyediakan kdkab/kdkec/kddesa, fallback ke behavior lama (DKI / Jakpus default)
    if not kdkab:
        return await set_wilayah(page)

    # Normalisasi kode label
    kdkab_s  = str(kdkab).strip()                 # contoh '73'
    kdkec_s  = _pad3(kdkec) if kdkec is not None else ""  # contoh '010'
    kddesa_s = _pad3(kddesa) if kddesa is not None else ""# contoh '001'

    kab_css = SEL["kabupaten"]
    kec_css = SEL["kecamatan"] if "kecamatan" in SEL else "#kecamatan"
    kel_css = SEL["kelurahan"] if "kelurahan" in SEL else "#kelurahan_desa"

    # 1) KAB/KOTA
    if await page.locator(kab_css).count() > 0:
        # Skip jika sudah sesuai
        cur_kab_txt = await _get_selected_text(page, kab_css)
        if not re.search(rf"\[\s*{re.escape(kdkab_s)}\s*\]", cur_kab_txt or "", re.I):
            # Tunggu opsi termuat
            try:
                await page.wait_for_function(
                    "(sel)=>document.querySelector(sel)?.querySelectorAll('option').length>1",
                    arg=kab_css, timeout=5000
                )
            except:
                pass
            # Pilih berdasarkan label [XX]
            try:
                await page.select_option(
                    kab_css,
                    label=re.compile(rf"\[\s*{re.escape(kdkab_s)}\s*\]", re.I)
                )
            except:
                logger.warning(f"Gagal set kabupaten via label [ {kdkab_s} ], coba brute-find.")
                # Brute: cari option yang match lalu set value-nya
                try:
                    opt_val = await page.locator(
                        f"{kab_css} option",
                        has_text=re.compile(rf"\[\s*{re.escape(kdkab_s)}\s*\]", re.I)
                    ).first.get_attribute("value")
                    if opt_val:
                        await page.select_option(kab_css, value=opt_val)
                except:
                    logger.warning("Brute-find kabupaten juga gagal.")
        await page.wait_for_timeout(600)

    # 2) KECAMATAN
    if kdkec_s and await page.locator(kec_css).count() > 0:
        cur_kec_txt = await _get_selected_text(page, kec_css)
        if not re.search(rf"\[\s*{re.escape(kdkec_s)}\s*\]", cur_kec_txt or "", re.I):
            # Tunggu opsi kecamatan muncul setelah pilih kabupaten
            try:
                await page.wait_for_function(
                    "(sel)=>document.querySelector(sel)?.querySelectorAll('option').length>1",
                    arg=kec_css, timeout=7000
                )
            except:
                pass
            try:
                await page.select_option(
                    kec_css,
                    label=re.compile(rf"\[\s*{re.escape(kdkec_s)}\s*\]", re.I)
                )
            except:
                logger.warning(f"Gagal set kecamatan via label [ {kdkec_s} ], coba brute-find.")
                try:
                    opt_val = await page.locator(
                        f"{kec_css} option",
                        has_text=re.compile(rf"\[\s*{re.escape(kdkec_s)}\s*\]", re.I)
                    ).first.get_attribute("value")
                    if opt_val:
                        await page.select_option(kec_css, value=opt_val)
                except:
                    logger.warning("Brute-find kecamatan juga gagal.")
        await page.wait_for_timeout(500)

    # 3) KELURAHAN/DESA
    if kddesa_s and await page.locator(kel_css).count() > 0:
        cur_kel_txt = await _get_selected_text(page, kel_css)
        if not re.search(rf"\[\s*{re.escape(kddesa_s)}\s*\]", cur_kel_txt or "", re.I):
            # Tunggu opsi kelurahan muncul setelah pilih kecamatan
            try:
                await page.wait_for_function(
                    "(sel)=>document.querySelector(sel)?.querySelectorAll('option').length>1",
                    arg=kel_css, timeout=7000
                )
            except:
                pass
            try:
                await page.select_option(
                    kel_css,
                    label=re.compile(rf"\[\s*{re.escape(kddesa_s)}\s*\]", re.I)
                )
            except:
                logger.warning(f"Gagal set kelurahan via label [ {kddesa_s} ], coba brute-find.")
                try:
                    opt_val = await page.locator(
                        f"{kel_css} option",
                        has_text=re.compile(rf"\[\s*{re.escape(kddesa_s)}\s*\]", re.I)
                    ).first.get_attribute("value")
                    if opt_val:
                        await page.select_option(kel_css, value=opt_val)
                except:
                    logger.warning("Brute-find kelurahan juga gagal.")
        await page.wait_for_timeout(400)


async def set_wilayah(
    page,
    kdprov: str | int | None = None,
    kdkab:  str | int | None = None,
    kdkec:  str | int | None = None,
    kddesa: str | int | None = None,
):
    """
    Urutan:
      1) Provinsi (kdprov)  → tunggu load kabupaten
      2) Kab/Kota (kdkab)   → tunggu load kecamatan
      3) Kecamatan (kdkec)  → tunggu load kelurahan/desa
      4) Kelurahan/Desa (kddesa)
    Jika sudah terisi lengkap, skip. Fallback: DKI (116) & Jakpus ([73]) jika kd kosong/ga match.
    """
    for key in ("provinsi", "kabupaten", "kecamatan", "kelurahan"):
        if await page.locator(SEL[key]).count() == 0:
            logger.warning(f"Select wilayah '{key}' tidak ditemukan, skip set_wilayah")
            return

    # Sudah lengkap?
    try:  prov_val = (await page.locator(SEL["provinsi"]).input_value()) or ""
    except: prov_val = ""
    try:  kab_val  = (await page.locator(SEL["kabupaten"]).input_value()) or ""
    except: kab_val = ""
    try:  kec_val  = (await page.locator(SEL["kecamatan"]).input_value()) or ""
    except: kec_val = ""
    try:  kel_val  = (await page.locator(SEL["kelurahan"]).input_value()) or ""
    except: kel_val = ""

    if prov_val.strip() and kab_val.strip() and kec_val.strip() and kel_val.strip():
        logger.info("🔁 Wilayah sudah lengkap (prov/kab/kec/kel) — skip set_wilayah")
        return

    kdprov_norm = _norm_code(kdprov)
    kdkab_norm  = _norm_code(kdkab)
    kdkec_norm  = _norm_code(kdkec)
    kddesa_norm = _norm_code(kddesa)

    # 1) Provinsi
    if not prov_val.strip():
        ok_prov = False
        if kdprov_norm:
            ok_prov = await _select_by_label_code(page, SEL["provinsi"], kdprov_norm)
            if not ok_prov:
                logger.warning(f"Gagal set provinsi kode [{kdprov_norm}], fallback ke DKI (116).")
        if not ok_prov:
            try:
                await page.select_option(SEL["provinsi"], value="116")
                ok_prov = True
            except:
                try:
                    await page.select_option(SEL["provinsi"], label=re.compile(r"\[31\].*DKI.*JAKARTA", re.I))
                    ok_prov = True
                except:
                    logger.warning("Gagal set provinsi via fallback DKI.")
        await page.wait_for_timeout(600)
        await _wait_options_loaded(page, SEL["kabupaten"], min_count=2)

    # 2) Kab/Kota
    if not kab_val.strip():
        ok_kab = False
        if kdkab_norm:
            ok_kab = await _select_by_label_code(page, SEL["kabupaten"], kdkab_norm)
        if not ok_kab:
            # fallback Jakpus
            try:
                await page.select_option(SEL["kabupaten"], label=re.compile(r"\[\s*73\s*\].*JAKARTA\s*PUSAT", re.I))
                ok_kab = True
            except:
                try:
                    await page.select_option(SEL["kabupaten"], value="2319")
                    ok_kab = True
                except:
                    logger.warning("Gagal set kabupaten via fallback.")
        await page.wait_for_timeout(500)
        await _wait_options_loaded(page, SEL["kecamatan"], min_count=2)

    # 3) Kecamatan
    if not kec_val.strip():
        if kdkec_norm:
            ok_kec = await _select_by_label_code(page, SEL["kecamatan"], kdkec_norm)
            if not ok_kec:
                logger.warning(f"Gagal set kecamatan kode [{kdkec_norm}]")
        await page.wait_for_timeout(400)
        await _wait_options_loaded(page, SEL["kelurahan"], min_count=2)

    # 4) Kelurahan/Desa
    if not kel_val.strip():
        if kddesa_norm:
            ok_kel = await _select_by_label_code(page, SEL["kelurahan"], kddesa_norm)
            if not ok_kel:
                logger.warning(f"Gagal set kelurahan kode [{kddesa_norm}]")


async def set_bentuk_badan_usaha(page, text_value: str | None):
    if await page.locator(SEL["bentuk_badan_usaha"]).count() == 0: return
    sel = page.locator(SEL["bentuk_badan_usaha"]).first

    # Jika sudah ada pilihan yang valid (bukan "-- pilih --" dan bukan "lainnya") → pertahankan
    try:
        current_value = await sel.evaluate("el => el.value")
        current_text = await sel.evaluate("el => el.options[el.selectedIndex].text")
        if current_value and current_text and "pilih" not in current_text.lower():
            if "lainnya" not in current_text.lower():
                return
    except: pass

    if not text_value or text_value.strip().lower() == "lainnya":
        try:
            await sel.select_option(index=0)  # default
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
        if 0 <= best_idx < len(values):
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

# ---------- KBLI / Kegiatan Usaha ----------
async def inject_kbli_row(page, kbli: str | None, kategori: str | None, deskripsi: str | None):
    """
    Isi 1 baris kegiatan usaha:
      - input.l_kegiatan_usaha  (pakai deskripsi)
      - select.l_kategori_usaha (pilih berdasarkan kode kategori A..U)
      - select.l_kbli           (pilih berdasarkan kode KBLI, contoh '46636')
      - input.l_produk_utama    (optional: kosongkan atau isi dengan deskripsi)
    Jika belum ada baris, klik Add New dulu.
    """
    if not (kbli or kategori or deskripsi):
        return

    container = page.locator(SEL["container_repeater"])
    if await container.count() == 0:
        logger.warning("Container kegiatan usaha tidak ditemukan"); return

    rows = container.locator(SEL["row_kegiatan"])
    n = await rows.count()
    if n == 0:
        await page.click(SEL["btn_add_kegiatan"])
        await page.wait_for_timeout(400)
        rows = container.locator(SEL["row_kegiatan"])
        n = await rows.count()
        if n == 0:
            logger.warning("Gagal menambah baris kegiatan usaha"); return

    row0 = rows.nth(0)

    # Kegiatan/Deskripsi
    if deskripsi and deskripsi.strip():
        try:
            await row0.locator(SEL["inp_kegiatan"]).fill(deskripsi.strip())
        except: pass

    # Kategori (A..U)
    if kategori and str(kategori).strip():
        kat = str(kategori).strip().upper()[:1]
        try:
            await row0.locator(SEL["sel_kategori"]).select_option(value=kat)
        except:
            try:
                await row0.locator(SEL["sel_kategori"]).select_option(label=re.compile(rf"^\s*{kat}\s*-", re.I))
            except: pass

    # KBLI (kode angka)
    if kbli and str(kbli).strip():
        kode = re.sub(r"\D", "", str(kbli))
        if kode:
            sel_kbli = row0.locator(SEL["sel_kbli"])
            try:
                await sel_kbli.select_option(value=kode)
            except:
                try:
                    await sel_kbli.select_option(label=re.compile(rf"^{re.escape(kode)}$", re.I))
                except: pass

    # Optional isi produk = deskripsi
    try:
        if deskripsi and deskripsi.strip():
            await row0.locator(SEL["inp_produk"]).fill(deskripsi.strip())
    except: pass

# ---------- SweetAlert lat/lng ----------
async def handle_latlng_error_on_open(page):
    """Segera tutup swal 'Format latitude tidak valid' jika muncul saat open form."""
    try:
        if await page.locator(SEL["swal_popup"]).count() > 0:
            txt = (await page.locator(SEL["swal_text"]).inner_text()).strip().lower()
            if "latitude" in txt and "tidak valid" in txt:
                logger.info("ℹ️  SWAL lat/lng saat open form → klik OK")
                await handle_any_swal(page)
            if "longitude" in txt and "tidak valid" in txt:
                logger.info("ℹ️  SWAL lat/lng saat open form → klik OK")
                await handle_any_swal(page)
    except: pass

async def handle_latlng_error_after_submit(page):
    """Setelah submit, kalau swal error lat/lng muncul, klik OK lalu lanjut (jangan skip)."""
    try:
        if await page.locator(SEL["swal_popup"]).count() > 0:
            txt = (await page.locator(SEL["swal_text"]).inner_text()).strip().lower()
            if "latitude" in txt and "tidak valid" in txt:
                logger.info("ℹ️  SWAL lat/lng setelah submit → klik OK & lanjut")
                await handle_any_swal(page)
            if "longitude" in txt and "tidak valid" in txt:
                logger.info("ℹ️  SWAL lat/lng setelah submit → klik OK & lanjut")
                await handle_any_swal(page)
    except: pass

# ---------- Open Edit ----------
async def open_edit_page(page):
    edit = page.locator(SEL["edit_buttons"]).first
    await edit.wait_for(state="visible", timeout=TIMEOUT_MS)
    try: await edit.evaluate("(a)=>a.removeAttribute('target')")
    except: pass

    popup_task = asyncio.create_task(page.context.wait_for_event("page", timeout=5000))

    await edit.click()
    await click_if_visible(page, SEL["swal_confirm"], 1500)
    await click_if_visible(page, SEL["swal_primary"], 1500)

    try:
        new_page = await popup_task
        await new_page.wait_for_load_state("domcontentloaded")
        await dismiss_intro_popup(new_page); await handle_any_swal(new_page)
        return new_page
    except Exception as e:
        logger.warning(f"Gagal mendapatkan halaman baru: {e}")
        await asyncio.sleep(1)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            return page
        except Exception as e2:
            logger.error(f"Gagal menunggu load state: {e2}")
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
    await page.wait_for_timeout(1500)
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
        edits = await page.locator(SEL["edit_buttons"]).all()
        logger.info(f"[{idsbr}] hasil edit buttons = {len(edits)}")

        if len(edits) == 0:
            logger.warning(f"[{idsbr}] Tidak ada hasil, mencoba lagi…")
            await page.click(SEL["btn_filter"])
            await page.wait_for_timeout(2000)
            await page.wait_for_load_state("networkidle", timeout=5000)
            edits = await page.locator(SEL["edit_buttons"]).all()
            logger.info(f"[{idsbr}] hasil edit buttons setelah coba ulang = {len(edits)}")

        if len(edits) != 1:
            raise Exception(f"IDSBR {idsbr} tidak unik/0 hasil (len={len(edits)})")
    except Exception as e:
        if "Execution context was destroyed" in str(e):
            logger.warning(f"[{idsbr}] Konteks rusak, reload & coba ulang…")
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

    # Tangani swal lat/lng kalau muncul saat open (jangan skip)
    await handle_latlng_error_on_open(page)

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
    status = row.get("status") if isinstance(row, dict) else row["status"]
    nama_sls = to_str(row["nama_sls"])

    await page.fill(SEL["sumber"], to_str(row["sumber_profiling"]))
    await page.fill(SEL["catatan"], to_str(row["catatan_profiling"]))
    await page.fill(SEL["sls"], nama_sls)
    await set_alamat(page, row.get("alamat") if isinstance(row, dict) else row["alamat"])

    # 6) email & phone & website
    await set_email(page, row.get("email") if isinstance(row, dict) else row["email"])
    await set_telepon(page, row.get("nomor_telepon") if isinstance(row, dict) else row["nomor_telepon"])
    await set_whatsapp(page, row.get("nomor_whatsapp") if isinstance(row, dict) else row["nomor_whatsapp"])
    await set_website(page, row.get("website") if isinstance(row, dict) else row["website"])

    # 7) lat/lng (kosongkan dulu → isi jika ada)
    await page.fill(SEL["lat"], ""); await page.fill(SEL["lng"], "")
    lat = row.get("latitude") if isinstance(row, dict) else row["latitude"]
    lng = row.get("longitude") if isinstance(row, dict) else row["longitude"]
    if lat is not None and str(lat).strip(): await page.fill(SEL["lat"], str(lat))
    if lng is not None and str(lng).strip(): await page.fill(SEL["lng"], str(lng))

    # 8) status
    await set_keberadaan_usaha(page, status)

    # 9) wilayah — gunakan kdprov/kdkab/kdkec/kddesa dari database bila ada
    # await set_wilayah(
    #     page,
    #     (row.get("kdprov")  if isinstance(row, dict) else row["kdprov"]),
    #     (row.get("kdkab")   if isinstance(row, dict) else row["kdkab"]),
    #     (row.get("kdkec")   if isinstance(row, dict) else row["kdkec"]),
    #     (row.get("kddesa")  if isinstance(row, dict) else row["kddesa"]),
    # )

    # 9) wilayah – isi dari DB (kdkab/kdkec/kddesa). Jika kosong, fallback ke default.
    kdkab = row.get("kdkab") if isinstance(row, dict) else row["kdkab"]
    kdkec = row.get("kdkec") if isinstance(row, dict) else row["kdkec"]
    kddesa = row.get("kddesa") if isinstance(row, dict) else row["kddesa"]
    await set_wilayah_from_db(page, kdkab, kdkec, kddesa)

    # 10) bentuk badan usaha
    await set_bentuk_badan_usaha(page, row.get("bentuk_badan_usaha") if isinstance(row, dict) else row["bentuk_badan_usaha"])

    # 11) tahun berdiri
    await set_tahun_berdiri(page, row.get("tahun_berdiri") if isinstance(row, dict) else row["tahun_berdiri"])

    # 12) jaringan usaha
    await set_jaringan_usaha(page, row.get("jaringan_usaha") if isinstance(row, dict) else row["jaringan_usaha"])

    # 12b) KBLI/Kegiatan Usaha dari DB (opsional)
    await inject_kbli_row(
        page,
        (row.get("kbli") if isinstance(row, dict) else row["kbli"]),
        (row.get("kategori") if isinstance(row, dict) else row["kategori"]),
        (row.get("deskripsi_kegiatan_usaha") if isinstance(row, dict) else row["deskripsi_kegiatan_usaha"]),
    )

    # 13) cek peta & submit
    logger.info(f"[{idsbr}] step: cek-peta")
    await page.click(SEL["cek_peta"])
    await wait_blockui_gone(page, timeout=25000)

    logger.info(f"[{idsbr}] step: submit")
    await page.click(SEL["submit"])
    await click_if_visible(page, SEL["confirm_consistency"], 2000)
    await click_if_visible(page, SEL["ignore_consistency"], 2000)

    # Jika muncul swal error lat/lng: klik OK dan lanjut submit flow tetap berakhir dengan swal done
    await handle_latlng_error_after_submit(page)

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

        # Stealth patches
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
