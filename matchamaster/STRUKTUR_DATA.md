# Struktur Data MatchaMaster

Dokumen ini menjelaskan struktur data lengkap yang digunakan dalam sistem MatchaMaster untuk otomatisasi Direktori Usaha BPS.

## 📋 Tabel Database: `direktori_ids`

### Kolom Sistem (Otomatis)

| Kolom | Tipe | Deskripsi | Contoh |
|-------|------|-----------|--------|
| `id` | INTEGER | Primary Key, auto increment | 1, 2, 3, ... |
| `automation_status` | VARCHAR | Status otomatisasi | 'new', 'in_progress', 'done', 'failed' |
| `assigned_to` | VARCHAR | Nama worker yang memproses | 'pc-jakarta-01', 'server-prod' |
| `attempt_count` | INTEGER | Jumlah percobaan | 0, 1, 2, ... |
| `first_taken_at` | TIMESTAMP | Waktu pertama kali diambil worker | 2024-01-15 10:30:00 |
| `last_updated` | TIMESTAMP | Waktu terakhir diupdate | 2024-01-15 11:45:30 |
| `error` | TEXT | Pesan error (jika ada) | 'Timeout error', 'Form locked' |

### Kolom Data Usaha (Input)

#### Identifikasi Usaha
| Kolom | Tipe | Wajib | Deskripsi | Contoh |
|-------|------|-------|-----------|--------|
| `tahap` | INTEGER | Ya | Tahap profiling | 1, 2, 3 |
| `proses` | VARCHAR | Ya | Jenis proses | 'Profiling', 'Update', 'Verifikasi' |
| `idsbr` | VARCHAR(16) | Ya | ID SBR usaha (16 digit) | '1234567890123456' |
| `nama_usaha` | VARCHAR | Ya | Nama resmi usaha | 'PT Maju Bersama Sejahtera' |
| `nama_komersial_usaha` | VARCHAR | Tidak | Nama dagang/komersial | 'Toko Elektronik Maju' |

#### Informasi Kontak
| Kolom | Tipe | Wajib | Deskripsi | Contoh |
|-------|------|-------|-----------|--------|
| `alamat` | TEXT | Ya | Alamat lengkap usaha | 'Jl. Sudirman No. 45, Jakarta Pusat' |
| `nama_sls` | VARCHAR | Tidak | Nama SLS (Satuan Lingkungan Setempat) | 'SLS Jakarta Pusat 001' |
| `kodepos` | VARCHAR(5) | Tidak | Kode pos | '10220' |
| `nomor_telepon` | VARCHAR | Tidak | Nomor telepon | '021-5551234' |
| `nomor_whatsapp` | VARCHAR | Tidak | Nomor WhatsApp | '08123456789' |
| `email` | VARCHAR | Tidak | Alamat email | 'info@majubersama.com' |
| `website` | VARCHAR | Tidak | Website usaha | 'www.majubersama.com' |

#### Koordinat Geografis
| Kolom | Tipe | Wajib | Deskripsi | Contoh |
|-------|------|-------|-----------|--------|
| `latitude` | DECIMAL | Tidak | Koordinat lintang | -6.2088 |
| `longitude` | DECIMAL | Tidak | Koordinat bujur | 106.8456 |
| `status` | VARCHAR | Ya | Status usaha | 'Aktif', 'Tidak Aktif', 'Tutup' |

#### Wilayah Administratif
| Kolom | Tipe | Wajib | Deskripsi | Contoh |
|-------|------|-------|-----------|--------|
| `kdprov` | VARCHAR(2) | Ya | Kode provinsi | '31' (DKI Jakarta) |
| `kdkab` | VARCHAR(4) | Ya | Kode kabupaten/kota | '3171' (Jakarta Selatan) |
| `kdkec` | VARCHAR(6) | Ya | Kode kecamatan | '317101' (Tebet) |
| `kddesa` | VARCHAR(10) | Ya | Kode desa/kelurahan | '3171011001' (Tebet Timur) |

#### Karakteristik Usaha
| Kolom | Tipe | Wajib | Deskripsi | Contoh |
|-------|------|-------|-----------|--------|
| `jenis_kepemilikan_usaha` | VARCHAR | Ya | Jenis kepemilikan | 'Swasta', 'BUMN', 'BUMD', 'Koperasi' |
| `bentuk_badan_usaha` | VARCHAR | Ya | Bentuk badan usaha | 'PT', 'CV', 'UD', 'Koperasi', 'Yayasan' |
| `deskripsi_badan_usaha_lainnya` | TEXT | Tidak | Deskripsi tambahan | 'Perusahaan asing PMA' |
| `tahun_berdiri` | INTEGER | Tidak | Tahun berdiri usaha | 2015 |
| `jaringan_usaha` | VARCHAR | Tidak | Jenis jaringan usaha | 'Tunggal', 'Cabang', 'Franchise' |
| `sektor_institusi` | VARCHAR | Ya | Sektor institusi | 'Swasta', 'Pemerintah', 'Koperasi' |

#### Kegiatan Ekonomi
| Kolom | Tipe | Wajib | Deskripsi | Contoh |
|-------|------|-------|-----------|--------|
| `deskripsi_kegiatan_usaha` | TEXT | Ya | Deskripsi kegiatan utama | 'Perdagangan eceran alat elektronik' |
| `kategori` | VARCHAR(1) | Ya | Kategori KBLI (huruf) | 'G' (Perdagangan) |
| `kbli` | VARCHAR(5) | Ya | Kode KBLI 5 digit | '47421' |
| `produk_usaha` | TEXT | Ya | Produk/jasa yang dihasilkan | 'Elektronik konsumen, smartphone' |

#### Metadata Profiling
| Kolom | Tipe | Wajib | Deskripsi | Contoh |
|-------|------|-------|-----------|--------|
| `sumber_profiling` | VARCHAR | Ya | Sumber data profiling | 'Survei lapangan', 'Data sekunder' |
| `catatan_profiling` | TEXT | Tidak | Catatan tambahan | 'Usaha aktif dengan omzet stabil' |

## 🔍 Validasi Data

### ⚠️ Persyaratan Data Sebelum Import
**PENTING**: Data master harus memenuhi kriteria berikut:
- ✅ **Tidak ada missing data** - Semua field wajib terisi lengkap
- ✅ **Data sudah clean** - Bebas dari karakter aneh, format konsisten
- ✅ **Validasi manual** - Periksa keakuratan sebelum import
- ✅ **Backup tersedia** - Simpan salinan data asli

### Aturan Validasi
1. **IDSBR**: Harus 16 digit numerik, unik
2. **Kode Wilayah**: Harus sesuai dengan hierarki BPS (provinsi → kabupaten → kecamatan → desa)
3. **KBLI**: Harus 5 digit, sesuai dengan KBLI 2020
4. **Koordinat**: Latitude (-90 to 90), Longitude (-180 to 180)
5. **Email**: Format email yang valid
6. **Website**: Format URL yang valid (jika diisi)
7. **Tahun Berdiri**: Tidak boleh lebih dari tahun sekarang

### Status Otomatisasi
- `new`: Data baru, belum diproses
- `in_progress`: Sedang diproses oleh worker
- `done`: Berhasil diproses
- `failed`: Gagal diproses (error)

## 📝 Catatan Implementasi

### Import Data
- Gunakan script `import_excel_to_postgres.py` untuk import dari Excel/CSV
- Pastikan mapping kolom sesuai dengan `COLUMN_MAP`
- Data akan otomatis mendapat status `new` setelah import

### Processing
- Worker akan mengambil data dengan status `new` secara atomik
- Status berubah menjadi `in_progress` saat diproses
- Setelah selesai, status menjadi `done` atau `failed`
- Retry otomatis untuk data yang gagal (maksimal attempt)

### Monitoring
- Gunakan query SQL untuk monitoring progress
- Log tersimpan per worker dengan timestamp
- Error message tersimpan di kolom `error` untuk debugging