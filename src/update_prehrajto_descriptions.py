#!/usr/bin/env python3
"""Update the Prehraj.to name + description for videos we've already uploaded.

The UI on /profil/nahrana-videa ships each row with an inline edit form.
Saving the form fires this AJAX GET:

    /profil/nahrana-videa
        ?uploadedVideoListing-videoId=<VIDEO_ID>
        &do=uploadedVideoListing-changeVideoNameAndVideoDescription
        &uploadedVideoListing-name=<URL-ENCODED NAME>
        &uploadedVideoListing-desc=<URL-ENCODED DESC>

Headers: X-Requested-With=XMLHttpRequest, Accept=application/json, session cookies.

This script:
1. Loads state/uploaded.json → (cr_film_id, prehrajto_video_id) pairs
2. Loads backlog → current prehrajto_description + display_name(film)
3. Logs into Prehraj.to (same credentials as sync batch)
4. For each upload: PATCH name + description via the endpoint above
5. Logs result, records success/fail per video

Run:
    PREHRAJTO_EMAIL=... PREHRAJTO_PASSWORD=... \\
        python3 src/update_prehrajto_descriptions.py [--only-ids 49,168] [--dry-run]
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_next_film import display_name
from prehrajto_upload import login

import requests


REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "backlog" / "sktorrent-films.jsonl"
STATE = REPO / "state" / "uploaded.json"
LOG = REPO / "state" / "desc_updates.log"

EDIT_URL = "https://prehraj.to/profil/nahrana-videa"


def log(msg: str) -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def change_description(session: requests.Session, video_id: int, name: str, desc: str, timeout: int = 30) -> tuple[bool, str]:
    params = {
        "uploadedVideoListing-videoId": str(video_id),
        "do": "uploadedVideoListing-changeVideoNameAndVideoDescription",
        "uploadedVideoListing-name": name,
        "uploadedVideoListing-desc": desc,
    }
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        "Referer": "https://prehraj.to/profil/nahrana-videa",
    }
    r = session.get(EDIT_URL, params=params, headers=headers, timeout=timeout, allow_redirects=False)
    return r.status_code == 200, f"http={r.status_code} len={len(r.text)}"


def load_backlog() -> dict[int, dict]:
    out = {}
    with BACKLOG.open() as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            out[r["cr_film_id"]] = r
    return out


def load_state() -> dict:
    return json.loads(STATE.read_text())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-ids", type=str, default="", help="Comma-separated cr_film_id list")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Only update first N")
    ap.add_argument("--throttle", type=float, default=0.5, help="Seconds between requests")
    args = ap.parse_args()

    only_ids: set[int] = set()
    if args.only_ids:
        only_ids = {int(x.strip()) for x in args.only_ids.split(",") if x.strip()}

    email = os.environ.get("PREHRAJTO_EMAIL")
    password = os.environ.get("PREHRAJTO_PASSWORD")
    if not email or not password:
        print("ERROR: PREHRAJTO_EMAIL / PREHRAJTO_PASSWORD not set", file=sys.stderr)
        return 2

    state = load_state()
    backlog = load_backlog()

    tasks = []
    for u in state.get("uploads", []):
        cid = u["cr_film_id"]
        if only_ids and cid not in only_ids:
            continue
        film = backlog.get(cid)
        if not film:
            log(f"SKIP cr_film_id={cid} — not in backlog anymore")
            continue
        new_name = display_name(film)
        new_desc = film.get("prehrajto_description") or film.get("description") or ""
        if not new_desc:
            log(f"SKIP cr_film_id={cid} — no description available")
            continue
        tasks.append({
            "cr_film_id": cid,
            "video_id": u["prehrajto_video_id"],
            "title": film["title"],
            "year": film["year"],
            "name": new_name,
            "desc": new_desc,
        })

    if args.limit > 0:
        tasks = tasks[: args.limit]

    log(f"step=start tasks={len(tasks)} dry_run={args.dry_run}")
    if not tasks:
        log("nothing to update")
        return 0

    if args.dry_run:
        for t in tasks[:5]:
            print(f"DRY: video_id={t['video_id']}  name={t['name']}")
            print(f"     desc ({len(t['desc'])} chars): {t['desc'][:200]}...")
        print(f"(showing 5 of {len(tasks)})")
        return 0

    log("step=login")
    session = login(email, password)
    log("step=login done")

    ok = fail = 0
    start = time.time()
    for i, t in enumerate(tasks, 1):
        success, info = change_description(session, t["video_id"], t["name"], t["desc"])
        if success:
            ok += 1
            if i <= 5 or i % 25 == 0:
                log(f"OK {i}/{len(tasks)} cr_film_id={t['cr_film_id']} video={t['video_id']} '{t['name']}' {info}")
        else:
            fail += 1
            log(f"FAIL {i}/{len(tasks)} cr_film_id={t['cr_film_id']} video={t['video_id']} '{t['name']}' {info}")
        if args.throttle > 0 and i < len(tasks):
            time.sleep(args.throttle)

    dur = round(time.time() - start, 1)
    log(f"step=done tasks={len(tasks)} ok={ok} fail={fail} dur={dur}s")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
