# Detekce jazyka videa

Jak z libovolné URL / video streamu / upload titulku zjistíme, **jakým jazykem
mluví zvuková stopa a jestli má titulky**. Dokument pokrývá tři nezávislé
detekční mechanismy (tag → kontejner → Whisper), jejich cenu, přesnost a jak
se řetězí v produkčních pipeline napříč `cr` a `prehrajto-sync`.

## TL;DR

Detekce běží jako kaskáda **od nejlevnější k nejdražší**:

| Vrstva | Zdroj | Cena | Přesnost | Výstup |
|---|---|---|---|---|
| 1. **Regex** | Upload title / tag | 0 ms | Vysoká pro SK Torrent konvenci | `has_dub`, `has_subtitles` |
| 2. **ffprobe** | Container tag v MP4/MKV | ~1–10 s | Velmi vysoká **pokud tag existuje** | ISO 639-1 kód |
| 3. **Whisper** | Vzorek zvukové stopy | ~30–90 s | Vysoká, ale stojí CPU | ISO 639-1 + pravděpodobnost |

Jakmile vrstva 1 nebo 2 vrátí jednoznačné CZ/SK, další vrstva se **nespouští**.
Whisper je drahý poslední záchyt.

## Vrstva 1 — Regex nad uploadovaným titulem

**Kde:** [`cr` repo, `scripts/auto_import/title_parser.py`](https://github.com/Olbrasoft/cr/blob/main/scripts/auto_import/title_parser.py)

SK Torrent uploadery drží konvenci: do závorky za názvem dávají jazykový
tag. Příklady:

- `"Hitler: Vzestup zla / Hitler: The Rise of Evil (2003)(CZ) = CSFD 82%"` → CZ dabing
- `"The Matrix (1999)(SK tit)"` → SK titulky
- `"Film 2024(CZ dab/SK tit)"` → CZ dabing + SK titulky
- `"Movie.2024.CZ.SK"` → CZ + SK (ambivalentní — bereme obojí)

### Regexy (vybrané)

```python
_DUB_CZ_RE   = re.compile(r"\b(cz|cesk[yá])\s*(dab|dub|dabing)\b", re.I)
_DUB_SK_RE   = re.compile(r"\b(sk|slovensk[yá])\s*(dab|dub|dabing)\b", re.I)
_SUBS_RE     = re.compile(r"\b(cz|cesk[yá])\s*(tit|titulky|sub)\b", re.I)
_SUBS_SK_RE  = re.compile(r"\b(sk|slovensk[yá])\s*(tit|titulky|sub)\b", re.I)
_LANG_TAG_RE = re.compile(r"[\(\[\s](cz|sk|en)[\)\]\s]", re.I)
```

`_detect_langs(title)` vrátí seznam z množiny:
`{"DUB_CZ", "DUB_SK", "SUBS_CZ", "SUBS_SK", "CZ", "SK", "EN"}`.

### Kontextová interpretace holého tagu

SK Torrent konvence: **holý `(CZ)` / `(SK)`** (bez "dab"/"tit") = **dabing**,
ne originál ani titulky. `_langs_to_flags()` v `auto-import.py` to promítá:

```python
def _langs_to_flags(langs):
    has_dub = any(l in ("DUB_CZ", "DUB_SK", "CZ", "SK") for l in langs)
    has_subtitles = any(l in ("SUBS_CZ", "SUBS_SK") for l in langs)
    return has_dub, has_subtitles
```

**Kdy to zabíjí:** uploady, kde je holé `(EN)` ale obsah je dabovaný CZ
(uploader se spletl). Pak nás zachrání vrstva 2 nebo 3.

### Backfill

[`scripts/backfill-sktorrent-langs.py`](https://github.com/Olbrasoft/cr/blob/main/scripts/backfill-sktorrent-langs.py)
reparsuje historické `import_items.sktorrent_title` a **OR-uje** detekci do
`films.has_dub` / `films.has_subtitles`. OR-logika je důležitá: existující
`true` z jiného zdroje (Bombuj, Prehraj.to) se nesnižuje na `false`.

## Vrstva 2 — ffprobe container tag

**Kde:**
- [`cr`, `scripts/sledujteto-detect-audio.py`, `ffprobe_audio()`](https://github.com/Olbrasoft/cr/blob/main/scripts/sledujteto-detect-audio.py)
- [`prehrajto-sync`, `src/detect_audio_language.py`, `ffprobe_audio_lang()`](../src/detect_audio_language.py)

MP4 a Matroska obsahují `language` tag na audio stopě. ffprobe ho přečte bez
stahování celého souboru — stačí HTTP Range requesty na `moov` atom (MP4)
nebo header (MKV). **Rozdíl proti stahování:** ~1–10 s místo desítek minut.

### Příkaz

```bash
ffprobe -v error \
        -select_streams a:0 \
        -show_entries stream_tags=language \
        -show_entries format=duration \
        -of json \
        "$VIDEO_URL"
```

Výstup:

```json
{"streams":[{"tags":{"language":"cze"}}],"format":{"duration":"6840.24"}}
```

### Normalizace ISO kódů

Tagy bývají ISO 639-2 ("cze", "slk", "eng"), my pracujeme s ISO 639-1
("cs", "sk", "en"). Mapovací tabulka `ISO_MAP` pokrývá ~60 jazyků včetně
alternativních kódů (`"ces"` = `"cs"`, `"slo"` = `"sk"`, `"ger"` / `"deu"` =
`"de"`).

### Známé slepé skvrny

1. **Tag chybí.** Mnoho uploadů nemá tag nastaven (nebo ho má `"und"` =
   undefined). `ffprobe_audio()` pak vrátí `(duration, None)` a caller se
   propadne do vrstvy 3.

2. **Tag lže.** Stream byl remuxován se zachovaným tagem z originálu,
   zatímco audio stopa byla přemixována na CZ dabing. Regex z vrstvy 1
   (pokud máme title) tohle často zachytí, jinak tag vyhodnotíme jako
   **unverified** a dáme mu confidence 0.5.

3. **Víc audio stop.** Bereme jen `a:0` (primární). Pokud je první stopa
   bez tagu a druhá má CZ tag, prošvihneme. **TODO** (viz sekce níže).

## Vrstva 3 — Whisper fallback

Když vrstvy 1 a 2 selžou (nebo vrátí nevěrohodný výsledek), stáhneme krátký
vzorek zvuku a spustíme Whisper jen na jazykové detekci (ne na plný přepis).

### Dvě implementace

**`cr` / sledujteto:** `whisper` (OpenAI referenční), model `tiny`
```python
model = whisper.load_model("tiny")
audio = whisper.load_audio(wav_path)
mel = whisper.log_mel_spectrogram(audio).to(model.device)
_, probs = model.detect_language(mel)
# probs = {"cs": 0.87, "en": 0.08, "sk": 0.03, ...}
```

**`prehrajto-sync`:** `faster-whisper` (CTranslate2, ~4× rychlejší na CPU),
default model `small`, quantizace `int8`
```python
model = WhisperModel(model_size, device="cpu", compute_type="int8")
segments, info = model.transcribe(path, language=None, task="transcribe",
                                  beam_size=1, vad_filter=True)
# info.language = "cs", info.language_probability = 0.98
```

### Získání vzorku zvuku

Nechceme stahovat 2 GB film jen kvůli detekci. Dva vzorovací přístupy:

**sledujteto (2 vzorky, každý 15 s):**
```python
# Obejde "studio ticho" na startu a závěrečné titulky.
for position in [duration * 0.33, duration * 0.66]:
    subprocess.run([
        "ffmpeg", "-ss", str(position), "-i", url,
        "-t", "15", "-vn", "-ac", "1", "-ar", "16000",
        "-f", "wav", wav_path,
    ])
    mel = prepare(wav_path)
    iso, prob = model.detect_language(mel)
```
Výsledek: průměr obou pravděpodobností, vyhraje vyšší. Zabrání to
false-positivu, pokud vzorek padne do hudby nebo ticha.

**prehrajto-sync (1 vzorek, 30 s od 5. minuty):**
```python
ffmpeg -ss 300 -t 30 -i "$URL" -vn -ac 1 -ar 16000 "$TMP"
```
Jednodušší, ale zranitelnější vůči "studio ticho". Model `small` je
robustnější, takže 30 s stačí.

### Proč ne celý film

- **Cena:** transkript 90-min filmu na CPU s `tiny` = 5–10 min; se `small`
  = 15–30 min.
- **Přesnost:** `detect_language` potřebuje 15–30 s čistého hlasu. Víc už
  nepomůže.
- **GPU neřešíme:** `cr` i `prehrajto-sync` běží na běžných VPS / GitHub
  Actions runnerech bez CUDA. `int8` quantizace ve `faster-whisper` dává
  ~200 ms inference na 30 s vzorek bez GPU.

### Confidence scoring

```
tag v {cs, sk}                         → 1.0
tag existuje, ale jiný                 → 0.5 (unverified, zaznamenáno jako hint)
tag chybí + Whisper vrátí probability  → hodnota probability (typicky 0.7–0.99)
Whisper selže                          → 0.0 (fall back na tag nebo log error)
```

### Kdy Whisper selže

- Soubor je jen hudba / znělky / titulky bez hlasu (krátký sample zachytí
  instrumentál, `detect_language` vrátí pravděpodobnost ≤ 0.5 pro všechny
  jazyky).
- Audio kodek, který ffmpeg neumí dekódovat (vzácné, ale vídáno u starých
  DivX kontejnerů).
- Síťové selhání na HTTP range při seek-u — ffmpeg vyhodí nulový vzorek.

## Řetězení v praxi

### SK Torrent auto-import (`cr`)

```
SK Torrent detail page
         │
         ▼
┌─────────────────────────────────┐
│ Vrstva 1: _detect_langs(title)  │   <1 ms
└────────┬────────────────────────┘
         │ has_dub=?, has_subtitles=?
         ▼
 Vrstvy 2/3 se v auto-import.py ZATÍM NEVYUŽÍVAJÍ —
 content jde na disk jen pokud prehraj.to tenhle konkrétní
 film ještě nemá. Zůstává to TODO pro kvalitnější rozhodnutí
 "CZ dabing vs originál" u uploadů bez tagu.
```

**Výstup:** sloupce `films.has_dub` + `films.has_subtitles`. Oba jsou
kumulativní (OR-uje se přes všechny zdroje).

### sledujteto audio detection (`cr`)

```
URL videa ze sledujte.to
         │
         ▼
┌───────────────────────────────────┐
│ Vrstva 2: ffprobe_audio(url)      │   1–3 s
└──────────┬────────────────────────┘
           │ tag ∈ {cs, sk, ...}
           ├── YES ──► audio_language = tag, method = "ffprobe"
           │
           └── NO  ──┐
                    ▼
┌──────────────────────────────────────┐
│ Vrstva 3: whisper tiny, 2× 15s       │   30–60 s
│            detect_language()         │
└──────────┬───────────────────────────┘
           │
           ▼
audio_language  = ISO 639-1
method         = "whisper_tiny_2samples"
probability    = float
```

**Výstup:** JSONL do `data/sledujteto/*-audio-lang.jsonl`, odtud se později
promítá do `films.audio_language` (zatím jen experimentálně, ne v produkci).

### prehrajto-sync upload selector

```
next film z backlog.sktorrent-films.jsonl
         │
         ▼ (už má ffprobe / whisper výsledek z předchozího kroku)
┌──────────────────────────────────┐
│ pick_next_film.py                │
│   if require_cs and              │
│      detected_language != "cs":  │
│      skip                        │
└──────────┬───────────────────────┘
           │
           ▼
 TMDB original_language lookup
 if orig ∈ {cs, sk}: title = "… (YYYY) CZ"
 else:               title = "… (YYYY) CZ Dabing"
```

**Proč dva sloupce** (`detected_language` vs. `original_language`):

- `detected_language` = co **reálně mluví** ve videu (z Whisper / tag).
- `original_language` z TMDB = v jakém jazyce byl film **natočen**.

Oba se zkombinují pro název uploadu: pokud originál je angličtina a my
máme český zvuk, je to očividně dabing → přidáme `"CZ Dabing"` suffix. Pokud
originál je čeština a máme český zvuk, je to originál → stačí `"CZ"`.

## Titulky

Titulky detekujeme odděleně, pouze z `.srt` souborů (Whisper titulky nečte):

**[`cr`, `scripts/sledujteto-sources-enrich.py`, `detect_srt_language()`](https://github.com/Olbrasoft/cr/blob/main/scripts/sledujteto-sources-enrich.py)**

```python
from langdetect import detect
text = srt_to_plain_text(srt_content)   # strip timestamps, HTML tags
lang = detect(text)   # "cs" / "sk" / "en" / ...
```

`langdetect` je statistický klasifikátor nad n-gramy — rychlý a přesný na
titulky (stovky vět), ale **nepoužitelný na audio**. Whisper zvládá obojí,
ale titulky jsou tak levné přes `langdetect`, že pouštět Whisper nemá
smysl.

**Stav:** funkce existuje, výsledek se **zatím neukládá do DB**. Je to
připraveno pro budoucí sloupec `films.subtitle_languages` (TODO).

## Konfigurační matrix

| Repo / skript | Whisper engine | Model | Device | Vzorek | Celková cena |
|---|---|---|---|---|---|
| `cr/sledujteto-detect-audio.py` | `whisper` (OpenAI) | `tiny` | CPU | 2× 15 s (33 % + 66 %) | 30–60 s / film |
| `prehrajto-sync/detect_audio_language.py` | `faster-whisper` | `small` (default) | CPU `int8` | 1× 30 s (od 5. min) | 30–90 s / film |
| GitHub Actions runner (prehrajto-sync) | `faster-whisper` | `small` | CPU `int8` | 1× 30 s | ~45 s / film + 20 s model load |

## TODO — nevyřešené scénáře

1. **Víc audio stop.** Číst `a:*` místo `a:0`, vybrat stream s CZ/SK tagem
   (pokud existuje), jinak první. Teď prošvihneme filmy, kde CZ dabing je
   na druhé stopě.

2. **TMDB `original_language` v DB.** V `pick_next_film.py` se načítá
   dynamicky; pomohlo by mít ho přímo v `films` na cache, protože TMDB rate
   limit nás omezuje při dávkovém přehodnocení.

3. **SRT language → DB.** `detect_srt_language()` funguje a má ~99% přesnost
   na titulky > 100 řádků. Chybí jen schema (`subtitle_languages TEXT[]`)
   a wrapper, který to z SK Torrent / Prehraj.to uploadu uloží.

4. **Whisper fallback v auto-import.py.** Aktuálně SK Torrent auto-import
   jede jen na regex. Pro filmy bez jakéhokoli jazykového tagu v názvu
   (občas se najdou) by Whisper run s `tiny` modelem byl ~30 s / film —
   únosné pro nightly cron, nepoužitelné inline při webovém requestu.

5. **Re-detekce při změně modelu.** `cr` nemá sloupec
   `audio_detection_model` / `audio_detected_at`, takže nelze cíleně
   re-spustit detekci pro filmy, které jsme detekovali starým modelem.
   Prehrajto-sync má `detected_language_source` (+ `confidence`), což
   pokrývá část problému.

6. **GPU acceleration.** `faster-whisper` podporuje CUDA s `compute_type="float16"`
   a běží ~20× rychleji. Neřešíme, dokud má `cr` / `prehrajto-sync` jen CPU
   VPS — ale je to jednořádková změna, kdyby se hardware objevil.

7. **VAD pre-filter.** `faster-whisper` má `vad_filter=True` (ořízne ticho
   před detekcí). `cr` OpenAI Whisper ne — proto bere 2 vzorky, aby se
   nespálil na tichu. Přechod na `faster-whisper` všude by logiku
   sjednotil.

## Reference

- Regex parser titulů: [`cr/scripts/auto_import/title_parser.py`](https://github.com/Olbrasoft/cr/blob/main/scripts/auto_import/title_parser.py)
- Integrace v auto-importu: [`cr/scripts/auto-import.py`](https://github.com/Olbrasoft/cr/blob/main/scripts/auto-import.py) (`_langs_to_flags`)
- Backfill: [`cr/scripts/backfill-sktorrent-langs.py`](https://github.com/Olbrasoft/cr/blob/main/scripts/backfill-sktorrent-langs.py)
- sledujteto ffprobe + Whisper: [`cr/scripts/sledujteto-detect-audio.py`](https://github.com/Olbrasoft/cr/blob/main/scripts/sledujteto-detect-audio.py)
- prehrajto-sync ffprobe + faster-whisper: [`prehrajto-sync/src/detect_audio_language.py`](../src/detect_audio_language.py)
- TMDB original_language: [`prehrajto-sync/src/pick_next_film.py`](../src/pick_next_film.py)
- SRT detekce: [`cr/scripts/sledujteto-sources-enrich.py`](https://github.com/Olbrasoft/cr/blob/main/scripts/sledujteto-sources-enrich.py) (`detect_srt_language`)
