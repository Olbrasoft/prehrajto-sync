#!/usr/bin/env python3
"""Fetch Czech (and English fallback) TMDB overview for each film.

Stores `tmdb_overview_cs` and `tmdb_overview_en` in the backlog JSONL.
Used downstream by `generate_prehrajto_descriptions.py` as factual ground
truth so Gemma rephrases instead of hallucinating.

Usage:
    python3 src/enrich_tmdb_overview.py backlog/sktorrent-films.jsonl
    python3 src/enrich_tmdb_overview.py backlog/sktorrent-films.jsonl --only-ids 49,168
    python3 src/enrich_tmdb_overview.py backlog/sktorrent-films.jsonl --force
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

REPO = Path(__file__).resolve().parent.parent
CR_ENV = Path.home() / "GitHub" / "Olbrasoft" / "cr" / ".env"

if load_dotenv is not None:
    load_dotenv(REPO / ".env")
    if CR_ENV.exists():
        load_dotenv(CR_ENV, override=False)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
if not TMDB_API_KEY:
    print(f"ERROR: TMDB_API_KEY not set. Checked {REPO}/.env and {CR_ENV}.", file=sys.stderr)
    sys.exit(1)

TMDB_BASE = "https://api.themoviedb.org/3"
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json"})


def tmdb_get(path: str, params: dict | None = None, max_retries: int = 3):
    p = {"api_key": TMDB_API_KEY}
    if params:
        p.update(params)
    url = f"{TMDB_BASE}{path}"
    for attempt in range(max_retries):
        try:
            r = SESSION.get(url, params=p, timeout=30)
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  429 rate limit, wait {wait}s", flush=True)
                time.sleep(wait)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise RuntimeError(f"TMDB {path}: {e}") from e
    raise RuntimeError(f"TMDB {path}: max retries")


def fetch_overviews(tmdb_id: int) -> dict:
    """Returns {cs: str, en: str}. Empty strings when language missing."""
    cs = tmdb_get(f"/movie/{tmdb_id}", {"language": "cs-CZ"}) or {}
    en = tmdb_get(f"/movie/{tmdb_id}", {"language": "en-US"}) or {}
    return {
        "cs": (cs.get("overview") or "").strip(),
        "en": (en.get("overview") or "").strip(),
    }


def process_file(path: Path, only_ids: set[int] | None, force: bool):
    records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    todo = []
    for i, r in enumerate(records):
        if not r.get("tmdb_id"):
            continue
        if only_ids and r.get("cr_film_id") not in only_ids:
            continue
        if not force and ("tmdb_overview_cs" in r or "tmdb_overview_en" in r):
            continue
        todo.append(i)

    total = len(todo)
    if not total:
        print(f"{path.name}: nothing to enrich")
        return 0, 0

    print(f"{path.name}: {total} films to enrich (of {len(records)})", flush=True)

    ok = fail = 0
    save_every = 20
    start = time.time()

    for n, idx in enumerate(todo, 1):
        r = records[idx]
        tmdb_id = r["tmdb_id"]
        title = r.get("title", "?")
        year = r.get("year", "?")
        try:
            ov = fetch_overviews(tmdb_id)
        except Exception as e:
            print(f"  FAIL: {title} ({year}) tmdb={tmdb_id} — {e}", flush=True)
            r["tmdb_overview_cs"] = ""
            r["tmdb_overview_en"] = ""
            fail += 1
            continue

        r["tmdb_overview_cs"] = ov["cs"]
        r["tmdb_overview_en"] = ov["en"]
        ok += 1
        if n <= 5 or n % 100 == 0:
            cs_len = len(ov["cs"])
            en_len = len(ov["en"])
            print(f"  {n}/{total}: {title} ({year}) cs={cs_len} en={en_len}", flush=True)

        if n % save_every == 0 or n == total:
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tmp.replace(path)
            elapsed = time.time() - start
            rate = n / elapsed * 3600 if elapsed > 0 else 0
            print(f"  --- saved, {n}/{total} done ({ok} ok, {fail} fail, {rate:.0f}/h)", flush=True)

    has_cs = sum(1 for r in records if r.get("tmdb_overview_cs"))
    has_en = sum(1 for r in records if r.get("tmdb_overview_en"))
    print(f"{path.name}: done. OK: {ok}, Fail: {fail}")
    print(f"  has CS overview: {has_cs}/{len(records)}")
    print(f"  has EN overview: {has_en}/{len(records)}")
    return ok, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Path to backlog JSONL")
    ap.add_argument("--only-ids", type=str, default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    only_ids = set()
    if args.only_ids:
        only_ids = {int(x.strip()) for x in args.only_ids.split(",") if x.strip()}

    p = Path(args.path)
    if not p.is_file():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)

    process_file(p, only_ids or None, args.force)


if __name__ == "__main__":
    main()
