# Sktorrent.eu — velikosti souborů (ověření)

Benchmark z 2026-04-18. Cíl: zjistit, s jakou velikostí souborů budeme
reálně pracovat v pipeline.

## URL formát

```
https://online{N}.sktorrent.eu/media/videos//h264/{VID}_{QUALITY}.mp4
```

- `N` = 1..25 (CDN node, distribuce podle hashů)
- `VID` = numerické ID filmu v sktorrent DB
- `QUALITY` = `480p`, `720p`, případně `1080p` (podle toho co tam je)

Žádná autentizace nutná, **GET je anonymní**, `Referer: https://sktorrent.eu/`
a běžný `User-Agent` stačí.

## Naměřené velikosti (10-sample)

| # | Film | Kvalita | Content-Length |
|---|------|---------|----------------|
| 7 | Tonda, Slávka a kouzelné světlo (2023) | 720p | 436 MB |
| 10 | Hrdina (2021) | 480p | 501 MB |
| 5 | DJ Ahmet (2025) | 720p | 510 MB |
| 1 | Lví král (1994) | 720p | 531 MB |
| 3 | Medvěd (1988) | 720p | 677 MB |
| 6 | Bláznivá střela 2½ (1991) | 720p | 696 MB |
| 4 | Přátelé: Zase spolu (2021) | 720p | 740 MB |
| 2 | Umění létat 3D (2011) | 720p | 886 MB |
| 8 | Anatomie pádu (2023) | 720p | 895 MB |
| 9 | Mission: Impossible Odplata – 1. část (2023) | 720p | 1198 MB |

**Průměr: 707 MB** (720p). **Medián: 687 MB**. **Rozsah: 436 MB – 1.2 GB**.

## Download rychlost

Z jedné CDN nody (`online8.sktorrent.eu`, test Lví král 531 MB):

- **148 s pro 531 MB = 3.6 MB/s = ~29 Mbit/s**
- To je strop sktorrent CDN, ne naší linky (plně sycený upload by
  měl víc).

## Dostupné testovací soubory lokálně

V `test-assets/` máš připraveno (gitignored):

```
tonda-slavka-2023-720p.mp4     436 MB
lvi-kral-1994-720p.mp4         532 MB
```

Tyhle **už nemusíš znova stahovat** ze sktorrentu. Stačí je použít pro
testování uploadu do Přehraj.to.

## Co ještě ne-známo

- Je tam **1080p** dostupné pro novější filmy? Odpovídá „nejvyšší kvalita
  v titulku na webu sktorrent = HTTP URL se stejným suffixem 1080p"? Nebo
  to dělají transkodingem až při požadavku?
  - Empiricky jsme testovali 25 nod pro Matrix 1999, žádná nevrátila 1080p
    URL. Ale možná jen Matrix, pro novější filmy být může.
- Existuje **H.265** varianta? URL obsahuje `/h264/`, takže možná existuje
  i `/h265/` path pro nové filmy?
- Jak dlouho zůstávají URL platné? Máme pocit že trvalé, ale neověřeno na
  delší časovou vzdálenost.

## Důsledek pro design pipeline

- **14 GB runner disk** je víc než dost pro 1 film naráz (max 1.2 GB).
- **Streamovat download → upload bez ukládání na disk** by šlo, ale není
  to nutné — `/tmp/film.mp4` přežije dobu jobu v pohodě.
- **Jeden film = cca 5-10 min pipeline** = ~8 filmů/hodinu, ~200 filmů/den
  kdyby běžel cron každou hodinu. Backlog 9 000 kandidátů → ~45 dní na
  plnou synchronizaci.
