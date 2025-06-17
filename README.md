# 🛠️ Python Automation Script

Script ini dibuat untuk membantu mengotomatisasi pekerjaan berulang yang memakan waktu, khususnya dalam lingkungan kerja yang penuh dengan tugas-tugas administratif atau data entry.

## 📦 Fitur

- Otomatisasi input data dari file Excel ke form web
- Penanganan elemen form kompleks (dropdown, checkbox, input teks)
- Logging aktivitas otomatis
- Konfigurasi mudah, cocok untuk berbagai use case

## 🚀 Cara Penggunaan

1. Pastikan Python 3.x telah terinstal di sistem Anda.
2. Install semua dependensi yang dibutuhkan dengan perintah berikut:

   ```bash
   pip install pandas selenium openpyxl
   ```

3. Unduh Chrome WebDriver yang sesuai dengan versi Chrome Anda di:
   [https://googlechromelabs.github.io/chrome-for-testing/](https://googlechromelabs.github.io/chrome-for-testing/)

4. Ekstrak file `chromedriver` dan tambahkan lokasinya ke PATH sistem:

   **Windows:**

   - Pindahkan `chromedriver.exe` ke folder seperti `C:\WebDriver\bin`
   - Tambahkan folder tersebut ke Environment Variables > System variables > `Path`

   **Mac/Linux:**

   - Pindahkan `chromedriver` ke `/usr/local/bin/` atau folder lain yang sudah ada di PATH
   - Atau tambahkan folder tempat `chromedriver` berada ke PATH melalui `~/.bashrc`, `~/.zshrc`, atau `~/.profile`:

     ```bash
     export PATH=$PATH:/path/to/your/chromedriver
     ```

5. Jalankan script dengan:

   ```bash
   python main.py
   ```

6. Ikuti instruksi atau sesuaikan isi file Excel sesuai dengan struktur yang dibutuhkan oleh script.

## ⚠️ Peringatan

> **Gunakan dengan bijak. Jangan salahgunakan script ini. Script ini dibuat untuk _membelah diri_ karena banyaknya kerjaan yang saling bertumpukan.**

Script ini ditujukan untuk membantu produktivitas dan efisiensi, bukan untuk disalahgunakan.

## 📄 Lisensi

Script ini disediakan _as-is_ tanpa jaminan. Bebas digunakan dan dimodifikasi, namun segala risiko ditanggung oleh pengguna.
