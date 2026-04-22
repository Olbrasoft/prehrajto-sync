#!/usr/bin/env python3
"""Detect audio language for sktorrent films.

Two-stage pipeline:
1. `ffprobe` reads the MP4/MKV audio stream `language` tag (cheap — HTTP range
   requests only, a few seconds). If the tag is cs/sk we trust it.
2. Otherwise we fall back to `faster-whisper` running on a 30s audio sample
   extracted via `ffmpeg -ss 300 -t 30` (seeks into the middle of the film to
   skip silent intros/credits).

The detected language + source + confidence is written back to the backlog
JSONL as `detected_language`, `detected_language_source`, and
`detected_language_confidence`.

Usage:
    python3 src/detect_audio_language.py
    python3 src/detect_audio_language.py --only-ids 10591,16264
    python3 src/detect_audio_language.py --limit 20
    python3 src/detect_audio_language.py --force --only-ids 168
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve_sktorrent_cdn import resolve as resolve_cdn


REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "backlog" / "sktorrent-films.jsonl"

SAMPLE_START_SEC = 300
SAMPLE_DURATION_SEC = 30

# ISO 639-2/B (cze, slo), 639-2/T (ces, slk), 639-1 (cs, sk) → 639-1 two-letter
ISO_MAP = {
    "cze": "cs", "ces": "cs", "cs": "cs", "cz": "cs",
    "slo": "sk", "slk": "sk", "sk": "sk",
    "eng": "en", "en": "en",
    "ger": "de", "deu": "de", "de": "de",
    "fre": "fr", "fra": "fr", "fr": "fr",
    "spa": "es", "es": "es",
    "ita": "it", "it": "it",
    "rus": "ru", "ru": "ru",
    "pol": "pl", "pl": "pl",
    "hun": "hu", "hu": "hu",
    "ukr": "uk", "uk": "uk",
    "jpn": "ja", "ja": "ja",
    "kor": "ko", "ko": "ko",
    "chi": "zh", "zho": "zh", "zh": "zh",
    "dan": "da", "da": "da",
    "dut": "nl", "nld": "nl", "nl": "nl",
    "fin": "fi", "fi": "fi",
    "nor": "no", "nob": "no", "no": "no",
    "swe": "sv", "sv": "sv",
    "por": "pt", "pt": "pt",
    "tur": "tr", "tr": "tr",
}


def normalize_iso(code: str | None) -> str | None:
    if not code:
        return None
    c = code.strip().lower()
    return ISO_MAP.get(c, c if len(c) == 2 else None)


def ffprobe_audio_lang(url: str, timeout: int = 20) -> str | None:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream_tags=language",
        "-of", "default=nw=1:nk=1", url,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return normalize_iso(out.stdout.strip())
    except Exception:
        return None


def extract_audio_sample(url: str, out_wav: Path, timeout: int = 180) -> bool:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(SAMPLE_START_SEC),
        "-i", url,
        "-t", str(SAMPLE_DURATION_SEC),
        "-vn", "-ac", "1", "-ar", "16000",
        "-f", "wav",
        str(out_wav),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode == 0 and out_wav.exists() and out_wav.stat().st_size > 1024
    except Exception:
        return False


def load_records():
    with BACKLOG.open() as f:
        return [json.loads(l) for l in f if l.strip()]


def save_records(records):
    tmp = BACKLOG.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(BACKLOG)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-ids", type=str, default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true",
                    help="Re-detect even when detected_language is already set")
    ap.add_argument("--model-size", type=str, default="small",
                    help="Whisper model (tiny/base/small/medium). Default small.")
    ap.add_argument("--skip-whisper", action="store_true",
                    help="Only use ffprobe tag; do not fall back to Whisper")
    ap.add_argument("--dry-run", action="store_true",
                    help="Do not write back to backlog")
    args = ap.parse_args()

    only_ids = set()
    if args.only_ids:
        only_ids = {int(x.strip()) for x in args.only_ids.split(",") if x.strip()}

    records = load_records()
    todo = []
    for i, r in enumerate(records):
        if only_ids:
            if r.get("cr_film_id") not in only_ids:
                continue
        elif not args.force and r.get("detected_language"):
            continue
        todo.append(i)

    if args.limit > 0:
        todo = todo[: args.limit]

    total = len(todo)
    if not total:
        print("Nothing to detect.")
        return 0

    print(f"Films to detect: {total}")
    print(f"Skip whisper: {args.skip_whisper}")
    if not args.skip_whisper:
        print(f"Whisper model: {args.model_size}")
        print("Loading whisper model…")
        from faster_whisper import WhisperModel
        model = WhisperModel(args.model_size, device="cpu", compute_type="int8")
    else:
        model = None

    ok = via_tag = via_whisper = fail = 0
    start = time.time()

    for n, idx in enumerate(todo, 1):
        r = records[idx]
        fid = r["cr_film_id"]
        title = r.get("title", "?")
        year = r.get("year", "?")
        url = r.get("url")
        if not url:
            print(f"  {n}/{total} SKIP [id={fid}] — no url")
            fail += 1
            continue

        t0 = time.time()
        resolved = resolve_cdn(url)
        if not resolved:
            print(f"  {n}/{total} FAIL {title} ({year}) [id={fid}] — cdn_resolve_failed")
            r["detected_language_error"] = "cdn_resolve_failed"
            fail += 1
            continue

        # Stage 1: ffprobe tag
        tag = ffprobe_audio_lang(resolved)
        if tag in ("cs", "sk"):
            r["detected_language"] = tag
            r["detected_language_source"] = "ffprobe_tag"
            r["detected_language_confidence"] = 1.0
            r.pop("detected_language_error", None)
            print(f"  {n}/{total} {title} ({year}) [id={fid}] → {tag} (tag) {time.time()-t0:.1f}s")
            ok += 1
            via_tag += 1
            if not args.dry_run and n % 5 == 0:
                save_records(records)
            continue

        if args.skip_whisper:
            r["detected_language"] = tag
            r["detected_language_source"] = "ffprobe_tag_only"
            r["detected_language_confidence"] = 0.5 if tag else 0.0
            print(f"  {n}/{total} {title} ({year}) [id={fid}] → {tag or '?'} (tag, no whisper) {time.time()-t0:.1f}s")
            if tag:
                ok += 1
                via_tag += 1
            else:
                fail += 1
            if not args.dry_run and n % 5 == 0:
                save_records(records)
            continue

        # Stage 2: Whisper on 30s sample
        with tempfile.TemporaryDirectory() as tmpdir:
            wav = Path(tmpdir) / "sample.wav"
            if not extract_audio_sample(resolved, wav):
                print(f"  {n}/{total} FAIL {title} ({year}) [id={fid}] — ffmpeg sample failed (tag={tag})")
                r["detected_language_error"] = "ffmpeg_sample_failed"
                if tag:
                    # keep the tag as a lower-confidence hint
                    r["detected_language"] = tag
                    r["detected_language_source"] = "ffprobe_tag_unverified"
                    r["detected_language_confidence"] = 0.5
                fail += 1
                continue

            try:
                segments, info = model.transcribe(
                    str(wav),
                    language=None,
                    task="transcribe",
                    beam_size=1,
                    vad_filter=True,
                )
                list(segments)
                detected = info.language
                conf = float(info.language_probability)
            except Exception as e:
                print(f"  {n}/{total} FAIL {title} ({year}) [id={fid}] — whisper: {e}")
                r["detected_language_error"] = f"whisper: {e!s}"
                fail += 1
                continue

        r["detected_language"] = detected
        r["detected_language_source"] = "whisper"
        r["detected_language_confidence"] = round(conf, 3)
        r.pop("detected_language_error", None)
        print(f"  {n}/{total} {title} ({year}) [id={fid}] → {detected} ({conf:.0%}, tag={tag}) {time.time()-t0:.1f}s")
        ok += 1
        via_whisper += 1
        if not args.dry_run and n % 5 == 0:
            save_records(records)

    if not args.dry_run:
        save_records(records)

    dur = time.time() - start
    print()
    print(f"Done in {dur:.0f}s ({dur/60:.1f}m) — ok={ok} (tag={via_tag}, whisper={via_whisper}) fail={fail}")

    # Distribution in processed set
    from collections import Counter
    c = Counter()
    for idx in todo:
        c[records[idx].get("detected_language")] += 1
    print("Language distribution (processed):")
    for k, v in c.most_common():
        print(f"  {k!r:10s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
