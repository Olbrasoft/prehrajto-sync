#!/usr/bin/env python3
"""Scrape sktorrent video detail pages and record external .vtt subtitle tracks
into the backlog.

Only processes films that are NOT yet uploaded / failed / moderated — there's
no point enriching films we've already shipped, because later subtitle dubbing
will be done by cr_film_id against the live sktorrent endpoint anyway.

The sktorrent player HTML embeds tracks like:
    <track src="…/vtt/<id>/Cesky.vtt" kind="substitles" srclang="cs" label=Cesky>

Note the `substitles` typo (theirs, not ours). We accept both.

Writes back to backlog JSONL:
    sktorrent_subtitles: [
        {"lang": "cs", "label": "Cesky", "url": "…/Cesky.vtt"},
        …
    ]
Lang is derived from `label` first (authoritative; sktorrent occasionally
mislabels srclang), falling back to `srclang`.

Usage:
    python3 src/enrich_sktorrent_subtitles.py
    python3 src/enrich_sktorrent_subtitles.py --only-ids 2307,4456 --dry-run
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "backlog" / "sktorrent-films.jsonl"
STATE = REPO / "state" / "uploaded.json"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
TRACK_RE = re.compile(r"<track\s+([^>]+?)/?>", re.IGNORECASE)
ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))')

LABEL_TO_LANG = {
    "cesky": "cs",
    "cesky ": "cs",
    "česky": "cs",
    "czech": "cs",
    "slovensky": "sk",
    "slovak": "sk",
    "english": "en",
    "anglicky": "en",
}


def normalize_lang(label: str | None, srclang: str | None) -> str | None:
    if label:
        key = label.strip().lower()
        if key in LABEL_TO_LANG:
            return LABEL_TO_LANG[key]
    if srclang:
        return srclang.strip().lower()
    return None


def parse_tracks(html: str) -> list[dict]:
    out = []
    for m in TRACK_RE.finditer(html):
        attrs = {}
        for am in ATTR_RE.finditer(m.group(1)):
            key = am.group(1).lower()
            val = am.group(2) or am.group(3) or am.group(4) or ""
            attrs[key] = val
        kind = (attrs.get("kind") or "").lower()
        # Accept "subtitles", "captions", and the "substitles" typo used by sktorrent.
        if kind and kind not in ("subtitles", "captions", "substitles"):
            continue
        src = attrs.get("src")
        if not src:
            continue
        out.append({
            "lang": normalize_lang(attrs.get("label"), attrs.get("srclang")),
            "label": attrs.get("label"),
            "url": src,
        })
    return out


def fetch_html(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def load_records() -> list[dict]:
    with BACKLOG.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def save_records(records: list[dict]) -> None:
    tmp = BACKLOG.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(BACKLOG)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-ids", type=str, default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=0.15)
    args = ap.parse_args()

    only_ids = set()
    if args.only_ids:
        only_ids = {int(x.strip()) for x in args.only_ids.split(",") if x.strip()}

    state = json.loads(STATE.read_text())
    uploaded = {u["cr_film_id"] for u in state.get("uploads", [])}
    failed = {f["cr_film_id"] for f in state.get("failed_attempts", [])}
    mo = state.get("moderated_out", [])
    moderated = {m["cr_film_id"] if isinstance(m, dict) else m for m in mo}

    records = load_records()
    todo = []
    for i, r in enumerate(records):
        if only_ids and r.get("cr_film_id") not in only_ids:
            continue
        fid = r.get("cr_film_id")
        if fid in uploaded or fid in failed or fid in moderated:
            continue
        if not r.get("url"):
            continue
        todo.append(i)

    if args.limit > 0:
        todo = todo[: args.limit]

    total = len(todo)
    if not total:
        print("Nothing to enrich.")
        return 0
    print(f"Films to scrape: {total}")

    with_tracks = 0
    total_tracks = 0
    lang_counts = {}
    errs = 0
    start = time.time()

    for n, idx in enumerate(todo, 1):
        r = records[idx]
        sk_id = r["id"]
        try:
            html = fetch_html(f"https://online.sktorrent.eu/video/{sk_id}/")
            tracks = parse_tracks(html)
        except Exception as e:
            errs += 1
            r["sktorrent_subtitles_error"] = str(e)[:200]
            continue

        if tracks:
            r["sktorrent_subtitles"] = tracks
            r.pop("sktorrent_subtitles_error", None)
            with_tracks += 1
            total_tracks += len(tracks)
            for t in tracks:
                lang_counts[t.get("lang")] = lang_counts.get(t.get("lang"), 0) + 1
        else:
            # Record empty list to mark "scraped, none found" — avoids re-scraping.
            r["sktorrent_subtitles"] = []
            r.pop("sktorrent_subtitles_error", None)

        if n % 25 == 0 or n == total:
            print(f"  {n}/{total} with_tracks={with_tracks} errs={errs} "
                  f"elapsed={time.time()-start:.0f}s")

        if not args.dry_run and n % 50 == 0:
            save_records(records)

        time.sleep(args.delay)

    if not args.dry_run:
        save_records(records)

    print()
    print(f"Done — scraped={total} with_tracks={with_tracks} "
          f"total_tracks={total_tracks} errs={errs}")
    print(f"Subtitle languages: {lang_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
