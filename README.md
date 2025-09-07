# MatchaMaster - Otomatisasi Direktori Usaha BPS

🤖 **Sistem otomatisasi untuk pengisian data direktori usaha BPS menggunakan Python dan Playwright**

## ⚠️ Pemberitahuan Penting

**DISCLAIMER**: Aplikasi ini hanya berfungsi sebagai **alat bantu otomatisasi entri data** dan **pengganti tenaga manusia** untuk proses input. 

- 📊 **Sumber data dan validitas data tetap menjadi tanggung jawab penuh tim pengumpulan data**
- 🔍 **Tim pengumpulan data wajib memverifikasi keakuratan data sebelum dan sesudah proses otomatisasi**
- 📋 **Aplikasi tidak bertanggung jawab atas kesalahan data yang berasal dari sumber data master**
- ✅ **Pastikan data master sudah divalidasi dan disetujui oleh supervisor sebelum menggunakan aplikasi ini**

MatchaMaster adalah skrip otomatisasi berbasis Python untuk mengisi dan memperbarui data pada platform [Direktori Usaha BPS (MatchaPro)](https://matchapro.web.bps.go.id/direktori-usaha) secara efisien dan akurat. Proyek ini menggunakan Playwright untuk otomatisasi browser dan PostgreSQL untuk penyimpanan data.

## 📊 Data Master

Data master untuk otomatisasi dapat diakses melalui [Google Spreadsheet MatchaMaster](https://s.bps.go.id/matchamaster). Data ini berisi informasi lengkap usaha yang akan diproses oleh sistem otomatisasi.


## 🚀 Panduan Lengkap untuk Pengguna Awam

### Tahap 1: Persiapan Database (NEON PostgreSQL)
1. **Daftar akun NEON Database**
   - Kunjungi [neon.tech](https://neon.tech) dan buat akun gratis
   - Buat database baru dengan nama `matchamaster_db`
   - Catat connection string yang diberikan

2. **Setup Environment Variables**
   - Copy file `.env.example` menjadi `.env`
   - Isi connection string NEON ke dalam file `.env`

### Tahap 2: Persiapan Data Master
1. **Download template data**
   - Gunakan file `contoh_data_master.csv` atau `contoh_data_master.xlsx`
   - Isi data sesuai format yang telah ditentukan

2. **🔍 Deteksi Duplikat Data (WAJIB)**
   ```bash
   cd "Import to DB"
   python find_duplicates.py
   ```
   - **Jalankan ini PERTAMA** untuk menjaring data master yang duplikat
   - Perbaiki semua duplikat sebelum melanjutkan

### Tahap 3: Import Data ke Database
1. **Install dependencies Python**
   ```bash
   # Dari root folder automation
   pip install -r requirements.txt
   
   # Atau dari folder matchamaster
   cd matchamaster
   pip install -r requirements.txt
   ```

2. **Import data master**
   ```bash
   cd matchamaster
   cd "Import to DB"
   python import_excel_to_postgres.py
   ```

### Tahap 4: Setup Browser Automation
1. **Install Playwright**
   ```bash
   pip install playwright
   playwright install chromium
   ```

2. **Simpan login state**
   ```bash
   python record_login.py
   ```

### Tahap 5: Menjalankan Otomatisasi
1. **Mode normal**
   ```bash
   python worker.py
   ```

2. **Mode debug (untuk testing)**
   ```bash
   python debug_single.py --headless=false
   ```

---

##  Fitur Utama

- Otomatisasi pengisian form data usaha pada platform MatchaPro
- Dukungan multi-worker untuk pemrosesan paralel
- Penanganan kesalahan dan retry otomatis
- Deteksi form yang sedang diedit oleh pengguna lain
- Pencatatan log komprehensif
- Dukungan mode headless untuk server
- Import data master dari Excel ke PostgreSQL
- Deteksi dan penanganan data duplikat
- Tools debugging dan monitoring

## 🏗️ Arsitektur Sistem

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Excel/CSV     │───▶│   PostgreSQL     │───▶│   MatchaPro     │
│   Data Master   │    │   Database       │    │   Platform      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │                         ▲
                              ▼                         │
                       ┌──────────────────┐            │
                       │   Multi-Worker   │────────────┘
                       │   Automation     │
                       └──────────────────┘
```

### Workflow Otomatisasi

1. **Import Data**: Data master dari Excel/Google Sheets diimpor ke PostgreSQL
2. **Worker Assignment**: Setiap worker mengambil record dengan status 'new'
3. **Browser Automation**: Worker menggunakan Playwright untuk mengisi form
4. **Status Update**: Status record diperbarui sesuai hasil pemrosesan
5. **Error Handling**: Record dengan error akan di-retry sesuai konfigurasi
6. **Monitoring**: Log dan status dapat dipantau secara real-time

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

## 📊 Contoh Data Master

Untuk melihat contoh struktur data yang diperlukan, silakan kunjungi:
**[https://s.bps.go.id/matchamaster](https://s.bps.go.id/matchamaster)**

Atau lihat file contoh di folder `matchamaster/`:
- [`contoh_data_master.csv`](matchamaster/contoh_data_master.csv) - Template CSV dengan 5 contoh data lengkap
- [`contoh_data_master.xlsx`](matchamaster/contoh_data_master.xlsx) - Template Excel (dokumentasi struktur kolom)
- [`STRUKTUR_DATA.md`](matchamaster/STRUKTUR_DATA.md) - Dokumentasi detail struktur database

## 🗄️ Struktur Database

Aplikasi menggunakan tabel `direktori_ids` dengan struktur berikut:

### Kolom Sistem
- `id`: ID unik (Primary Key)
- `idsbr`: ID SBR usaha (16 digit)
- `automation_status`: Status otomatisasi ('new', 'in_progress', 'done', 'failed')
- `assigned_to`: Worker yang sedang memproses
- `attempt_count`: Jumlah percobaan
- `first_taken_at`: Waktu pertama kali diambil worker
- `last_updated`: Waktu terakhir diupdate
- `error`: Pesan error (jika ada)

### Kolom Data Usaha
- `tahap`: Tahap profiling
- `proses`: Jenis proses
- `nama_usaha`: Nama resmi usaha
- `nama_komersial_usaha`: Nama dagang/komersial
- `alamat`: Alamat lengkap usaha
- `nama_sls`: Nama SLS (Satuan Lingkungan Setempat)
- `kodepos`: Kode pos
- `nomor_telepon`: Nomor telepon
- `nomor_whatsapp`: Nomor WhatsApp
- `email`: Alamat email
- `website`: Website usaha
- `latitude`, `longitude`: Koordinat geografis
- `status`: Status usaha
- `kdprov`, `kdkab`, `kdkec`, `kddesa`: Kode wilayah administratif
- `jenis_kepemilikan_usaha`: Jenis kepemilikan
- `bentuk_badan_usaha`: Bentuk badan usaha
- `deskripsi_badan_usaha_lainnya`: Deskripsi tambahan
- `tahun_berdiri`: Tahun berdiri usaha
- `jaringan_usaha`: Jenis jaringan usaha
- `sektor_institusi`: Sektor institusi
- `deskripsi_kegiatan_usaha`: Deskripsi kegiatan utama
- `kategori`: Kategori KBLI
- `kbli`: Kode KBLI (5 digit)
- `produk_usaha`: Produk/jasa yang dihasilkan
- `sumber_profiling`: Sumber data profiling
- `catatan_profiling`: Catatan tambahan

## 📥 Import Data Master

### ⚠️ Persyaratan Data
**PENTING**: Data master harus memenuhi kriteria berikut:
- ✅ **Tidak ada missing data** - Semua field wajib terisi lengkap
- ✅ **Data sudah clean** - Bebas dari karakter aneh, format konsisten
- ✅ **Validasi manual** - Periksa keakuratan sebelum import
- ✅ **Backup tersedia** - Simpan salinan data asli

### 🔄 Proses Import (Ikuti Urutan)

**LANGKAH 1: Deteksi Duplikat (WAJIB PERTAMA)**
```bash
cd "Import to DB"
python find_duplicates.py
```
> ⚠️ **PENTING**: Jalankan ini SEBELUM import untuk menjaring data duplikat

**LANGKAH 2: Persiapan Data**
- Gunakan template `contoh_data_master.csv` atau `contoh_data_master.xlsx`
- Perbaiki semua duplikat yang ditemukan di langkah 1
- Pastikan struktur kolom sesuai dengan mapping di `COLUMN_MAP`
- Data harus dalam format Excel (.xlsx) atau CSV

**LANGKAH 3: Konfigurasi Environment**
Tambahkan konfigurasi berikut ke file `.env`:

```
# Konfigurasi Import Excel
EXCEL_PATH=master.xlsx          # path file Excel
SHEET_NAME=Sheet1               # nama sheet (kosongkan untuk sheet aktif)
CHUNK_SIZE=1000                 # ukuran batch import
```

**LANGKAH 4: Import ke Database**
```bash
# Pastikan sudah install dependencies
cd matchamaster
pip install -r requirements.txt

# Import data
cd "Import to DB"
python import_excel_to_postgres.py
```

**LANGKAH 5: Validasi Final**
```bash
# Verifikasi data berhasil diimport
python find_duplicates.py
```

## 🚦 Cara Menjalankan

### Persiapan Awal
1. Pastikan semua dependensi sudah terinstall
2. Konfigurasi file `.env` sudah benar
3. Database PostgreSQL sudah tersedia dan dapat diakses
4. Data master sudah diimport ke database

### Mode Normal (Multi-worker)
```bash
cd matchamaster
python worker.py
```
Ini akan menjalankan sejumlah worker sesuai konfigurasi `NUM_WORKERS` di file `.env`.

### Mode Debug (Single IDSBR)
```bash
cd matchamaster
python worker.py --debug-idsbr=123456789
```

### Parameter Debug Tambahan
- `--slowmo=200`: Delay antar aksi dalam milidetik (default: 200)
- `--devtools`: Buka DevTools browser saat debug
- `--headless=false`: Jalankan browser dalam mode visible

### Contoh Penggunaan Debug
```bash
# Debug dengan browser visible dan slowmo
python worker.py --debug-idsbr=1234567890123456 --slowmo=500 --devtools

# Debug dengan multiple parameter
python worker.py --debug-idsbr=1234567890123456 --slowmo=1000 --headless=false
```

### Deteksi Duplikat

```bash
cd "matchamaster/Import to DB"
python find_duplicates.py
```

## 📊 Monitoring dan Logging

### Status Database
Untuk memonitor progress otomatisasi, gunakan query berikut:
```sql
-- Status keseluruhan
SELECT automation_status, COUNT(*) as jumlah 
FROM direktori_ids 
GROUP BY automation_status;

-- Worker aktif
SELECT assigned_to, COUNT(*) as sedang_diproses 
FROM direktori_ids 
WHERE automation_status = 'in_progress' 
GROUP BY assigned_to;

-- Progress harian
SELECT DATE(last_updated) as tanggal, 
       automation_status, 
       COUNT(*) as jumlah
FROM direktori_ids 
WHERE last_updated >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(last_updated), automation_status
ORDER BY tanggal DESC;
```

### Log Files
- Log aplikasi tersimpan dengan format timestamp
- Setiap worker memiliki log terpisah dengan identifier `WORKER_NAME`
- Log level dapat diatur melalui environment variable

## 🔍 Troubleshooting

### Masalah Database
- **Error Koneksi Database**: 
  - Pastikan kredensial database benar di file `.env`
  - Cek koneksi internet dan firewall
  - Verifikasi SSL mode sesuai requirement database
- **Import Excel Gagal**: Periksa format kolom Excel sesuai dengan mapping yang ditentukan
- **Duplikasi Data**: Gunakan script `find_duplicates.py` untuk mendeteksi dan menangani data duplikat

### Masalah Browser
- **Browser Tidak Terbuka**: 
  - Install Playwright: `python -m playwright install chromium`
  - Cek permission dan antivirus yang mungkin memblokir
  - Untuk server, pastikan `HEADLESS=true`

### Masalah Aplikasi
- **Form Terkunci**: Aplikasi akan mendeteksi jika form sedang diedit pengguna lain dan skip otomatis
- **Session Expired**: Hapus file `storage_state.json` dan login ulang
- **Worker Stuck**: Restart worker, status 'in_progress' akan otomatis reset ke 'new' setelah timeout
- **Data Duplikat**: Jalankan `find_duplicates.py` untuk identifikasi dan cleanup

### Performance Issues
- **Terlalu Lambat**: Kurangi `NUM_WORKERS` atau tambah `--slowmo`
- **Memory Tinggi**: Restart worker secara berkala atau kurangi `NUM_WORKERS`
- **Network Timeout**: Tingkatkan `TIMEOUT_MS` di `.env`

## 📝 Catatan Penting

### Keamanan
- **Jangan commit file `.env`** ke repository (sudah ada di `.gitignore`)
- File `storage_state.json` berisi session cookies - jaga kerahasiaan
- Gunakan kredensial database yang aman dan rotasi password secara berkala
- Untuk production, gunakan environment variables alih-alih file `.env`

### Best Practices
- **Session Management**: File `storage_state.json` menyimpan sesi login browser. Jika sesi kedaluwarsa, hapus file ini dan login ulang
- **Server Deployment**: Mode headless (`HEADLESS=true`) cocok untuk server tanpa GUI
- **Multi-PC Setup**: Gunakan `WORKER_NAME` yang unik untuk setiap PC/server
- **Resource Management**: Monitor penggunaan CPU dan memory, sesuaikan `NUM_WORKERS`
- **Data Backup**: Backup database secara berkala sebelum menjalankan batch besar

### Skalabilitas
- Untuk volume data besar (>10K records), pertimbangkan:
  - Menjalankan di multiple server dengan `WORKER_NAME` berbeda
  - Menggunakan database connection pooling
  - Monitoring progress dengan dashboard
  - Implementasi queue management untuk retry logic

## 🤝 Kontribusi

Untuk berkontribusi pada proyek ini:
1. Fork repository
2. Buat branch feature (`git checkout -b feature/AmazingFeature`)
3. Commit perubahan (`git commit -m 'Add some AmazingFeature'`)
4. Push ke branch (`git push origin feature/AmazingFeature`)
5. Buat Pull Request

## 📄 Lisensi

Proyek ini menggunakan lisensi MIT. Lihat file `LICENSE` untuk detail lengkap.

## 📚 Dokumentasi Tambahan

- [`CHANGELOG.md`](CHANGELOG.md) - Riwayat perubahan dan update
- [`matchamaster/STRUKTUR_DATA.md`](matchamaster/STRUKTUR_DATA.md) - Detail struktur database dan validasi
- [`matchamaster/contoh_data_master.csv`](matchamaster/contoh_data_master.csv) - Template data dengan contoh
- [Data Master Online](https://s.bps.go.id/matchamaster) - Akses data master terbaru

## 📞 Dukungan

Jika mengalami masalah atau membutuhkan bantuan:
- Buat issue di GitHub repository
- Sertakan log error dan konfigurasi (tanpa kredensial sensitif)
- Jelaskan langkah reproduksi masalah

---

**MatchaMaster** - Otomatisasi Direktori Usaha BPS dengan Python & Playwright  
*Dikembangkan untuk meningkatkan efisiensi pengisian data direktori usaha BPS*
