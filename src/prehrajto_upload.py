#!/usr/bin/env python3
"""Přehraj.to — end-to-end upload bez prohlížeče.

Spuštění:
    export PREHRAJTO_EMAIL=...
    export PREHRAJTO_PASSWORD=...
    python3 prehrajto_upload.py /path/to/video.mp4
"""
import json
import os
import sys
from pathlib import Path
import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0 Safari/537.36 Edg/145.0"
)


def login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT

    # Prime the session — visit homepage to get initial Nette cookies (csrf, session)
    prime = s.get("https://prehraj.to/")
    print(f"[login] prime GET status={prime.status_code}, cookies={dict(s.cookies)}")

    r = s.post(
        "https://prehraj.to/?frm=homepageLoginForm-loginForm",
        files={
            "email": (None, email),
            "password": (None, password),
            "_do": (None, "homepageLoginForm-loginForm-submit"),
            "login": (None, "Přihlásit se"),
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "Referer": "https://prehraj.to/",
        },
        allow_redirects=False,
    )
    print(f"[login] status={r.status_code}, ctype={r.headers.get('content-type')}")
    print(f"[login] response text (first 500): {r.text[:500]!r}")
    print(f"[login] set-cookie headers: {r.headers.get('set-cookie')!r}")
    print(f"[login] session cookies after login: {dict(s.cookies)}")
    r.raise_for_status()

    check = s.get("https://prehraj.to/profil", allow_redirects=False)
    print(f"[login] /profil check status={check.status_code}")
    if check.status_code != 200:
        raise RuntimeError(f"Login failed — /profil vrací {check.status_code}")
    print(f"[login] OK, {len(s.cookies)} cookies uloženo")
    return s


def upload_video(session: requests.Session, path: Path, *, private: bool = True) -> int:
    size = path.stat().st_size
    print(f"[upload] Soubor: {path.name} ({size} B)")

    print(f"[upload] Krok 1: prepareVideo")
    prep = session.post(
        "https://prehraj.to/profil/nahrat-soubor?do=prepareVideo",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "*/*",
        },
        data={
            "description": "",
            "name": path.name,
            "size": str(size),
            "type": "video/mp4",
            "erotic": "false",
            "folder": "",
            "private": "true" if private else "false",
        },
    )
    print(f"[upload] prepareVideo status={prep.status_code}")
    prep.raise_for_status()
    prep_data = prep.json()
    print(f"[upload] prepare response: {prep_data}")
    video_id = json.loads(prep_data["params"])["video_id"]
    print(f"[upload] video_id={video_id}")

    print(f"[upload] Krok 2: upload na api.premiumcdn.net")
    with path.open("rb") as fh:
        r = requests.post(
            "https://api.premiumcdn.net/upload/",
            headers={
                "Referer": "https://prehraj.to/",
                "User-Agent": USER_AGENT,
            },
            data={
                "nonce": prep_data["nonce"],
                "params": prep_data["params"],
                "project": prep_data["project"],
                "response": prep_data["response"],
                "signature": prep_data["signature"],
            },
            files={"file": (path.name, fh, "video/mp4")},
            timeout=3600,
        )
    print(f"[upload] CDN status={r.status_code}")
    print(f"[upload] CDN response: {r.text[:300]!r}")
    r.raise_for_status()

    return video_id


def main() -> int:
    email = os.environ.get("PREHRAJTO_EMAIL")
    password = os.environ.get("PREHRAJTO_PASSWORD")
    if not email or not password:
        print("ERROR: Chybí PREHRAJTO_EMAIL nebo PREHRAJTO_PASSWORD v env")
        return 2
    if len(sys.argv) != 2:
        print(f"Použití: {sys.argv[0]} /path/to/video.mp4")
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"ERROR: soubor neexistuje: {path}")
        return 2

    session = login(email, password)
    video_id = upload_video(session, path, private=True)
    print(f"\n=== HOTOVO ===")
    print(f"video_id: {video_id}")
    print(f"Zkontroluj v profilu: https://prehraj.to/profil/nahrana-videa?filterIsPrivate=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
