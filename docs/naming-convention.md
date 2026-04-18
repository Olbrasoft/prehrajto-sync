# Naming konvence pro uploady na Přehraj.to

Finální rozhodnutí pro pojmenování souborů, které nahráváme na náš účet.

## Formát

    {Název filmu} ({rok}) HD CZ.mp4

## Příklady

```
Lví král (1994) HD CZ.mp4
Medvěd (1988) HD CZ.mp4
Oppenheimer (2023) HD CZ.mp4
Mission Impossible Odplata (2023) HD CZ.mp4
```

## Varianty

- **Titulky místo dabingu**: `{Název} ({rok}) HD CZ titulky.mp4`
- **SD kvalita (480p, výjimečně)**: `{Název} ({rok}) SD CZ.mp4`

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
- **„CZ" za HD** — signalizuje, že film je v češtině (dabing nebo titulky);
  bez toho si někteří uživatelé nejsou jistí.

## Shrnutí

Stáhni ze sktorrentu, pojmenuj `Název (rok) HD CZ.mp4`, nahraj na náš
Přehraj.to účet. Neřeš čísla. Neřeš cinemascope vs. 16:9. Přehraj.to
přidá HD badge automaticky a film bude vypadat stejně kvalitně jako
cokoli jiného, co je tam uploadováno s „1080p" (protože polovina z toho
je stejně ve skutečnosti 720p).

## Edge cases

| Scénář | Filename |
|--------|----------|
| Film s diakritikou v názvu | Ponechat diakritiku: `Žižkov 96 (1996) HD CZ.mp4` |
| Film s dvojtečkou nebo nepovolenými znaky | Dvojtečka → spojovník: `Mission Impossible Odplata — 1. část (2023) HD CZ.mp4` |
| Serial epizoda (nechystáme, ale pro úplnost) | `{Seriál} SxxExx — {Epizoda} ({rok}) HD CZ.mp4` |
| Film bez českého dabingu ani titulků | Nenahrávat. Jsme česká platforma. |
