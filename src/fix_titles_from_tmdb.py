#!/usr/bin/env python3
"""Replace hard-to-read titles in the backlog with Czech or English titles from TMDB.

Some films in the backlog have original-script titles (Korean, Japanese,
Chinese, Arabic, …) that render as mojibake or are unreadable for a Czech
audience. For each film with a `tmdb_id`, we fetch the Czech and English
TMDB titles and pick the first one whose characters stay within Latin
or Cyrillic scripts.

Saves:
- `title`                 overwritten with the picked title
- `title_original`        preserved only if this is the first rewrite
- `title_source`          'cs-CZ' / 'en-US' / 'kept' (when nothing better)

Usage:
    python3 src/fix_titles_from_tmdb.py
    python3 src/fix_titles_from_tmdb.py --only-ids 2542,168 --dry-run
    python3 src/fix_titles_from_tmdb.py --only-unreadable
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
BACKLOG = REPO / "backlog" / "sktorrent-films.jsonl"
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

# Allowed Unicode script ranges — Latin (incl. Czech diacritics), Cyrillic,
# Greek. Anything in CJK / Arabic / Hebrew / Devanagari / Thai / etc. is
# considered unreadable for a Czech audience.
ALLOWED_RANGES = [
    (0x0000, 0x024F),  # ASCII + Latin-1 + Latin Ext-A/B (Czech diacritics fit here)
    (0x0370, 0x03FF),  # Greek
    (0x0400, 0x052F),  # Cyrillic + Cyrillic Supplement
    (0x1E00, 0x1EFF),  # Latin Extended Additional
    (0x2000, 0x206F),  # General Punctuation (dashes, quotes)
    (0x2100, 0x214F),  # Letter-like Symbols
    (0x2200, 0x22FF),  # Mathematical operators (for "∞" etc. if any)
]


def is_readable(s: str | None) -> bool:
    if not s:
        return False
    for ch in s:
        cp = ord(ch)
        if not any(lo <= cp <= hi for lo, hi in ALLOWED_RANGES):
            return False
    return True


def tmdb_get(path: str, params: dict, timeout: int = 30, retries: int = 3):
    p = {"api_key": TMDB_API_KEY, **params}
    url = f"{TMDB_BASE}{path}"
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=timeout)
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                time.sleep(wait)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return None
    return None


def fetch_titles(tmdb_id: int) -> tuple[str | None, str | None]:
    cs = tmdb_get(f"/movie/{tmdb_id}", {"language": "cs-CZ"}) or {}
    en = tmdb_get(f"/movie/{tmdb_id}", {"language": "en-US"}) or {}
    return (cs.get("title") or "").strip() or None, (en.get("title") or "").strip() or None


def pick_best(cs: str | None, en: str | None, current: str | None) -> tuple[str | None, str]:
    """Return (picked_title, source). Source: 'cs-CZ' / 'en-US' / 'kept' / 'already_readable'."""
    if cs and is_readable(cs):
        return cs, "cs-CZ"
    if en and is_readable(en):
        return en, "en-US"
    if current and is_readable(current):
        return current, "already_readable"
    return current, "kept"


def load_records():
    with BACKLOG.open() as f:
        return [json.loads(l) for l in f if l.strip()]


def save_records(records):
    tmp = BACKLOG.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(BACKLOG)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-ids", type=str, default="",
                    help="Comma-separated cr_film_id list")
    ap.add_argument("--only-unreadable", action="store_true",
                    help="Skip films whose current title is already readable")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    only_ids = set()
    if args.only_ids:
        only_ids = {int(x.strip()) for x in args.only_ids.split(",") if x.strip()}

    records = load_records()
    todo = []
    for i, r in enumerate(records):
        if only_ids and r.get("cr_film_id") not in only_ids:
            continue
        if not r.get("tmdb_id"):
            continue
        if args.only_unreadable and is_readable(r.get("title")):
            continue
        todo.append(i)

    if args.limit > 0:
        todo = todo[: args.limit]

    total = len(todo)
    if not total:
        print("Nothing to process.")
        return 0
    print(f"Films to check: {total}")

    changed = kept = failed = 0
    start = time.time()
    for n, idx in enumerate(todo, 1):
        r = records[idx]
        fid = r["cr_film_id"]
        current = r.get("title", "")
        tmdb_id = r["tmdb_id"]

        cs_title, en_title = fetch_titles(tmdb_id)
        if cs_title is None and en_title is None:
            failed += 1
            if n <= 5 or n % 100 == 0:
                print(f"  {n}/{total} FAIL [id={fid}] tmdb={tmdb_id} — no TMDB data")
            continue

        picked, source = pick_best(cs_title, en_title, current)

        if picked and picked != current:
            if "title_original" not in r:
                r["title_original"] = current
            r["title"] = picked
            r["title_source"] = source
            changed += 1
            if n <= 20 or n % 50 == 0 or not is_readable(current):
                print(f"  {n}/{total} [id={fid}] '{current}' → '{picked}' ({source})")
        else:
            if source == "already_readable" and "title_source" not in r:
                r["title_source"] = source
            kept += 1

        if not args.dry_run and n % 25 == 0:
            save_records(records)

    if not args.dry_run:
        save_records(records)

    dur = time.time() - start
    print()
    print(f"Done in {dur:.0f}s ({dur/60:.1f}m) — changed={changed} kept={kept} failed={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
