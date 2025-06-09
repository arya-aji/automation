import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

# --- Load Excel ---
df = pd.read_excel("usaha.xlsx")
idsbr_list = df['idsbr mirip'].dropna().astype(str).tolist()

# --- Setup Selenium dengan Chrome profile (agar sudah login SSO dan VPN aktif) ---
options = webdriver.ChromeOptions()
chrome_profile_path = r"C:\\Users\\adjie\\Documents\\chromeDriver\\profile"
options.add_argument(f"--user-data-dir={chrome_profile_path}")
driver = webdriver.Chrome(options=options)

# --- Buka halaman utama ---
driver.get("https://matchapro.web.bps.go.id/direktori-usaha")
time.sleep(7)  # Tunggu halaman dan JS selesai load

for idsbr in idsbr_list:
    try:
        print(f"Memproses IDSBR: {idsbr}")

        # Cari input dengan name=idsbr
        input_box = driver.find_element(By.NAME, "idsbr")
        input_box.clear()
        input_box.send_keys(idsbr)

        # Klik tombol filter
        filter_button = driver.find_element(By.ID, "filter-data")
        filter_button.click()

        time.sleep(7)  # Tunggu hasil filter keluar

        # Ambil semua tombol edit yang muncul
        edit_buttons = driver.find_elements(By.CSS_SELECTOR, 'a.btn-edit-perusahaan[aria-label="Edit"]')

        if len(edit_buttons) == 1:
            print(f"✅ Ditemukan 1 hasil, klik tombol edit untuk {idsbr}")
            # Klik tombol edit
            driver.execute_script("arguments[0].click();", edit_buttons[0])
            time.sleep(5)  # Tunggu Modal Entri
            print("🔄 Menunggu modal SweetAlert...")

            # Tunggu modal SweetAlert muncul dan klik tombol "Ya, edit!"
            try:
                # Tunggu tombol benar-benar visible dan aktif
                confirm_button = WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, 'button.swal2-confirm.swal2-styled'))
                )

                # Klik pakai JavaScript (lebih paksa)
                driver.execute_script("arguments[0].click();", confirm_button)
                print("✅ Klik tombol 'Ya, edit!' berhasil (via JS).")
                print("✅ Klik tombol 'Ya, edit!' di modal berhasil.")
                
                #Entri Form
                # Tunggu form selesai load
                WebDriverWait(driver, 10).until(                
                    EC.presence_of_element_located((By.ID, "alamat_usaha"))
                )

                # 1. Isi Alamat
                alamat_input = driver.find_element(By.ID, "alamat_usaha")
                alamat_input.clear()
                alamat_input.send_keys(row["Alamat"])

                # 2. Isi Sumber Profiling
                try:                
                    sumber_input = driver.find_element(By.ID, "sumber_profiling")
                    sumber_input.clear()
                    sumber_input.send_keys(row["Sumber"])
                except:             
                    print("❌ Tidak ditemukan input sumber_profiling")

                # 3. Isi Catatan Profiling
                try:
                    catatan_input = driver.find_element(By.ID, "catatan_profiling")
                    catatan_input.clear()
                    catatan_input.send_keys(row["Desk Sumber"])
                except:
                    print("❌ Tidak ditemukan input catatan_profiling")

            except:
                print("❌ Gagal menemukan atau klik tombol 'Ya, edit!'")
            break  # Stop di 1 data dulu sesuai permintaan
        else:
            print(f"⚠️ Hasil IDSBR {idsbr} tidak unik atau tidak ditemukan.")

        # Reload ulang halaman utama untuk IDSBR berikutnya
        driver.get("https://matchapro.web.bps.go.id/direktori-usaha")
        time.sleep(7)

    except Exception as e:
        print(f"❌ Error saat memproses {idsbr}: {e}")
        driver.get("https://matchapro.web.bps.go.id/direktori-usaha")
        time.sleep(7)

driver.quit()
