import pandas as pd
import psycopg2
from io import StringIO

# Load data CSV
df = pd.read_csv('alokasi.csv')

# Buat buffer CSV tanpa header
buffer = StringIO()
df.to_csv(buffer, index=False, header=False)
buffer.seek(0)

# Koneksi ke NeonDB
conn = psycopg2.connect(
    dbname="neondb",
    user="neondb_owner",
    password="npg_0vY6ikXVUxcZ",
    host="ep-flat-sky-a1m3o0gt-pooler.ap-southeast-1.aws.neon.tech",
    sslmode="require"
)
cursor = conn.cursor()

# COPY ke tabel
cursor.copy_from(buffer, 'wilkerstat', sep=';')
conn.commit()

cursor.close()
conn.close()
