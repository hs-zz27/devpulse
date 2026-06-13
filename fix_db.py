import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath("backend"))

from app.core.database import engine
from sqlalchemy import text

async def main():
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                text("ALTER TYPE pr_state ADD VALUE IF NOT EXISTS 'MERGED'")
            )
            print("Successfully added 'MERGED' to pr_state enum in the database.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
