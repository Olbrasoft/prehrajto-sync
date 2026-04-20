#!/usr/bin/env python3
"""Enrich backlog JSONL with `original_language` and `production_countries` from TMDB.

For each film, looks up TMDB by imdb_id via /find and fetches /movie details to
obtain the ISO 639-1 original language and ISO 3166-1 country list. This lets
the uploader pick the correct Prehraj.to title suffix:
- original_language in {cs, sk}  → "CZ HD"        (native Czech/Slovak audio)
- otherwise (with Czech audio)  → "CZ Dabing HD" (dubbed)

Uses TMDB_API_KEY from ~/GitHub/Olbrasoft/cr/.env (or prehrajto-sync/.env).
Safe to resume: already-enriched rows (have `original_language` key) are skipped.

Usage:
    python3 src/enrich_origin_language.py backlog/sktorrent-films.jsonl
    python3 src/enrich_origin_language.py backlog/sktorrent-films-cs.jsonl
    python3 src/enrich_origin_language.py --both
    python3 src/enrich_origin_language.py <file> --only-ids 49,168
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


def enrich_one(imdb_id: str):
    """Returns dict with original_language + production_countries, or None."""
    found = tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
    if not found:
        return None
    movies = found.get("movie_results", []) or []
    if not movies:
        return None
    tmdb_id = movies[0]["id"]
    movie = tmdb_get(f"/movie/{tmdb_id}")
    if not movie:
        return None
    countries = [c.get("iso_3166_1") for c in movie.get("production_countries", []) if c.get("iso_3166_1")]
    return {
        "tmdb_id": tmdb_id,
        "original_language": movie.get("original_language"),
        "production_countries": countries,
    }


def process_file(path: Path, only_ids: set[int] | None, force: bool):
    lines = path.read_text().splitlines()
    records = [json.loads(l) for l in lines if l.strip()]

    todo = []
    for i, r in enumerate(records):
        if not force and "original_language" in r:
            continue
        if not r.get("imdb_id"):
            continue
        if only_ids and r.get("cr_film_id") not in only_ids:
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
        imdb = r["imdb_id"]
        title = r.get("title", "?")
        year = r.get("year", "?")
        try:
            result = enrich_one(imdb)
        except Exception as e:
            print(f"  FAIL: {title} ({year}) imdb={imdb} — {e}", flush=True)
            r["original_language"] = None
            r["production_countries"] = []
            fail += 1
            continue

        if result is None:
            print(f"  MISS: {title} ({year}) imdb={imdb} — not on TMDB", flush=True)
            r["original_language"] = None
            r["production_countries"] = []
            fail += 1
        else:
            r["tmdb_id"] = result["tmdb_id"]
            r["original_language"] = result["original_language"]
            r["production_countries"] = result["production_countries"]
            ok += 1
            if n <= 5 or n % 50 == 0:
                print(
                    f"  {n}/{total}: {title} ({year}) → lang={result['original_language']}, "
                    f"countries={result['production_countries']}",
                    flush=True,
                )

        if n % save_every == 0 or n == total:
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tmp.replace(path)
            elapsed = time.time() - start
            rate = n / elapsed * 3600 if elapsed > 0 else 0
            print(f"  --- saved, {n}/{total} done ({ok} ok, {fail} miss/fail, {rate:.0f}/h)", flush=True)

    print(f"{path.name}: done. OK: {ok}, Miss/fail: {fail}")
    return ok, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="Path to backlog JSONL")
    ap.add_argument("--both", action="store_true", help="Enrich both full + cs backlogs")
    ap.add_argument("--only-ids", type=str, default="")
    ap.add_argument("--force", action="store_true", help="Re-fetch even if original_language already set")
    args = ap.parse_args()

    only_ids = set()
    if args.only_ids:
        only_ids = {int(x.strip()) for x in args.only_ids.split(",") if x.strip()}

    paths = []
    if args.both:
        paths = [REPO / "backlog" / "sktorrent-films.jsonl", REPO / "backlog" / "sktorrent-films-cs.jsonl"]
    elif args.path:
        paths = [Path(args.path)]
    else:
        ap.print_help()
        sys.exit(2)

    for p in paths:
        if not p.is_file():
            print(f"ERROR: {p} neexistuje", file=sys.stderr)
            continue
        process_file(p, only_ids or None, args.force)


if __name__ == "__main__":
    main()
