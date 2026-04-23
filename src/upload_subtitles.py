#!/usr/bin/env python3
"""Upload sktorrent external .vtt subtitle tracks to Přehraj.to.

Reverse-engineered endpoint:
    POST https://prehraj.to/profil/nahrana-videa?do=uploadedVideoListing-uploadSubtitles
    multipart/form-data:
        video = <prehrajto_video_id>
        files[] = <vtt bytes>

Takes cr_film_id → sktorrent_subtitles (URL list) mapping from the backlog,
plus uploaded state for prehrajto_video_id, and uploads each .vtt track.
Runs on processed videos; if Přehraj.to hasn't finished transcoding yet
the request still usually accepts, subtitles become active once the video
goes live.

Usage:
    PREHRAJTO_EMAIL=… PREHRAJTO_PASSWORD=… python3 src/upload_subtitles.py
    python3 src/upload_subtitles.py --only-ids 8103,9300 --dry-run
    python3 src/upload_subtitles.py --exclude-ids 17032,10750
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prehrajto_upload import login  # noqa: E402


REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "backlog" / "sktorrent-films.jsonl"
STATE = REPO / "state" / "uploaded.json"
ENDPOINT = (
    "https://prehraj.to/profil/nahrana-videa"
    "?do=uploadedVideoListing-uploadSubtitles"
)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def fetch_vtt(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def filename_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1] or "Cesky.vtt"


def upload_one(
    session: requests.Session,
    video_id: int,
    vtt_bytes: bytes,
    filename: str,
    *,
    dry_run: bool = False,
) -> tuple[bool, str]:
    if dry_run:
        return True, f"dry-run ({len(vtt_bytes)} B as {filename})"
    r = session.post(
        ENDPOINT,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://prehraj.to",
            "Referer": "https://prehraj.to/profil/nahrana-videa",
            "X-Requested-With": "XMLHttpRequest",
        },
        files=[
            ("files[]", (filename, vtt_bytes, "text/vtt")),
            ("video", (None, str(video_id))),
        ],
        timeout=60,
    )
    ok = r.status_code < 400
    short = r.text[:200].replace("\n", " ")
    return ok, f"status={r.status_code} body={short!r}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-ids", type=str, default="")
    ap.add_argument("--exclude-ids", type=str, default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    only = {int(x) for x in args.only_ids.split(",") if x.strip()}
    excl = {int(x) for x in args.exclude_ids.split(",") if x.strip()}

    state = json.loads(STATE.read_text())
    uploads_by_cr = {u["cr_film_id"]: u for u in state.get("uploads", [])}

    plans = []
    for line in BACKLOG.open():
        if not line.strip():
            continue
        r = json.loads(line)
        cr = r.get("cr_film_id")
        subs = r.get("sktorrent_subtitles") or []
        if not subs:
            continue
        if only and cr not in only:
            continue
        if cr in excl:
            continue
        up = uploads_by_cr.get(cr)
        if not up:
            print(f"  cr={cr} SKIP — not in state/uploaded.json", file=sys.stderr)
            continue
        plans.append((cr, up, subs))

    if not plans:
        print("Nothing to upload.")
        return 0

    total_tracks = sum(len(s) for _, _, s in plans)
    print(f"Plan: {len(plans)} films, {total_tracks} subtitle track(s) total")
    for cr, up, subs in plans:
        for s in subs:
            print(f"  cr={cr} pv={up['prehrajto_video_id']} "
                  f"lang={s.get('lang')} url={s['url']}")

    if args.dry_run:
        print("--dry-run; not logging in, nothing posted.")
        return 0

    email = os.environ.get("PREHRAJTO_EMAIL")
    password = os.environ.get("PREHRAJTO_PASSWORD")
    if not email or not password:
        print("ERROR: PREHRAJTO_EMAIL / PREHRAJTO_PASSWORD missing", file=sys.stderr)
        return 2

    print()
    print("Logging in…")
    session = login(email, password)

    ok = fail = 0
    for cr, up, subs in plans:
        pv = up["prehrajto_video_id"]
        title = up.get("title", "?")
        for s in subs:
            url = s["url"]
            lang = s.get("lang")
            try:
                vtt = fetch_vtt(url)
            except Exception as e:
                print(f"  cr={cr} {title!r} FAIL fetch {url}: {e}")
                fail += 1
                continue
            fn = filename_from_url(url)
            try:
                success, info = upload_one(session, pv, vtt, fn)
            except Exception as e:
                print(f"  cr={cr} {title!r} FAIL upload: {e}")
                fail += 1
                continue
            status = "OK" if success else "FAIL"
            print(f"  cr={cr} pv={pv} {title!r} {lang} {fn} → {status} {info}")
            if success:
                ok += 1
            else:
                fail += 1
            time.sleep(0.5)

    print()
    print(f"Done: ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
