import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

EXCEL_PATH = os.getenv("EXCEL_PATH", "master.xlsx")
SHEET_NAME = os.getenv("SHEET_NAME", None)  # None = sheet aktif

def clean_str(x):
    if x is None:
        return None
    # pandas baca NaN sebagai float nan
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    return s if s != "" else None

def main():
    print(f"📊 Membaca Excel {EXCEL_PATH}...")
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, dtype=str)
    
    # Normalisasi nama kolom
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Pastikan kolom yang diperlukan ada
    required_cols = ['idsbr', 'nama_usaha']
    for col in required_cols:
        if col not in df.columns:
            # Coba cari kolom dengan nama serupa
            for c in df.columns:
                if col in c.lower():
                    df[col] = df[c]
                    break
            if col not in df.columns:
                print(f"❌ Kolom {col} tidak ditemukan!")
                return
    
    # Bersihkan data
    df['idsbr'] = df['idsbr'].map(clean_str)
    df['nama_usaha'] = df['nama_usaha'].map(clean_str)
    
    # Hapus baris dengan idsbr kosong
    df = df[~df['idsbr'].isna()]
    
    # Identifikasi duplikat berdasarkan idsbr
    duplicates = df[df.duplicated('idsbr', keep=False)].sort_values('idsbr')
    
    if len(duplicates) == 0:
        print("✅ Tidak ada duplikat idsbr dalam data.")
        return
    
    # Simpan ke CSV
    output_file = "duplicate_idsbr.csv"
    duplicates[['idsbr', 'nama_usaha']].to_csv(output_file, index=False)
    
    print(f"✅ Ditemukan {len(duplicates)} baris dengan idsbr duplikat.")
    print(f"💾 Data duplikat disimpan ke {output_file}")
    
    # Tampilkan beberapa contoh duplikat
    print("\nContoh data duplikat:")
    sample_size = min(10, len(duplicates))
    print(duplicates[['idsbr', 'nama_usaha']].head(sample_size))

if __name__ == "__main__":
    main()