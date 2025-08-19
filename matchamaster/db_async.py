# db_async.py
import os, asyncpg
from dotenv import load_dotenv

load_dotenv()

async def get_pool():
    return await asyncpg.create_pool(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=int(os.getenv("PGPORT", "5432")),
        ssl="require"
    )

# Ambil 1 baris secara atomik + lock (hindari duplikat di banyak worker/PC)
# Prioritas: new -> yang attempt_count lebih kecil
CLAIM_SQL = """
WITH cte AS (
  SELECT id
  FROM direktori_ids
  WHERE automation_status = 'new'
  ORDER BY attempt_count ASC, id ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED
)
UPDATE direktori_ids d
SET automation_status = 'in_progress',
    assigned_to = $1,
    first_taken_at = COALESCE(first_taken_at, NOW()),
    last_updated = NOW()
FROM cte
WHERE d.id = cte.id
RETURNING d.*;
"""

async def claim_one(pool, assigned_to:str):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(CLAIM_SQL, assigned_to)
            return row

async def mark_done(pool, id_:int):
    async with pool.acquire() as conn:
        await conn.execute("""
          UPDATE direktori_ids
          SET automation_status = 'done', last_updated = NOW()
          WHERE id = $1
        """, id_)

async def mark_failed(pool, id_:int, error:str):
    async with pool.acquire() as conn:
        await conn.execute("""
          UPDATE direktori_ids
          SET automation_status = 'failed', error = left($2, 1000), last_updated = NOW(),
              attempt_count = attempt_count + 1
          WHERE id = $1
        """, id_, error)

# Jika error infrastruktur (VPN/timeout), kita lepas lagi ke 'new' supaya bisa dicoba worker lain nanti.
async def release_to_new(pool, id_:int, note:str):
    async with pool.acquire() as conn:
        await conn.execute("""
          UPDATE direktori_ids
          SET automation_status = 'new', error = left($2, 1000),
              last_updated = NOW(), attempt_count = attempt_count + 1
          WHERE id = $1
        """, id_, note)
