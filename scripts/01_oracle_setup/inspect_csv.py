# inspecionar as tabelas: customers, orders e order_items
import csv
from pathlib import Path

# __file__ é o caminho do próprio script, .resolve() transforma em absoluto,
#  e parents[2] sobe três níveis — 01_oracle_setup → scripts → raiz do projeto. Daí desce pra data/raw
raw_dir = Path(__file__).resolve().parents[2] / "data" / "raw"

for file in ["customers.csv", "orders.csv", "order_items.csv"]:
    path = raw_dir / file
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [next(reader) for _ in range(2)]
        total = sum(1 for _ in f) + 3 #2 lidas + header

    print(f"\n=== {file} ===")
    print(f"linhas: {total}")
    print(f"colunas ({len(header)}): {header}")
    for row in rows:
        print(row)