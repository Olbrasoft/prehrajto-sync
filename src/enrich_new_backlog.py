#!/usr/bin/env python3
"""Enrich new sktorrent films from cr's upload-backlog into our rich backlog.

Input:  backlog/cr-upload-backlog.sktorrent.jsonl (minimal: film_id, tmdb_id,
        title, original_title, year, sktorrent_video_id)
Output: append rows to backlog/sktorrent-films.jsonl in the canonical format
        used by sync_batch.py / pick_next_film.py / detect_audio_language.py.

Data sources per row:
    cr DB:  slug, imdb_id, runtime_min, sktorrent_cdn, sktorrent_qualities,
            has_dub, has_subtitles
    TMDB:   original_language, production_countries, overview (cs-CZ + en-US)
    URL:    https://online.sktorrent.eu/media/videos//h264/{svid}_{quality}.mp4
            (no CDN edge — resolve_sktorrent_cdn picks a live one at upload time)

`description` is set to tmdb_overview_cs ?? tmdb_overview_en ?? sktorrent_desc
(user wants TMDB/original descriptions, NOT our website's generated ones).

Skips rows whose cr_film_id is already in backlog/sktorrent-films.jsonl.

Usage:
    python3 src/enrich_new_backlog.py
    python3 src/enrich_new_backlog.py --limit 20
    python3 src/enrich_new_backlog.py --dry-run
"""
import argparse
import json
import os
import re
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

INPUT = REPO / "backlog" / "cr-upload-backlog.sktorrent.jsonl"
BACKLOG = REPO / "backlog" / "sktorrent-films.jsonl"
STATE = REPO / "state" / "uploaded.json"

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
SKT_DETAIL_UA = {"User-Agent": UA, "Accept-Encoding": "identity"}

_SOURCE_RE = re.compile(
    r'<source\s+src="https://online(\d+)\.sktorrent\.eu/media/videos//h264/'
    r'(\d+)_(\d+p)\.mp4"',
    re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta\s+property="og:description"\s+content="([^"]*)"',
    re.IGNORECASE,
)


def _quality_sort_key(label: str) -> int:
    m = re.match(r"(\d+)p", label.lower())
    return int(m.group(1)) if m else 0


def best_quality(qualities_csv: str | None) -> str | None:
    if not qualities_csv:
        return None
    parts = [q.strip() for q in qualities_csv.split(",") if q.strip()]
    parts.sort(key=_quality_sort_key, reverse=True)
    return parts[0] if parts else None


def tmdb_get(session, path, params=None, max_retries=3):
    p = {"api_key": TMDB_API_KEY}
    if params:
        p.update(params)
    url = f"{TMDB_BASE}{path}"
    for attempt in range(max_retries):
        try:
            r = session.get(url, params=p, timeout=30)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return None
    return None


def fetch_tmdb_movie(session, tmdb_id):
    cs = tmdb_get(session, f"/movie/{tmdb_id}", {"language": "cs-CZ"}) or {}
    en = tmdb_get(session, f"/movie/{tmdb_id}", {"language": "en-US"}) or {}
    base = en or cs  # base non-translated fields should match
    countries = [
        c.get("iso_3166_1") for c in (base.get("production_countries") or [])
        if c.get("iso_3166_1")
    ]
    return {
        "original_language": base.get("original_language"),
        "production_countries": countries,
        "tmdb_overview_cs": (cs.get("overview") or "").strip(),
        "tmdb_overview_en": (en.get("overview") or "").strip(),
    }


def fetch_sktorrent_description(sktorrent_video_id: int) -> str | None:
    """Fallback — only called when TMDB has no overview."""
    url = f"https://online.sktorrent.eu/video/{sktorrent_video_id}/"
    try:
        r = requests.get(url, headers=SKT_DETAIL_UA, timeout=20)
        if r.status_code != 200:
            return None
        m = _OG_DESC_RE.search(r.text)
        if not m:
            return None
        d = m.group(1).strip()
        return d or None
    except requests.RequestException:
        return None


def load_existing_cr_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    out = set()
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                cid = r.get("cr_film_id")
                if cid is not None:
                    out.add(cid)
            except json.JSONDecodeError:
                continue
    return out


def load_input(path: Path):
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_state_blocked(path: Path) -> set[int]:
    if not path.exists():
        return set()
    s = json.loads(path.read_text())
    done = {u["cr_film_id"] for u in s.get("uploads", [])}
    mod = {u["cr_film_id"] for u in s.get("moderated_out", [])}
    fail = {f["cr_film_id"] for f in s.get("failed_attempts", [])}
    return done | mod | fail


def build_record(cr_row: dict, tmdb: dict, upload_row: dict, sktorrent_desc: str | None) -> dict | None:
    """Compose one rich backlog row. Returns None if unplayable."""
    svid = cr_row.get("sktorrent_video_id") or upload_row.get("sktorrent_video_id")
    if not svid:
        return None
    quality = best_quality(cr_row.get("sktorrent_qualities"))
    if not quality:
        return None
    url = f"https://online.sktorrent.eu/media/videos//h264/{svid}_{quality}.mp4"

    # Description priority: TMDB cs → TMDB en → sktorrent og:description
    desc = (tmdb.get("tmdb_overview_cs") or "").strip()
    if not desc:
        desc = (tmdb.get("tmdb_overview_en") or "").strip()
    if not desc and sktorrent_desc:
        desc = sktorrent_desc.strip()

    return {
        "id": svid,
        "title": cr_row.get("title") or upload_row.get("title"),
        "year": cr_row.get("year") or upload_row.get("year"),
        "quality": quality,
        "cr_film_id": cr_row["id"],
        "cr_slug": cr_row.get("slug"),
        "runtime_min": cr_row.get("runtime_min"),
        "has_dub": cr_row.get("has_dub"),
        "has_subtitles": cr_row.get("has_subtitles"),
        "priority_score": 0.0,
        "imdb_id": cr_row.get("imdb_id"),
        "csfd_id": cr_row.get("csfd_id"),
        "url": url,
        "description": desc,
        "prehrajto_description": desc,
        "tmdb_id": cr_row.get("tmdb_id") or upload_row.get("tmdb_id"),
        "original_language": tmdb.get("original_language"),
        "production_countries": tmdb.get("production_countries") or [],
        "tmdb_overview_cs": tmdb.get("tmdb_overview_cs") or "",
        "tmdb_overview_en": tmdb.get("tmdb_overview_en") or "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true",
                    help="Do not append to backlog; write to backlog/sktorrent-films-new.jsonl only")
    args = ap.parse_args()

    if not TMDB_API_KEY:
        print(f"ERROR: TMDB_API_KEY not set (checked {REPO}/.env and {CR_ENV})", file=sys.stderr)
        return 2

    import psycopg2
    from psycopg2.extras import RealDictCursor

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    existing_cr = load_existing_cr_ids(BACKLOG)
    blocked = load_state_blocked(STATE)
    print(f"Already in rich backlog: {len(existing_cr)} cr_film_ids")
    print(f"Blocked in state (done/failed/moderated): {len(blocked)} cr_film_ids")

    # Filter input: only rows not yet in rich backlog, not blocked.
    candidates = []
    for r in load_input(INPUT):
        cid = r.get("film_id")
        if cid in existing_cr:
            continue
        if cid in blocked:
            continue
        if not r.get("sktorrent_video_id"):
            continue
        if not r.get("tmdb_id"):
            continue
        candidates.append(r)

    if args.limit > 0:
        candidates = candidates[: args.limit]

    total = len(candidates)
    print(f"To enrich: {total}")
    if not total:
        return 0

    conn = psycopg2.connect(dsn)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    ids = [r["film_id"] for r in candidates]
    cur.execute(
        """
        SELECT id, title, slug, year, imdb_id, tmdb_id, csfd_id, runtime_min,
               sktorrent_video_id, sktorrent_cdn, sktorrent_qualities,
               has_dub, has_subtitles
        FROM films WHERE id = ANY(%s)
        """,
        (ids,),
    )
    cr_by_id = {row["id"]: dict(row) for row in cur.fetchall()}
    cur.close()
    conn.close()
    print(f"cr DB rows matched: {len(cr_by_id)} / {total}")

    tmdb_session = requests.Session()
    tmdb_session.headers.update({"Accept": "application/json"})

    new_rows = []
    skipped_nocr = skipped_noplay = skipped_nodesc = 0
    start = time.time()

    for n, r in enumerate(candidates, 1):
        fid = r["film_id"]
        cr_row = cr_by_id.get(fid)
        if not cr_row:
            skipped_nocr += 1
            continue

        # 1. TMDB
        tmdb_id = cr_row.get("tmdb_id") or r.get("tmdb_id")
        tmdb = fetch_tmdb_movie(tmdb_session, tmdb_id) if tmdb_id else {}

        # 2. sktorrent description fallback — only if TMDB has nothing
        sktorrent_desc = None
        if not (tmdb.get("tmdb_overview_cs") or tmdb.get("tmdb_overview_en")):
            sktorrent_desc = fetch_sktorrent_description(cr_row["sktorrent_video_id"])
            time.sleep(0.2)  # polite

        rec = build_record(cr_row, tmdb, r, sktorrent_desc)
        if rec is None:
            skipped_noplay += 1
            continue
        if not rec["description"]:
            skipped_nodesc += 1
            # still keep it — enrichment can fill later; but flag
        new_rows.append(rec)

        if n <= 5 or n % 25 == 0 or n == total:
            elapsed = time.time() - start
            rate = n / elapsed * 3600 if elapsed > 0 else 0
            print(
                f"  {n}/{total}  cr={fid}  {rec['title']!r} ({rec['year']}) "
                f"q={rec['quality']} lang={rec['original_language']} "
                f"desc={len(rec['description'])}  "
                f"[{rate:.0f}/h, {elapsed:.0f}s]",
                flush=True,
            )

    dur = time.time() - start
    print()
    print(f"Enriched {len(new_rows)} films in {dur:.0f}s ({dur/60:.1f}m)")
    print(f"  skipped: no_cr_row={skipped_nocr} no_playable={skipped_noplay}")
    print(f"  no description at all: {skipped_nodesc}")

    # Write output
    if args.dry_run:
        out = REPO / "backlog" / "sktorrent-films-new.jsonl"
        with out.open("w") as f:
            for rec in new_rows:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[dry-run] wrote {len(new_rows)} → {out}")
    else:
        # Append to rich backlog
        with BACKLOG.open("a") as f:
            for rec in new_rows:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"Appended {len(new_rows)} → {BACKLOG}")

    # Stats: how many have cs/sk original_language
    from collections import Counter
    lang = Counter(r.get("original_language") for r in new_rows)
    print("\nOriginal-language distribution (new rows):")
    for k, v in lang.most_common(15):
        print(f"  {k!r:10s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
