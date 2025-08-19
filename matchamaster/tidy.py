import psycopg2
import csv
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# === Database connection ===
conn = psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=int(os.getenv("PGPORT", "5432")),
        sslmode=os.getenv("PGSSLMODE", "require")
)
cur = conn.cursor()

# === Read IDs from file ===
ids_list = []
with open("notfound.txt", newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)  # uses header "IDSBR"
    for row in reader:
        if row["IDSBR"] and row["IDSBR"].strip():
            ids_list.append(row["IDSBR"].strip())

# === Update in one query ===
query = """
    UPDATE public.direktori_ids
    SET automation_status = 'new'
    WHERE idsbr = ANY(%s)
"""
cur.execute(query, (ids_list,))
print(f"Updated rows: {cur.rowcount}")

# === Commit and close ===
conn.commit()
cur.close()
conn.close()
