# Changelog

Semua perubahan penting pada proyek MatchaMaster akan didokumentasikan dalam file ini.

## [1.1.0] - 2024-01-15

### ✨ Ditambahkan
- **Contoh Data Master**: File `contoh_data_master.csv` dengan 5 contoh data lengkap
- **Template Excel**: File `contoh_data_master.xlsx` sebagai dokumentasi struktur kolom
- **Link Data Master**: Referensi ke https://s.bps.go.id/matchamaster untuk akses data master
- **Dokumentasi Struktur Data**: File `STRUKTUR_DATA.md` dengan penjelasan detail semua kolom
- **Monitoring Dashboard**: Query SQL untuk monitoring progress otomatisasi
- **Troubleshooting Guide**: Panduan lengkap mengatasi masalah umum
- **Security Guidelines**: Panduan keamanan untuk deployment production
- **Best Practices**: Rekomendasi penggunaan untuk skalabilitas

### 📝 Diperbarui
- **README.md**: Struktur dokumentasi yang lebih terorganisir dan komprehensif
- **Struktur Database**: Penjelasan detail kolom sistem dan data usaha
- **Cara Menjalankan**: Panduan step-by-step yang lebih jelas
- **Import Data**: Proses import dengan validasi dan error handling
- **Parameter Debug**: Contoh penggunaan parameter untuk debugging

### 🔧 Diperbaiki
- Duplikasi informasi dalam dokumentasi
- Konsistensi format dan struktur README
- Penjelasan yang lebih jelas untuk setiap fitur

### 🗂️ Struktur File Baru
```
automation/
├── README.md                           # Dokumentasi utama (diperbarui)
├── CHANGELOG.md                        # File ini
└── matchamaster/
    ├── README.md                       # Dokumentasi detail (diperbarui)
    ├── STRUKTUR_DATA.md               # Dokumentasi struktur data (baru)
    ├── contoh_data_master.csv         # Template CSV (baru)
    ├── contoh_data_master.xlsx        # Template Excel (baru)
    ├── .env.example
    ├── .gitignore
    ├── db_async.py
    ├── worker.py
    ├── debug_single.py
    ├── record_login.py
    ├── tidy.py
    └── Import to DB/
        ├── import_excel_to_postgres.py
        └── find_duplicates.py
```

## [1.0.0] - 2024-01-01

### ✨ Rilis Awal
- Otomatisasi pengisian form Direktori Usaha BPS
- Multi-worker support dengan PostgreSQL
- Browser automation menggunakan Playwright
- Import data dari Excel ke database
- Deteksi dan handling duplikat data
- Session management dan retry logic
- Logging komprehensif
- Mode debug untuk single record

---

**Format Changelog**
- ✨ Ditambahkan: Fitur baru
- 📝 Diperbarui: Perubahan pada fitur yang ada
- 🔧 Diperbaiki: Bug fixes
- 🗑️ Dihapus: Fitur yang dihapus
- 🔒 Keamanan: Perbaikan keamanan