#!/usr/bin/env python3
"""Upload sktorrent external subtitle tracks to Přehraj.to.

Reverse-engineered endpoint:
    POST https://prehraj.to/profil/nahrana-videa?do=uploadedVideoListing-uploadSubtitles
    multipart/form-data:
        video = <prehrajto_video_id>
        files[] = <srt bytes>

Takes cr_film_id → sktorrent_subtitles (URL list) mapping from the backlog,
plus uploaded state for prehrajto_video_id, and uploads each track.

Sktorrent serves WEBVTT, but prehraj.to silently leaves WEBVTT uploads
in 'Zpracovává se' forever — only SRT input gets processed and re-served
as VTT from pp-storageN.premiumcdn.net. We therefore content-sniff every
fetched file and convert WEBVTT → SRT before POSTing.

Usage:
    PREHRAJTO_EMAIL=… PREHRAJTO_PASSWORD=… python3 src/upload_subtitles.py
    python3 src/upload_subtitles.py --only-ids 8103,9300 --dry-run
    python3 src/upload_subtitles.py --exclude-ids 17032,10750
"""
import argparse
import io
import json
import os
import re
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


def fetch_subtitle(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def detect_subtitle_format(content: bytes) -> tuple[str, str]:
    """Sniff actual format. Sktorrent serves WEBVTT under .vtt URLs; some
    sources mislabel formats. Returns (extension_with_dot, mime_type)."""
    head = content.lstrip(b"\xef\xbb\xbf").lstrip()
    if head[:6] == b"WEBVTT":
        return ".vtt", "text/vtt"
    if head.lower().startswith(b"[script info"):
        return ".ass", "text/x-ass"
    return ".srt", "application/x-subrip"


def vtt_to_srt(vtt_bytes: bytes) -> bytes:
    """Convert WEBVTT bytes to SRT. Required because prehraj.to's parser
    silently leaves WEBVTT uploads in 'Zpracovává se' indefinitely; only
    SRT input gets processed and re-served as VTT from pp-storage CDN.

    Strips any existing cue identifier line so the output is renumbered
    cleanly — sktorrent's VTTs include numeric cue ids that would
    otherwise produce `1\\n1\\n<timestamp>` and confuse strict parsers.
    Also drops trailing WEBVTT cue settings on the timestamp line.
    """
    text = vtt_bytes.lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n")
    # An interior BOM occasionally precedes the first cue (sktorrent does this).
    text = text.replace("﻿", "")
    lines = text.split("\n")
    if lines and lines[0].startswith("WEBVTT"):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    body = "\n".join(lines)
    body = re.sub(r"(\d{2}:\d{2}:\d{2})\.(\d{3})", r"\1,\2", body)
    ts_re = re.compile(
        r"^(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}).*$"
    )
    out: list[str] = []
    n = 1
    for blk in body.split("\n\n"):
        blk = blk.strip()
        if not blk or " --> " not in blk:
            continue
        blk_lines = blk.split("\n")
        if blk_lines and " --> " not in blk_lines[0]:
            blk_lines = blk_lines[1:]  # drop existing cue id / hint line
        if not blk_lines:
            continue
        m = ts_re.match(blk_lines[0])
        if m:
            blk_lines[0] = m.group(1)  # strip cue settings
        out.append(f"{n}\r\n" + "\r\n".join(blk_lines))
        n += 1
    return ("\r\n\r\n".join(out) + "\r\n").encode("utf-8")


def filename_from_url(url: str, ext: str) -> str:
    base = url.rsplit("/", 1)[-1] or "Cesky"
    for ex in (".vtt", ".srt", ".ass", ".ssa", ".sub"):
        if base.lower().endswith(ex):
            base = base[: -len(ex)]
            break
    return base + ext


def upload_one(
    session: requests.Session,
    video_id: int,
    content: bytes,
    filename: str,
    mime: str,
    *,
    dry_run: bool = False,
) -> tuple[bool, str]:
    if dry_run:
        return True, f"dry-run ({len(content)} B as {filename} mime={mime})"
    r = session.post(
        ENDPOINT,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://prehraj.to",
            "Referer": "https://prehraj.to/profil/nahrana-videa",
            "X-Requested-With": "XMLHttpRequest",
        },
        files=[
            ("files[]", (filename, content, mime)),
            ("video", (None, str(video_id))),
        ],
        timeout=60,
    )
    ok = r.status_code < 400
    short = r.text[:200].replace("\n", " ")
    return ok, f"status={r.status_code} body={short!r}"


VAR_TRACKS_RE = re.compile(r"var tracks = \[(.{0,4000}?)\];", re.DOTALL)


def verify_processed(
    session: requests.Session, slug_path: str, timeout: int = 15
) -> tuple[bool, str]:
    """GET the detail page and check whether `var tracks` is non-empty.
    POST returns 200 even when prehraj.to silently rejects the format;
    only the rendered detail page tells the truth."""
    if not slug_path:
        return False, "no slug"
    url = f"https://prehraj.to/{slug_path.lstrip('/')}"
    try:
        r = session.get(url, timeout=timeout)
    except Exception as e:
        return False, f"GET error: {e}"
    if r.status_code != 200:
        return False, f"status={r.status_code}"
    m = VAR_TRACKS_RE.search(r.text)
    if not m:
        return False, "no var tracks block"
    inner = m.group(1).strip()
    return bool(inner), f"tracks_len={len(inner)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-ids", type=str, default="")
    ap.add_argument("--exclude-ids", type=str, default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--verify-delay",
        type=float,
        default=8.0,
        help="Seconds to wait before GETting detail page to verify var tracks",
    )
    ap.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip post-upload var tracks verification",
    )
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

    ok = fail = unverified = 0
    posted_videos: dict[int, dict] = {}
    for cr, up, subs in plans:
        pv = up["prehrajto_video_id"]
        title = up.get("title", "?")
        any_posted = False
        for s in subs:
            url = s["url"]
            lang = s.get("lang")
            try:
                content = fetch_subtitle(url)
            except Exception as e:
                print(f"  cr={cr} {title!r} FAIL fetch {url}: {e}")
                fail += 1
                continue
            ext, mime = detect_subtitle_format(content)
            converted = ""
            if ext == ".vtt":
                content = vtt_to_srt(content)
                ext, mime = ".srt", "application/x-subrip"
                converted = " (vtt→srt)"
            fn = filename_from_url(url, ext)
            try:
                success, info = upload_one(session, pv, content, fn, mime)
            except Exception as e:
                print(f"  cr={cr} {title!r} FAIL upload: {e}")
                fail += 1
                continue
            status = "OK" if success else "FAIL"
            print(
                f"  cr={cr} pv={pv} {title!r} {lang} {fn}{converted} "
                f"→ {status} {info}"
            )
            if success:
                ok += 1
                any_posted = True
            else:
                fail += 1
            time.sleep(0.5)
        if any_posted:
            posted_videos[pv] = up

    if not args.no_verify and posted_videos and not args.dry_run:
        print()
        print(
            f"Verifying var tracks on {len(posted_videos)} videos "
            f"after {args.verify_delay:.0f}s grace…"
        )
        time.sleep(args.verify_delay)
        for pv, up in posted_videos.items():
            slug = up.get("prehrajto_slug_path") or ""
            processed, info = verify_processed(session, slug)
            mark = "OK" if processed else "EMPTY"
            print(
                f"  pv={pv} {up.get('title','?')!r} verify={mark} {info}"
            )
            if not processed:
                unverified += 1

    print()
    print(f"Done: ok={ok} fail={fail} unverified={unverified}")
    if fail:
        return 1
    if unverified and not args.no_verify:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
