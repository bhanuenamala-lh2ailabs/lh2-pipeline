"""Live progress watcher for the background enrichment run.

Run from the project root:  python watch_progress.py
Prints every 15s; Ctrl+C to stop (does not affect the background run).
"""
import sqlite3
import time

DB = "data/pipeline.sqlite"
TARGET = 100

while True:
    try:
        c = sqlite3.connect(DB)
        d = c.execute("SELECT COUNT(DISTINCT domain) FROM people").fetchone()[0]
        f = c.execute("SELECT COUNT(*) FROM people WHERE name<>'(verify)'").fetchone()[0]
        p = c.execute("SELECT COUNT(*) FROM people WHERE phone IS NOT NULL").fetchone()[0]
        c.close()
        print(f"firms enriched: {d}/{TARGET} | founder rows: {f} | phones: {p}", flush=True)
    except Exception as e:
        print("waiting for db...", e, flush=True)
    time.sleep(15)
