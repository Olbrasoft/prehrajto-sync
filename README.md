# prehrajto-sync

Automatická synchronizace filmů **sktorrent.eu → Přehraj.to**.

Detekuje filmy, které jsou na `sktorrent.eu`, ale zatím **nejsou** na našem Přehraj.to
účtu, stáhne je a nahraje je tam. Cílem je mít u nás **záložní zdroj**, kdyby sktorrent
zmizel nebo byl zablokován.

## Architektura

```
┌─ GitHub Actions cron (ubuntu-latest, 14 GB disk) ─────────┐
│                                                           │
│  1. git clone prehrajto-sync                              │
│  2. python check_missing.py  →  next film URL             │
│  3. curl   → /tmp/film.mp4   (ze sktorrent.eu CDN)        │
│  4. python prehrajto_upload.py /tmp/film.mp4              │
│     ├─ login (multipart POST)                             │
│     ├─ prepareVideo (form POST, vrací nonce+signature)    │
│     └─ upload (multipart POST → api.premiumcdn.net)       │
│  5. git commit state/uploaded.json + push                 │
│  6. VM se smaže, disk zmizí                               │
└───────────────────────────────────────────────────────────┘
```

**Kompletně bez externího hostingu** — žádný Vercel, žádné VPS. Jen GitHub.

Detail: [docs/hosting-architecture.md](docs/hosting-architecture.md)

## Quickstart (pro nové Claude Code session)

1. **Přečti [CLAUDE.md](CLAUDE.md)** — kompletní handoff co je hotové a co chybí.
2. **Hesla / přístupy** — `~/Dokumenty/přístupy/prehrajto.md` (testovací účet).
3. **Funkční upload skript** — [src/prehrajto_upload.py](src/prehrajto_upload.py),
   ověřený end-to-end na 67 MB souboru (viz [docs/upload-flow.md](docs/upload-flow.md)).
4. **Předpřipravené test filmy** — `test-assets/` (gitignored, ~968 MB), ušetří
   ti re-download ze sktorrentu.
5. **Naming konvence** pro uploady — [docs/naming-convention.md](docs/naming-convention.md).

## Co zbývá

- Wire up GitHub Actions workflow (`.github/workflows/sync.yml`)
- Test konektivity z GitHub runneru na `sktorrent.eu` (geo-block check)
- `check_missing.py` — input: sktorrent backlog; output: co ještě chybí na Přehraj.to
- Přesun z testovacího účtu `olbrasoft.claudecode@gmail.com` na dedikovaný bot account

## Licence

Interní projekt Olbrasoft. Žádná veřejná licence.
