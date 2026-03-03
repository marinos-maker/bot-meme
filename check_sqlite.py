import sqlite3
import os

db_path = "detector.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables in detector.db:")
    for table in tables:
        print(f"- {table[0]}")
        # Print first few rows of each table or schema
        cursor.execute(f"PRAGMA table_info({table[0]})")
        columns = cursor.fetchall()
        print(f"  Columns: {[c[1] for c in columns]}")
    conn.close()
else:
    print("detector.db not found")
