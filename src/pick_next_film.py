#!/usr/bin/env python3
"""Vybere další film z backlogu, který ještě není na Přehraj.to.

Vstup: backlog/sktorrent-films.jsonl + state/uploaded.json
Výstup: GITHUB_OUTPUT (sktorrent_url, film_name, film_description, cr_film_id, sktorrent_id, cr_slug, year)
        nebo exit 1 + log "no more films" (workflow skončí cleanly).

Pořadí: backlog už je seřazený podle priority_score desc — bereme první "fresh" záznam.
"""
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG = REPO_ROOT / "backlog" / "sktorrent-films.jsonl"
STATE = REPO_ROOT / "state" / "uploaded.json"


def main() -> int:
    if not BACKLOG.is_file():
        print(f"ERROR: backlog neexistuje: {BACKLOG}", file=sys.stderr)
        return 2
    if not STATE.is_file():
        print(f"ERROR: state neexistuje: {STATE}", file=sys.stderr)
        return 2

    state = json.loads(STATE.read_text())
    done_ids = {u["cr_film_id"] for u in state.get("uploads", [])}
    skipped_ids = {u["cr_film_id"] for u in state.get("moderated_out", [])}
    excluded = done_ids | skipped_ids
    print(f"[pick] state: {len(done_ids)} hotovo, {len(skipped_ids)} moderated_out")

    rows = [
        json.loads(line)
        for line in BACKLOG.read_text().splitlines()
        if line.strip()
    ]
    print(f"[pick] backlog: {len(rows)} kandidátů")

    pick = next(
        (r for r in rows if r.get("cr_film_id") not in excluded),
        None,
    )
    if pick is None:
        print("[pick] žádný film k nahrání — backlog vyčerpán")
        return 1

    name = f"{pick['title']} ({pick['year']}) HD CZ"
    description = pick.get("description") or ""
    print(f"[pick] vybrán: cr_film_id={pick['cr_film_id']}, '{name}'")
    print(f"[pick] sktorrent_url={pick['url']}")
    print(f"[pick] description ({len(description)} znaků): {description[:120]}...")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"sktorrent_url={pick['url']}\n")
            f.write(f"film_name={name}\n")
            # Multi-line popis: heredoc syntax pro GITHUB_OUTPUT
            f.write("film_description<<EOF_DESC\n")
            f.write(description + "\n")
            f.write("EOF_DESC\n")
            f.write(f"cr_film_id={pick['cr_film_id']}\n")
            f.write(f"cr_slug={pick['cr_slug']}\n")
            f.write(f"sktorrent_id={pick['id']}\n")
            f.write(f"year={pick['year']}\n")
            f.write(f"title={pick['title']}\n")
        print(f"[pick] zapsáno do GITHUB_OUTPUT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
