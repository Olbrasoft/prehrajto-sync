#!/usr/bin/env python3
"""Obohatí JSONL backlog (sktorrent-films.jsonl) o `description` z cr_dev DB.

Zdroj: Postgres `cr_dev`, tabulka `films`, sloupec `description` (LLM rewrite).
Klíč spojení: `cr_slug` (JSONL) ←→ `slug` (DB).

Spuštění:
    python3 scripts/enrich_backlog_with_descriptions.py \\
        --in  backlog/sktorrent-films.jsonl \\
        --out backlog/sktorrent-films-enriched.jsonl

Zachovává pořadí, doplní `description` (None pokud chybí v DB).
"""
import argparse
import json
import sys
from pathlib import Path
import psycopg2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Vstupní JSONL")
    ap.add_argument("--out", dest="out", required=True, help="Výstupní JSONL")
    ap.add_argument(
        "--dsn",
        default="postgres://jirka@localhost/cr_dev",
        help="Postgres DSN (default: lokální cr_dev)",
    )
    args = ap.parse_args()

    in_path = Path(args.inp)
    out_path = Path(args.out)
    if not in_path.is_file():
        print(f"ERROR: vstupní soubor neexistuje: {in_path}", file=sys.stderr)
        return 2

    rows = [json.loads(line) for line in in_path.read_text().splitlines() if line.strip()]
    slugs = {r["cr_slug"] for r in rows if r.get("cr_slug")}
    print(f"[enrich] {len(rows)} řádků, {len(slugs)} unikátních slugů")

    conn = psycopg2.connect(args.dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT slug, description FROM films "
                "WHERE slug = ANY(%s) AND description IS NOT NULL",
                (list(slugs),),
            )
            desc_by_slug = dict(cur.fetchall())
    finally:
        conn.close()

    matched = sum(1 for r in rows if r.get("cr_slug") in desc_by_slug)
    print(f"[enrich] popis nalezen pro {matched}/{len(rows)} filmů")

    with out_path.open("w") as f:
        for r in rows:
            r["description"] = desc_by_slug.get(r.get("cr_slug"))
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[enrich] zapsáno: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
