# MatchaMaster - Otomatisasi Direktori Usaha BPS

MatchaMaster adalah skrip otomatisasi berbasis Python untuk mengisi dan memperbarui data pada platform [Direktori Usaha BPS (MatchaPro)](https://matchapro.web.bps.go.id/direktori-usaha) secara efisien dan akurat. Proyek ini menggunakan Playwright untuk otomatisasi browser dan PostgreSQL untuk penyimpanan data.

## 🚀 Fitur Utama

- Otomatisasi pengisian form data usaha pada platform MatchaPro
- Dukungan multi-worker untuk pemrosesan paralel
- Penanganan kesalahan dan retry otomatis
- Deteksi form yang sedang diedit oleh pengguna lain
- Pencatatan log komprehensif
- Dukungan mode headless untuk server

## 📋 Persyaratan

### Sistem
- Python 3.8 atau lebih tinggi
- PostgreSQL database (lokal atau cloud seperti Neon)

### Dependensi Python
```bash
pip install playwright asyncpg tenacity loguru python-dotenv rapidfuzz
python -m playwright install chromium
```

## ⚙️ Konfigurasi

Buat file `.env` berdasarkan `.env.example` dengan konfigurasi berikut:

```
# Database PostgreSQL
PGHOST=host_database_anda
PGDATABASE=nama_database_anda
PGUSER=user_database_anda
PGPASSWORD=password_database_anda
PGSSLMODE=require
PGCHANNELBINDING=require

# Konfigurasi Aplikasi
BASE_URL=https://matchapro.web.bps.go.id/direktori-usaha
STORAGE_STATE=storage_state.json   # file cookie/session login
NUM_WORKERS=8                      # jumlah worker per PC
WORKER_NAME=pc-nama-anda           # identifikasi PC
HEADLESS=true                      # true untuk server
TIMEOUT_MS=60000                   # timeout dalam milidetik

# Kredensial Login (opsional)
LOGIN_USERNAME=username_anda
LOGIN_PASSWORD=password_anda
```

## 🗄️ Struktur Database

Aplikasi menggunakan tabel `direktori_ids` dengan struktur berikut:
- `id`: ID unik
- `idsbr`: ID SBR usaha
- `automation_status`: Status otomatisasi ('new', 'in_progress', 'done', dll)
- `assigned_to`: Worker yang sedang memproses
- `attempt_count`: Jumlah percobaan
- Dan kolom lain untuk data usaha

## 🚦 Cara Menjalankan

### Mode Normal (Multi-worker)

```bash
python worker.py
```

Ini akan menjalankan sejumlah worker sesuai konfigurasi `NUM_WORKERS` di file `.env`.

### Mode Debug (Single IDSBR)

```bash
python worker.py --debug-idsbr=123456789
```

Parameter tambahan:
- `--slowmo=200`: Delay antar aksi dalam milidetik (default: 200)
- `--devtools`: Buka DevTools browser saat debug

## 🔍 Troubleshooting

- **Error Koneksi Database**: Pastikan kredensial database benar dan database dapat diakses
- **Browser Tidak Terbuka**: Pastikan Playwright terinstal dengan benar (`python -m playwright install chromium`)
- **Form Terkunci**: Aplikasi akan mendeteksi jika form sedang diedit oleh pengguna lain dan melewatinya

## 📝 Catatan

- File `storage_state.json` menyimpan sesi login browser. Jika sesi kedaluwarsa, hapus file ini dan jalankan ulang aplikasi
- Mode headless (`HEADLESS=true`) cocok untuk server tanpa GUI
- Gunakan `WORKER_NAME` yang unik untuk setiap PC jika menjalankan di beberapa komputer