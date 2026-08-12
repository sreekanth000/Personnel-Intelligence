import duckdb

conn = duckdb.connect("data/world_model.duckdb", read_only=True)

print("=== TABLES ===")
tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
print(tables)

for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"\n=== {t} ({count} rows) ===")
    if count > 0:
        df = conn.execute(f"SELECT * FROM {t} LIMIT 3").fetchdf()
        print(df.to_string())
    else:
        print("(empty)")

conn.close()
