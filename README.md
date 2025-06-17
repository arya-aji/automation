# 🛠️ Python Automation Script

Script ini dibuat untuk membantu mengotomatisasi pekerjaan berulang yang memakan waktu, khususnya dalam lingkungan kerja yang penuh dengan tugas-tugas membangun negara.

# 📊 Otomatisasi Entri Data Profil Usaha BPS dengan Selenium

Skrip ini digunakan untuk mengotomatisasi proses pengisian form pada situs [Direktori Usaha BPS (Matchapro)](https://matchapro.web.bps.go.id/direktori-usaha), berdasarkan data dari file Excel (`usaha.xlsx`).
Fungsi utama skrip ini:

- Membaca data IDSBR dan atribut terkait dari Excel
- Mencari entri yang sesuai di Matchapro
- Mengisi form alamat, sumber, catatan, koordinat, dll.
- Melakukan submit otomatis hingga konfirmasi "Berhasil submit data final!" muncul
- Menandai baris yang berhasil diproses (dengan font bold dan label "USER")

---

## 🧰 Requirement

### ✅ Sistem Operasi

- Windows 10/11 (wajib karena menggunakan Chrome Profile)

### ✅ Python

- Python 3.8 atau lebih tinggi (disarankan versi 3.11)

### ✅ Chrome & ChromeDriver

- Google Chrome versi terbaru
- ChromeDriver **versi sama dengan Chrome**  
  👉 [Download ChromeDriver](https://chromedriver.chromium.org/downloads)

### 🔧 Cara Menambahkan ChromeDriver ke PATH (Windows):

1. Download ChromeDriver ZIP dari link di atas.
2. Ekstrak `chromedriver.exe` ke folder (misal: `C:\Tools\chromedriver`)
3. Tambahkan folder tersebut ke PATH:
   - Buka **Control Panel → System → Advanced system settings**
   - Klik **Environment Variables**
   - Pilih **Path** → klik **Edit** → klik **New**
   - Masukkan `C:\Tools\chromedriver`
   - Klik OK, lalu restart terminal/PC bila perlu

---

## 📦 Dependency Python

Install semua dependensi berikut:

```bash
pip install selenium pandas openpyxl
```

---

## 📁 Struktur File

- `usaha.xlsx` → file sumber data IDSBR dan informasi usaha
- `script.py` → file Python otomatisasi (isi sesuai skrip Anda)

---

## ▶️ Cara Menjalankan

1. Pastikan sudah login ke Chrome sebelumnya dan tersimpan dalam profil lokal.
2. Jalankan skrip ini dengan:

```bash
python script.py
```

3. Skrip akan membuka halaman [matchapro.web.bps.go.id](https://matchapro.web.bps.go.id/direktori-usaha), mencari IDSBR, mengisi data dari Excel, dan klik submit otomatis.

---

## ⚠️ Catatan Penting

- Gunakan profil Chrome yang **sudah login dan memiliki hak akses Matchapro**. Letak profil default ada di:
  ```
  C:\Users\NAMA_USER\AppData\Local\Google\Chrome\User Data
  ```
- Ubah `--user-data-dir` di dalam kode ke lokasi yang sesuai jika diperlukan:

  ```python
  options.add_argument("--user-data-dir=C:\\Shared\\Coding\\script\\bot_profil")
  ```

- Kolom `X` pada Excel akan otomatis diisi "Aji" dan dibold jika berhasil.
- Jika modal konfirmasi atau form tidak bisa diakses, skrip akan melakukan retry otomatis hingga 3x.

---

## 🧪 Fitur Cerdas

- Deteksi jika form sudah diedit oleh orang lain
- Deteksi form tidak dapat diedit (misalnya tombol tidak tersedia)
- Reload otomatis jika elemen form tidak bisa diinteraksikan

---

## ❓ Troubleshooting

| Masalah                                 | Solusi                                                                |
| --------------------------------------- | --------------------------------------------------------------------- |
| Chrome terbuka tapi tidak login         | Periksa `--user-data-dir` arahkan ke folder Chrome Profile yang benar |
| Error `chromedriver not found`          | Tambahkan folder ChromeDriver ke `PATH`                               |
| Form tidak bisa diklik atau input gagal | Pastikan koneksi stabil, tunggu loading selesai sebelum klik/input    |
| Gagal klik tombol akhir "Ya, Submit!"   | Periksa apakah pop-up SweetAlert muncul dengan benar                  |

---

## 👨‍💻 Author

Dibuat untuk keperluan internal BPS oleh tim integrasi pengolahan dan diseminasi statistik.
