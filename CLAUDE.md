# Pokyny pro Claude Code

Tenhle repo jsi otevřel po handoffu z předchozí session, která běžela v adresáři
`/home/jirka/streamtape/`. **Začni tím, že si přečteš tenhle soubor celý**, pak
si projdi `docs/`.

## Kontext projektu

Olbrasoft provozuje `ceskarepublika.wiki` (repo `~/GitHub/Olbrasoft/cr`). Potřebujeme
záložní zdroj filmů pro případ, že `sktorrent.eu` přestane fungovat. Proto stahujeme
filmy z jeho CDN a paralelně je nahráváme na náš účet na `prehraj.to` (česká cloudová
videoslužba podobná Uloz.to streamingu).

**Uživatel komunikuje česky**, technické věci (kód, commity, issues) anglicky.

## Co je hotové

### 1. Reverse-engineered Přehraj.to upload flow (3 HTTP kroky)

Plně funkční, otestované end-to-end bez prohlížeče. Viz [docs/upload-flow.md](docs/upload-flow.md).

- **Login**: `POST https://prehraj.to/?frm=homepageLoginForm-loginForm`
  - multipart, pole: `email`, `password`, `_do=homepageLoginForm-loginForm-submit`, `login=Přihlásit se`
  - **Vyžaduje priming GET na `/` předtím** (jinak session cookies neprojdou)
  - Odpověď: JSON `{"redirect":"https://prehraj.to/?afterLogin=1", ...}`
  - Set-Cookie: `_nss`, `access_token` (JWT ~10min), `refresh_token` (2 roky)
- **prepareVideo**: `POST https://prehraj.to/profil/nahrat-soubor?do=prepareVideo`
  - form-urlencoded: `name`, `size`, `type`, `erotic`, `folder`, `private`, `description`
  - Odpověď: JSON `{nonce, params, project, response, signature}`
- **Upload**: `POST https://api.premiumcdn.net/upload/`
  - multipart: všech 5 polí z prepare + soubor jako `file`
  - Hlavička `Referer: https://prehraj.to/` povinná
  - 201 Created = úspěch

### 2. Funkční Python skript

[src/prehrajto_upload.py](src/prehrajto_upload.py) — dostane cestu k MP4, přihlásí se
(env `PREHRAJTO_EMAIL` + `PREHRAJTO_PASSWORD`), nahraje soubor, vypíše `video_id`.

Ověřeno na 67 MB souboru → video se objevilo v profilu jako „Zpracovává se", detail
page dostupný přes permalink.

### 3. Testovací soubory k dispozici

V [test-assets/](test-assets/) máš dva reálné 720p filmy stažené ze sktorrentu
(celkem ~968 MB). **Jsou gitignorovány**, v repu nejsou, máš je jen lokálně. Takže
pro vývoj + testování uploadu nemusíš znova stahovat ze sktorrentu. Pokud potřebuješ
nový, stáhni další — viz `docs/sktorrent-sizes.md` pro seznam URL + velikostí.

### 4. Naming konvence

Finalizovaná, viz [docs/naming-convention.md](docs/naming-convention.md). Shrnutí:

    {Název filmu} ({rok}) HD CZ.mp4

Varianty: `... HD CZ titulky.mp4`, `... SD CZ.mp4` pro 480p.

### 5. Architektonické rozhodnutí

**Všechno na GitHubu, žádný hosting navíc.** Žádný Vercel, žádný VPS. GitHub Actions
cron na ubuntu-latest runneru (14 GB disk per job, 6h timeout) zvládne download + upload
jednoho filmu za ~5-10 minut. Detail: [docs/hosting-architecture.md](docs/hosting-architecture.md).

## Co zbývá udělat

Priority podle důležitosti:

### 🔴 Nutné před prvním produkčním během

1. **Test konektivity z GitHub runneru na `sktorrent.eu`** —
   GitHub runnery jsou v Azure USA, mohou být geo-blokovány. Nejdřív spustit
   [.github/workflows/test-sktorrent-access.yml](.github/workflows/test-sktorrent-access.yml)
   (manuální dispatch). Pokud 403, musí se použít self-hosted runner v ČR.

2. **Rotovat heslo k Přehraj.to** — heslo `JiriTuma19121976` bylo viděno při
   reverse-engineeringu. `~/Dokumenty/přístupy/prehrajto.md` má poznámku. Po rotaci
   update secretu v GitHubu.

3. **Přidat GitHub Secrets** — `PREHRAJTO_EMAIL`, `PREHRAJTO_PASSWORD` do
   `Olbrasoft/prehrajto-sync` → Settings → Secrets and variables → Actions.

### 🟡 Hlavní implementace

4. **`src/check_missing.py`** — input: seznam filmů ze sktorrent (URL +
   název + rok), výstup: ty co ještě nejsou v `state/uploaded.json`. Uživatel ve
   vedlejší session generuje kompletní sktorrent backlog (mluvil o „9254 kandidátech,
   15.9% verified"), ten sem přijde jako `backlog/sktorrent-films.json` nebo podobně.

5. **`src/rename_for_prehrajto.py`** (nebo funkce) — z metadat filmu (název + rok)
   vyrobí filename podle [docs/naming-convention.md](docs/naming-convention.md).

6. **Hlavní workflow `.github/workflows/sync.yml`** —
   - `schedule: '0 */6 * * *'` (každých 6 h) + `workflow_dispatch`
   - Ubuntu-latest, 30 min timeout
   - Steps: checkout → install python-requests → python check_missing.py
     → curl (download do `/tmp/`) → python prehrajto_upload.py → commit state

7. **`state/uploaded.json`** — {
     "sktorrent_id": 56413,
     "url": "https://online8.sktorrent.eu/.../56413_720p.mp4",
     "prehrajto_video_id": 23956301,
     "prehrajto_slug": "lvi-kral-...",
     "uploaded_at": "2026-04-18T..."
   }

### 🟢 Hezké mít, ne blokující

8. **Nový dedikovaný Přehraj.to účet** — ne na claudecode@gmail.com. Vytvořit
   `olbrasoft-prehrajto-bot@gmail.com` nebo podobně, upgrade na Premium (159 Kč/měs)
   kvůli neomezené rychlosti uploadu.

9. **Status dashboard** — volitelně malý Next.js/Svelte web na Vercel Hobby, jen
   UI co čte `state/uploaded.json` přes raw.githubusercontent.com. Žádná cron logika,
   jen readonly statistika "co kdy nahráno".

10. **Polling `Zpracovává se` → `Online`** — po uploadu video na prehraj.to chvíli
    transkóduje. Pipeline může volitelně čekat, než bude hotové, aby do state zapsal
    i ověřený slug. (Nekritické — slug se dá získat i z `/profil/nahrana-videa`
    později.)

## Konvence

- Jazyk kódu a commitů: **anglicky**.
- Jazyk s uživatelem: **česky**.
- **GitHub issues** vždy přes skill `github-issues` (viz user-level `~/.claude/CLAUDE.md`).
- Před commitem a PR si přečti `~/GitHub/Olbrasoft/engineering-handbook/`.
- Všechny PRs musí mít Claude session marker na začátku body (viz user-level CLAUDE.md).

## Důležité předchozí dokumenty (pro hlubší kontext)

V `/home/jirka/streamtape/` (původní pískoviště) jsou tyto analytické dokumenty,
které dávají plný kontext. **Nečti je všechny hned, jen když potřebuješ dopad:**

- `/home/jirka/streamtape/PREHRAJTO-COMPLETE-FLOW.md` — nejdůležitější, detail HTTP
  flow (byla zdrojem pro `docs/upload-flow.md` tady).
- `/home/jirka/streamtape/PREHRAJTO-ANALYZA-2026-04-18.md` — celkový přehled Přehraj.to,
  co umí, co ne, právní rámec.
- `/home/jirka/streamtape/STREAMTAPE-LIMITY-A-PODMINKY.md` + `ALTERNATIVY-KE-STREAMTAPE.md`
  — historie, proč jsme opustili StreamTape. Pro tento projekt přímo irelevantní,
  ale vysvětluje motivaci.

## Typické debugging tipy

- **Login vrací 200 + `{"redirect":"https://prehraj.to/"}` (ne `/?afterLogin=1`)** →
  zapomněl jsi priming GET. Login tiše selže.
- **Upload vrátí 403 / 401** → expiroval access_token (~10 min JWT). Refresh token
  se obnoví automaticky při jakémkoli requestu s validním refresh_token.
- **CDN upload 413 Request Entity Too Large** → ověřit že posíláš multipart správně,
  ne raw binary.
- **Video se nikdy nezpracuje** (zůstává „Zpracovává se" hodiny) → Přehraj.to
  ignoruje velmi malé soubory (< ~10 kB). Použij test-assets/ soubory.

## Na co se zeptat uživatele

- Kdy bude dedikovaný bot účet? (teď testujeme na `olbrasoft.claudecode@gmail.com`)
- Kdy dá sktorrent backlog? (generuje ho vedlejší session)
- Preferuje private nebo public repo? (teď private)
