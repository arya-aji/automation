import os
import math
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

PGHOST = os.getenv("PGHOST")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")
PGPORT = os.getenv("PGPORT", "5432")
PGSSLMODE = os.getenv("PGSSLMODE", "require")

EXCEL_PATH = os.getenv("EXCEL_PATH", "master.xlsx")
SHEET_NAME = os.getenv("SHEET_NAME", None)  # None = sheet aktif
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))

conn_kwargs = {
    "host": PGHOST,
    "dbname": PGDATABASE,
    "user": PGUSER,
    "password": PGPASSWORD,
    "port": PGPORT,
    "sslmode": PGSSLMODE,
}

# Mapping header Excel -> kolom tabel
# Sesuaikan kalau judul kolom Excel kamu sedikit berbeda
COLUMN_MAP = {
    "Tahap": "tahap",
    "proses": "proses",
    "idsbr": "idsbr",
    "nama_usaha": "nama_usaha",
    "nama_komersial_usaha": "nama_komersial_usaha",
    "alamat": "alamat",
    "nama_sls": "nama_sls",
    "kodepos": "kodepos",
    "nomor_telepon": "nomor_telepon",
    "nomor_whatsapp": "nomor_whatsapp",
    "email": "email",
    "website": "website",
    "latitude": "latitude",
    "longitude": "longitude",
    "status": "status",
    "kdprov": "kdprov",
    "kdkab": "kdkab",
    "kdkec": "kdkec",
    "kddesa": "kddesa",
    "jenis_kepemilikan_usaha": "jenis_kepemilikan_usaha",
    "bentuk_badan_usaha": "bentuk_badan_usaha",
    "deskripsi_badan_usaha_lainnya": "deskripsi_badan_usaha_lainnya",
    "tahun_berdiri": "tahun_berdiri",
    "jaringan_usaha": "jaringan_usaha",
    "sektor_institusi": "sektor_institusi",
    "deskripsi_kegiatan_usaha": "deskripsi_kegiatan_usaha",
    "kategori": "kategori",
    "kbli": "kbli",
    "produk_usaha": "produk_usaha",
    "sumber_profiling": "sumber_profiling",
    "catatan_profiling": "catatan_profiling",
}

TARGET_COLUMNS = list(COLUMN_MAP.values())

def to_float_or_none(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    if s == "" or s.lower() in ("nan", "none", "null"):
        return None
    try:
        return float(s)
    except:
        return None

def clean_str(x):
    if x is None:
        return None
    # pandas baca NaN sebagai float nan
    if isinstance(x, float) and math.isnan(x):
        return None
    s = str(x).strip()
    return s if s != "" else None

def read_excel(path, sheet_name=None):
    df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)
    # Normalisasi header agar pas ke COLUMN_MAP (lowercase, underscore)
    df.columns = [c.strip() for c in df.columns]
    return df

def normalize_and_select(df):
    # Ganti nama kolom Excel -> nama kolom tabel
    rename_map = {}
    for excel_col, pg_col in COLUMN_MAP.items():
        # toleransi: jika Excel pakai kapitalisasi beda
        for c in df.columns:
            if c.lower() == excel_col.lower():
                rename_map[c] = pg_col
                break

    df = df.rename(columns=rename_map)

    # Pastikan semua kolom target ada
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Pilih kolom sesuai urutan target
    df = df[TARGET_COLUMNS].copy()

    # Bersihkan string
    str_cols = [c for c in TARGET_COLUMNS if c not in ("latitude", "longitude", "tahap")]
    for c in str_cols:
        df[c] = df[c].map(clean_str)

    # khusus numeric/float
    df["latitude"] = df["latitude"].map(to_float_or_none)
    df["longitude"] = df["longitude"].map(to_float_or_none)

    # tahap ke int jika ada
    def to_int_or_none(x):
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        try:
            return int(float(s))
        except:
            return None
    df["tahap"] = df["tahap"].map(to_int_or_none)

    # idsbr wajib ada
    missing_idsbr = df["idsbr"].isna().sum()
    if missing_idsbr > 0:
        print(f"⚠️ Peringatan: {missing_idsbr} baris tanpa idsbr akan dilewati.")
        df = df[~df["idsbr"].isna()]

    return df

def upsert_rows(conn, rows):
    """
    rows: list of tuples in TARGET_COLUMNS order
    UPSERT by (idsbr)
    """
    with conn.cursor() as cur:
        insert_cols = ", ".join(TARGET_COLUMNS)
        placeholders = "(" + ", ".join(["%s"] * len(TARGET_COLUMNS)) + ")"

        # kolom di-update saat konflik (kecuali idsbr sebagai kunci unik)
        update_cols = [c for c in TARGET_COLUMNS if c != "idsbr"]
        set_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])

        sql = f"""
            INSERT INTO direktori_ids ({insert_cols})
            VALUES %s
            ON CONFLICT (idsbr) DO UPDATE SET
            {set_clause},
            last_updated = CURRENT_TIMESTAMP
        """
        execute_values(cur, sql, rows, template=placeholders)
    conn.commit()

def main():
    print("📥 Membaca Excel...")
    df = read_excel(EXCEL_PATH, sheet_name=SHEET_NAME)
    print(f"   Total baris di Excel: {len(df)}")

    print("🧼 Normalisasi kolom & data...")
    df = normalize_and_select(df)
    print(f"   Siap diimpor: {len(df)} baris")

    if len(df) == 0:
        print("⛔ Tidak ada data yang bisa diimpor.")
        return

    print("🔌 Koneksi ke PostgreSQL (NeonDB)...")
    conn = psycopg2.connect(**conn_kwargs)
    try:
        total = len(df)
        batches = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
        for i in range(batches):
            start = i * CHUNK_SIZE
            end = min((i + 1) * CHUNK_SIZE, total)
            chunk = df.iloc[start:end]

            # Konversi tuple sesuai urutan
            # Hapus duplikasi idsbr dalam satu batch untuk menghindari CardinalityViolation
            seen_idsbr = set()
            rows = []
            for _, r in chunk.iterrows():
                idsbr = r['idsbr']
                if idsbr not in seen_idsbr:
                    seen_idsbr.add(idsbr)
                    rows.append(tuple(r[c] for c in TARGET_COLUMNS))
                else:
                    print(f"⚠️ Melewati duplikat idsbr: {idsbr} dalam batch yang sama")

            print(f"⬆️  Import batch {i+1}/{batches} (rows {start+1}..{end})...")
            upsert_rows(conn, rows)

        print("✅ Selesai import/upssert ke direktori_ids.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
