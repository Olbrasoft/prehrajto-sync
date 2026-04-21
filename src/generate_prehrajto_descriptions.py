#!/usr/bin/env python3
"""Generate unique Czech descriptions for Prehraj.to uploads using Gemma via Gemini API.

Reads backlog/sktorrent-films.jsonl, produces a fresh unique Czech description for
each film that differs from the existing on-site description (to avoid duplicate-
content SEO penalty on ceskarepublika.wiki), writes it back to the JSONL as
`prehrajto_description`. Safe to resume: already-processed rows are skipped.

4 Gemini API keys are used in parallel (same pattern as cr/scripts/generate-film-descriptions.py).

Usage:
    python3 src/generate_prehrajto_descriptions.py --test 3          # test on 3 films (dry-run)
    python3 src/generate_prehrajto_descriptions.py --limit 20        # process first 20 pending
    python3 src/generate_prehrajto_descriptions.py --all             # process all pending
    python3 src/generate_prehrajto_descriptions.py --only-ids 1268,49
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

GEMINI_KEYS = [os.environ.get(f"GEMINI_API_KEY_{i}", "") for i in range(1, 5)]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]
if not GEMINI_KEYS:
    print(f"ERROR: No GEMINI_API_KEY_* env vars found. Checked {REPO}/.env and {CR_ENV}.", file=sys.stderr)
    sys.exit(1)

MODEL = "gemma-3-27b-it"
GEMINI_URL_TPL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={{}}"

PAUSE_BETWEEN_BATCHES = 3
RATE_LIMIT_PAUSE = 60


def build_prompt(title: str, year, tmdb_cs: str, tmdb_en: str, existing_desc: str) -> str:
    year_str = f" ({year})" if year else ""
    # Prefer TMDB Czech overview, fall back to English, last resort the existing desc.
    if tmdb_cs:
        plot_label = "Oficiální český popis děje z TMDB (ground truth — nevymýšlej nic navíc):"
        plot = tmdb_cs
    elif tmdb_en:
        plot_label = "Oficiální anglický popis děje z TMDB (ground truth — přelož a nevymýšlej nic navíc):"
        plot = tmdb_en
    else:
        plot_label = "Existující český popis (ground truth — respektuj fakta, nevymýšlej nové):"
        plot = existing_desc
    return (
        f'Napiš originální český popis filmu "{title}"{year_str} pro katalog videoserveru prehraj.to.\n\n'
        f"{plot_label}\n---\n{plot}\n---\n\n"
        "Požadavky:\n"
        "- 3-6 vět, 150-400 znaků\n"
        "- Drž se pouze dějových informací z výše uvedeného textu — nic si nepřidávej ani nevymýšlej\n"
        "- Poutavý styl pro běžné diváky\n"
        "- Piš vlastními slovy, ne doslovný překlad/opis (žádné převzaté celé věty)\n"
        "- Piš přímo o ději a postavách, ne o filmu jako díle\n"
        "- Bez nadpisů, odrážek a poznámek\n\n"
        "Odpověz pouze samotným textem popisu:"
    )


def call_gemma(prompt: str, key_index: int, max_retries: int = 3):
    key = GEMINI_KEYS[key_index % len(GEMINI_KEYS)]
    url = GEMINI_URL_TPL.format(key)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "maxOutputTokens": 1000},
    }
    for attempt in range(max_retries):
        start = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=120)
            ms = int((time.time() - start) * 1000)
            if resp.status_code == 429:
                wait = RATE_LIMIT_PAUSE * (attempt + 1)
                print(f"    429 rate limit (key {key_index}), waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                return None, ms, f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            cands = data.get("candidates", [])
            if not cands:
                return None, ms, "No candidates (safety filter?)"
            parts = cands[0].get("content", {}).get("parts", [])
            if not parts:
                return None, ms, "No content parts"
            text = parts[0].get("text", "").strip()
            if not text:
                return None, ms, "Empty response"
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1].strip()
            return text, ms, None
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            return None, 0, str(e)
    return None, 0, "Max retries exceeded"


def load_records():
    with BACKLOG.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def save_records(records):
    tmp = BACKLOG.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(BACKLOG)


def main():
    ap = argparse.ArgumentParser(description="Generate unique Prehraj.to film descriptions via Gemma")
    ap.add_argument("--test", type=int, default=0, help="Test on N films (implies --dry-run)")
    ap.add_argument("--all", action="store_true", help="Process all pending")
    ap.add_argument("--limit", type=int, default=0, help="Limit to first N pending")
    ap.add_argument("--only-ids", type=str, default="", help="Comma-separated cr_film_id list")
    ap.add_argument("--dry-run", action="store_true", help="Don't write to JSONL, just print")
    ap.add_argument("--force", action="store_true", help="Regenerate even if prehrajto_description exists")
    args = ap.parse_args()

    if args.test > 0 and not args.dry_run:
        args.dry_run = True

    records = load_records()

    only_ids = set()
    if args.only_ids:
        only_ids = {int(x.strip()) for x in args.only_ids.split(",") if x.strip()}

    candidates = []
    for i, r in enumerate(records):
        if not args.force and r.get("prehrajto_description"):
            continue
        # Need at least ONE source of ground truth: tmdb_cs, tmdb_en, or existing description
        if not (r.get("tmdb_overview_cs") or r.get("tmdb_overview_en") or (r.get("description") or "").strip()):
            continue
        if only_ids and r.get("cr_film_id") not in only_ids:
            continue
        candidates.append(i)

    if args.test > 0:
        candidates = candidates[: args.test]
    elif args.limit > 0:
        candidates = candidates[: args.limit]
    elif not (args.all or only_ids):
        ap.print_help()
        return

    total = len(candidates)
    if not total:
        print("Nothing to process.")
        return

    print(f"Films to process: {total}")
    print(f"API keys: {len(GEMINI_KEYS)}")
    print(f"Batch size: {len(GEMINI_KEYS)}, pause: {PAUSE_BETWEEN_BATCHES}s, temperature: 0.9")
    if total > 10:
        est_batches = (total + len(GEMINI_KEYS) - 1) // len(GEMINI_KEYS)
        est_s = est_batches * (PAUSE_BETWEEN_BATCHES + 7)
        print(f"Estimated time: {est_s // 60}m {est_s % 60}s")
    print("Dry-run: {}".format("YES" if args.dry_run else "no (backlog will be updated)"), flush=True)
    print()

    ok = 0
    fail = 0
    start = time.time()

    for batch_start in range(0, total, len(GEMINI_KEYS)):
        batch_idx = candidates[batch_start : batch_start + len(GEMINI_KEYS)]
        with ThreadPoolExecutor(max_workers=len(GEMINI_KEYS)) as ex:
            futures = {}
            for i, rec_i in enumerate(batch_idx):
                r = records[rec_i]
                prompt = build_prompt(
                    r.get("title", ""),
                    r.get("year"),
                    r.get("tmdb_overview_cs", ""),
                    r.get("tmdb_overview_en", ""),
                    r.get("description", ""),
                )
                futures[ex.submit(call_gemma, prompt, i)] = rec_i
            for fut in as_completed(futures):
                rec_i = futures[fut]
                r = records[rec_i]
                text, ms, err = fut.result()
                label = f"{r.get('title','?')} ({r.get('year','?')}) [id={r.get('cr_film_id')}]"
                if err:
                    print(f"  FAIL: {label} — {err}", flush=True)
                    fail += 1
                else:
                    if not args.dry_run:
                        r["prehrajto_description"] = text
                    print(f"  OK: {label} → {len(text)} chars, {ms}ms", flush=True)
                    if args.dry_run:
                        print(f"       >>> {text[:240]}", flush=True)
                    ok += 1
        if not args.dry_run:
            save_records(records)
        done = ok + fail
        if done % 40 == 0 or done == total:
            elapsed = time.time() - start
            rate = done / elapsed * 3600 if elapsed > 0 else 0
            print(f"\n--- Progress: {done}/{total} ({ok} ok, {fail} fail, {rate:.0f}/h) ---\n", flush=True)
        if batch_start + len(GEMINI_KEYS) < total:
            time.sleep(PAUSE_BETWEEN_BATCHES)

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s ({elapsed / 60:.1f}m)")
    print(f"OK: {ok}, Failed: {fail}, Total: {total}")


if __name__ == "__main__":
    main()
