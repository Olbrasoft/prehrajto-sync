# Backlog

Seznam filmů ze `sktorrent.eu`, které **nemáme** na našem Přehraj.to účtu a jsou
kandidáti na mirror.

## Soubory

- **`sktorrent-films.jsonl`** — pracovní fronta pro `src/check_missing.py`.
  1014 řádků (NONE verdict — na přehraj.to zatím nic, a my máme sktorrent
  video_id + quality, takže jde rovnou stáhnout). JSONL formát, jedna entita
  na řádek:

  ```jsonl
  {"id": 56413, "title": "Lví král", "year": 1994, "quality": "720p", "cr_film_id": 49, "cr_slug": "lvi-kral", "has_dub": true, "has_subtitles": true, "priority_score": 16.9, "imdb_id": "tt0110357", "csfd_id": "24537", "url": "https://online.sktorrent.eu/media/videos//h264/56413_720p.mp4"}
  ```

  Řazeno sestupně podle `priority_score` (kompozit csfd/10 + imdb s
  ignorem imdb ≥ 9.5 jako single-vote šum; tiebreaker year DESC).

  `id` = sktorrent_video_id (pro download URL). `cr_film_id` + `cr_slug` =
  náš DB identifikátor, pro zpětné spárování po uploadu.

  CDN hostname v `url` je `online.sktorrent.eu` jako placeholder —
  SK Torrent CDN rotuje, sync tool musí resolvovat edge node naživo
  (`online1..30.sktorrent.eu/media/videos//h264/{id}_{quality}.mp4`,
  HEAD probe, vrátí první 200/206). Viz `cr-web/src/handlers/films.rs`
  v Olbrasoft/cr — `scan_sktorrent_cdns`.

- **`audit/sktorrent-films-verified.csv`** — kompletní audit ke dni
  2026-04-18. 9254 filmů v ČR DB, které mají sktorrent_video_id ale
  `prehrajto_url IS NULL`. Každému byl živě dotazován `prehraj.to/hledej`
  a vyplněn `prehrajto_verdict`:

  | verdict | count | význam |
  |---------|------:|--------|
  | FOUND   | 7386 (79.8 %) | film na přehraj.to už JE — naše DB je stale, stačí enrich |
  | NONE    | 1094 (11.8 %) | film skutečně chybí → `sktorrent-films.jsonl` (1014 z toho má video_id + quality) |
  | MAYBE   |  591 (6.4 %)  | jen title sedí, délka ne/chybí — manuální ověření |
  | LIKELY  |  177 (1.9 %)  | délka sedí, title ne — možná překlad / jiná verze |
  | ERR     |    6 (0.1 %)  | HTTP chyba při ověření, zkus znovu |

  Skript co to generoval: `scripts/verify-prehrajto-missing.py` v
  Olbrasoft/cr. Slouží jen jako audit archiv — pracovní fronta je JSONL.

## Update procedura

Až doběhne další enrich / scan:

1. V Olbrasoft/cr: `scripts/list-sktorrent-only-films.sh` → nový CSV
2. `scripts/verify-prehrajto-missing.py` → doplní verdict sloupce
3. Převod NONE řádků na JSONL + upload sem

Zatímco audit CSV je zamrzlý snapshot, JSONL se postupně krátí (jak
upload do přehraj.to běží a filmy se odmazávají po úspěšném nahrání).
