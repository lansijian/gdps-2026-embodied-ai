#!/usr/bin/env python3
"""Pre-generate narration wav files for the offline fallback.

Reads knowledge_base.json (exhibit narrations) and stations YAML (route briefs),
synthesizes each unique text locally (macOS say / Linux espeak-ng), converts to
wav and writes a manifest consumed by guide/offline_audio.py.

Usage:
    python3 scripts/tourism/prepare_fallback_audio.py \
        --knowledge /path/to/exhibit_templates/knowledge_base.json \
        --stations tracks/cultural-tourism/configs/stations.example.yaml \
        --out-dir assets/narration

The robot only needs the generated directory (wav + manifest.json); generation
runs on a dev machine (or on the robot if espeak-ng is installed).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOURISM_ROOT = ROOT / "tracks" / "cultural-tourism"
for candidate in (ROOT, TOURISM_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass

from gdps_tourism.guide.offline_audio import text_key, wav_duration_s  # noqa: E402


def _load_knowledge(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for item in payload.get("exhibits") or []:
        items.append((str(item.get("id")), str(item.get("narration") or ""), "narration"))
    for item in payload.get("composite_boards") or []:
        items.append((str(item.get("id")), str(item.get("narration") or ""), "narration"))
    return items


def _load_route_briefs(path: Path):
    sys.path.insert(0, str(TOURISM_ROOT))
    from gdps_tourism.guide.stations import StationBook

    book = StationBook.load(path)
    return [(station.station_id, station.route_brief, "brief") for station in book.stations if station.route_brief]


def _synthesize(text: str, out_path: Path, *, engine: str, voice: str) -> bool:
    """Create a wav file for text; returns False when no TTS engine is available."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if engine in ("auto", "say") and sys.platform == "darwin" and shutil.which("say"):
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "narration.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
            if shutil.which("afconvert"):
                subprocess.run(
                    ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(out_path)],
                    check=True,
                )
                return True
            shutil.copy(aiff, out_path.with_suffix(".aiff"))
            return False
    if engine in ("auto", "espeak"):
        for binary in ("espeak-ng", "espeak"):
            if shutil.which(binary):
                subprocess.run(
                    [binary, "-v", "zh", "-s", "150", "-w", str(out_path), text],
                    check=True,
                )
                return True
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate offline narration wav files")
    parser.add_argument("--knowledge", required=True, help="knowledge_base.json")
    parser.add_argument("--stations", default=str(TOURISM_ROOT / "configs" / "stations.example.yaml"))
    parser.add_argument("--out-dir", default=str(ROOT / "assets" / "narration"))
    parser.add_argument("--engine", choices=("auto", "say", "espeak"), default="auto")
    parser.add_argument("--voice", default="Tingting")
    parser.add_argument("--force", action="store_true", help="regenerate existing files")
    args = parser.parse_args(argv)

    knowledge_path = Path(args.knowledge)
    if not knowledge_path.is_file():
        print("[fallback] knowledge_base.json not found: %s" % knowledge_path, file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    manifest_path = out_dir / "manifest.json"
    manifest = {}
    if manifest_path.is_file() and not args.force:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    texts = _load_knowledge(knowledge_path) + _load_route_briefs(Path(args.stations))
    generated = skipped = failed = 0
    for item_id, text, kind in texts:
        text = (text or "").strip()
        if not text:
            continue
        key = text_key(text)
        wav_path = out_dir / ("%s.wav" % key)
        if key in manifest and wav_path.is_file() and not args.force:
            skipped += 1
            continue
        ok = _synthesize(text, wav_path, engine=args.engine, voice=args.voice)
        duration = wav_duration_s(wav_path) if ok and wav_path.is_file() else 0.0
        if not ok:
            failed += 1
            print("[fallback] no TTS engine for %s (%s)" % (item_id, kind), file=sys.stderr)
            continue
        if duration <= 0.0:
            duration = max(3.0, len(text) / 4.5)
        manifest[key] = {
            "file": wav_path.name,
            "duration_s": round(duration, 1),
            "kind": kind,
            "id": item_id,
        }
        generated += 1
        print("[fallback] %-10s %-9s %5.1fs %s" % (item_id, kind, duration, wav_path.name))

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "[fallback] generated=%d skipped=%d failed=%d manifest=%s"
        % (generated, skipped, failed, manifest_path)
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
