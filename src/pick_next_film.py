#!/usr/bin/env python3
"""Vybere další film z backlogu, který ještě není na Přehraj.to.

Používá se ze dvou míst:
1. CLI (jednorázově) — zapíše vybraný řádek do GITHUB_OUTPUT.
2. Importem ze `sync_batch.py` — funkce `pick_next()` vrací dict / None.

Vstup: backlog/sktorrent-films.jsonl + state/uploaded.json
Pořadí: backlog je seřazený podle priority_score desc.
"""
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG = REPO_ROOT / "backlog" / "sktorrent-films.jsonl"
STATE = REPO_ROOT / "state" / "uploaded.json"


def load_backlog(path: Path = BACKLOG) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def load_state(path: Path = STATE) -> dict:
    return json.loads(path.read_text())


def excluded_ids(state: dict, extra: set[int] | None = None) -> set[int]:
    """cr_film_id které vynecháme: uploaded + moderated_out + dočasné `extra`
    (např. už vybrané v aktuální batch dávce, ale ještě nezapsané do state)."""
    done = {u["cr_film_id"] for u in state.get("uploads", [])}
    skipped = {u["cr_film_id"] for u in state.get("moderated_out", [])}
    return done | skipped | (extra or set())


def _require_cs_audio() -> bool:
    v = os.environ.get("REQUIRE_CS_AUDIO", "true").strip().lower()
    return v not in ("0", "false", "no", "off")


def pick_next(
    state: dict,
    backlog_rows: list[dict],
    extra_exclude: set[int] | None = None,
) -> dict | None:
    excluded = excluded_ids(state, extra_exclude)
    require_cs = _require_cs_audio()
    for r in backlog_rows:
        if r.get("cr_film_id") in excluded:
            continue
        if require_cs and r.get("detected_language") != "cs":
            continue
        return r
    return None


NATIVE_ORIGINS = {"cs", "sk"}


def display_name(film: dict) -> str:
    title = film["title"]
    year = film["year"]
    orig = film.get("original_language")
    # Native (Czech/Slovak) or unknown title (TMDB miss) → no "Dabing" label.
    # Everything else with Czech audio is dubbing.
    if orig in NATIVE_ORIGINS or orig is None:
        return f"{title} ({year}) CZ"
    return f"{title} ({year}) CZ Dabing"


def main() -> int:
    if not BACKLOG.is_file():
        print(f"ERROR: backlog neexistuje: {BACKLOG}", file=sys.stderr)
        return 2
    if not STATE.is_file():
        print(f"ERROR: state neexistuje: {STATE}", file=sys.stderr)
        return 2

    state = load_state()
    rows = load_backlog()
    excluded = excluded_ids(state)
    print(f"[pick] state: {len(state.get('uploads', []))} hotovo, "
          f"{len(state.get('moderated_out', []))} moderated_out")
    print(f"[pick] backlog: {len(rows)} kandidátů")

    pick = pick_next(state, rows)
    if pick is None:
        print("[pick] žádný film k nahrání — backlog vyčerpán")
        return 1

    name = display_name(pick)
    description = pick.get("description") or ""
    print(f"[pick] vybrán: cr_film_id={pick['cr_film_id']}, '{name}'")
    print(f"[pick] sktorrent_url={pick['url']}")
    print(f"[pick] description ({len(description)} znaků): {description[:120]}...")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"sktorrent_url={pick['url']}\n")
            f.write(f"film_name={name}\n")
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
