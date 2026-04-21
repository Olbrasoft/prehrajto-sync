# Naming konvence pro uploady na Přehraj.to

Finální rozhodnutí pro pojmenování souborů, které nahráváme na náš účet.

## Formát

    {Název filmu} ({rok}) CZ.mp4           # původní jazyk filmu je čeština/slovenština
    {Název filmu} ({rok}) CZ Dabing.mp4    # cizí film s českým dabingem

Rozhodování dělá `src/pick_next_film.py:display_name()` podle pole
`original_language` (z TMDB, doplňuje `src/enrich_origin_language.py`):
- `cs` nebo `sk` (nebo chybějící TMDB záznam) → `CZ`
- cokoli jiného → `CZ Dabing`

Sufix `HD` jsme odstranili — Přehraj.to si přidává badge „HD" na kartě
sám podle rozlišení streamu (≥ 720p), takže v názvu je redundantní.

## Příklady

```
Kameňák (2003) CZ.mp4                     # český film
Princezna zakletá v čase (2020) CZ.mp4    # český film
Lví král (1994) CZ Dabing.mp4             # US film s CZ dabingem
Medvěd (1988) CZ Dabing.mp4               # FR film s CZ dabingem
Oppenheimer (2023) CZ Dabing.mp4          # US film s CZ dabingem
```

## Varianty

- **SD kvalita (480p, výjimečně)**: `{Název} ({rok}) CZ SD.mp4` (zatím nepoužíváme)

## Co jsme zjistili měřením přímo na Přehraj.to

Pustili jsme několik existujících variant Matrixu (1999) přes Playwright a
u každého jsme změřili skutečné `videoWidth × videoHeight` streamu (ne to,
co je napsáno v názvu uploadu).

| Název uploadu | Velikost | Co player ve skutečnosti posílá |
|---------------|----------|----------------------------------|
| „Matrix 1 (The Matrix 1999) 4K! h265 CZ" | 13.47 GB | 1080p + 720p |
| „matrix-1-the-matrix-1999-4k-h265-cz.mp4" | 14.99 GB | jen 720p — navzdory „4K" |
| „Matrix 1 (1999) CZ Dabing 2160p Ultra HD 4k" | 6.05 GB | 1080p + 720p |
| „Matrix (1999) CZ DAB 3840x1600p" | 6.05 GB | 1080p |
| „Matrix-CZ-(1999)---HD-1080p" | 2.56 GB | jen 720p — navzdory „1080p" |
| „Matrix 1999 CZ dab 1080p" | 1.73 GB | jen 720p — navzdory „1080p" |
| „Matrix 1999 CZ dab" (bez labelu) | 1.74 GB | 720p |

### Klíčová zjištění

1. **Přehraj.to vůbec nepodává 4K.** Jejich transkoder má strop 1080p.
   Kdokoli napíše v názvu „4K", klame uživatele — hráč stejně nepřepne
   nad 1080p.
2. **Polovina uploadů s „1080p" v názvu lže.** Serverují jen 720p
   (1728×720), ale v titulku se vychloubají „1080p" / „Full HD".
3. **Kartový badge „HD"** vlevo nahoře přidává Přehraj.to **automaticky**
   u všeho, co má ve streamu ≥ 720p. Nezáleží, co je v názvu.

## Co budeme uploadovat my

Ze sktorrentu máme **maximálně 720p** soubory (ověřeno — na žádné ze 25 CDN
nod sktorrentu žádný z testovaných filmů nemá 1080p/1440p/2160p). Takže
posíláme na Přehraj.to **720p → 1728×720** (pro cinemascope) nebo
**1280×720** (pro 16:9).

Technicky je to **HD** podle průmyslové definice:
- HD = 720p
- Full HD = 1080p
- UHD / 4K = 2160p

## Proč přesně tohle pojmenování

- **„HD" je pravdivé** — 720p z definice HD je, a Přehraj.to to navíc sám
  autobadguje v kartě.
- **Bez čísel** — číslo typu „720p" odradí uživatele, který je zvyklý
  vídat „1080p" nebo „4K" (i když druzí uploadeři lžou).
- **Bez „Full HD" / „1080p" / „4K"** — byla by to lež, protože náš zdroj
  to není. Navíc by hráč ukázal jen 720p a uživatel by poznal rozpor.
- **Český název filmu + rok** — Přehraj.to to používá v interním
  vyhledávání a mikrodatech.
- **„CZ" na konci** — signalizuje, že film je v češtině (dabing nebo
  titulky); bez toho si někteří uživatelé nejsou jistí.
- **Bez „HD" sufixu** — Přehraj.to si badge „HD" v kartě přidává
  automaticky podle rozlišení streamu. V názvu to nic nepřidá a kazí
  čitelnost.

## Shrnutí

Stáhni ze sktorrentu, pojmenuj `Název (rok) CZ.mp4` (nebo `CZ Dabing`),
nahraj na náš Přehraj.to účet. Neřeš čísla. Neřeš cinemascope vs. 16:9.
Přehraj.to přidá HD badge automaticky a film bude vypadat stejně
kvalitně jako cokoli jiného, co je tam uploadováno s „1080p" (protože
polovina z toho je stejně ve skutečnosti 720p).

## Edge cases

| Scénář | Filename |
|--------|----------|
| Film s diakritikou v názvu | Ponechat diakritiku: `Žižkov 96 (1996) CZ.mp4` |
| Film s dvojtečkou nebo nepovolenými znaky | Dvojtečka → spojovník: `Mission Impossible Odplata — 1. část (2023) CZ Dabing.mp4` |
| Serial epizoda (nechystáme, ale pro úplnost) | `{Seriál} SxxExx — {Epizoda} ({rok}) CZ.mp4` |
| Film bez českého dabingu ani titulků | Nenahrávat. Jsme česká platforma. |
