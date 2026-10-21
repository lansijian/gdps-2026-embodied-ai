#!/usr/bin/env python3
"""Offline rehearsal: estimate the 30-minute mission timing without the robot.

Uses the station config (walking ETAs), knowledge_base.json (narration text) and
the pre-generated audio manifest (narration duration) to print a per-station
timeline and check it against the competition budget.

Usage:
    python3 scripts/tourism/guide_rehearsal.py \
        --stations tracks/cultural-tourism/configs/stations.example.yaml \
        --knowledge /path/to/exhibit_templates/knowledge_base.json \
        --manifest assets/narration/manifest.json \
        --budget-s 1800 --reserve-s 180
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

from gdps_tourism.guide.offline_audio import load_manifest, text_key  # noqa: E402
from gdps_tourism.guide.stations import StationBook  # noqa: E402

DEFAULT_SPEECH_CHARS_PER_S = 4.5


def _load_narrations(path: Optional[Path]) -> Dict[str, str]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    narrations: Dict[str, str] = {}
    for item in (payload.get("exhibits") or []) + (payload.get("composite_boards") or []):
        exhibit_id = str(item.get("id") or "")
        text = str(item.get("narration") or "")
        if exhibit_id and text:
            narrations[exhibit_id] = text
    return narrations


def _duration(text: str, manifest: Dict[str, dict], chars_per_s: float) -> float:
    entry = manifest.get(text_key(text))
    if entry and float(entry.get("duration_s") or 0.0) > 0.0:
        return float(entry["duration_s"])
    return max(2.0, len(text) / max(1.0, chars_per_s))


def build_timeline(
    stations_path: Path,
    *,
    knowledge_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    observe_s: float = 3.0,
    settle_s: float = 2.0,
    listen_s: float = 8.0,
    chars_per_s: float = DEFAULT_SPEECH_CHARS_PER_S,
) -> Dict[str, object]:
    book = StationBook.load(stations_path)
    narrations = _load_narrations(knowledge_path)
    manifest = load_manifest(manifest_path) if manifest_path else {}
    rows: List[Dict[str, object]] = []
    total = 0.0
    previous_eta = 0
    for station in book.ordered_stations():
        walk_s = max(0, int(station.eta_s) - previous_eta) if station.eta_s else 0
        previous_eta = max(previous_eta, int(station.eta_s or 0))
        narration_text = ""
        if station.exhibit_ids:
            narration_text = narrations.get(station.exhibit_ids[0], "")
        if not narration_text and station.route_brief:
            narration_text = station.route_brief
        narration_s = _duration(narration_text, manifest, chars_per_s) if narration_text else 0.0
        station_total = walk_s + settle_s + observe_s + narration_s + listen_s
        total += station_total
        rows.append(
            {
                "station_id": station.station_id,
                "name": station.name,
                "kind": station.kind,
                "walk_s": walk_s,
                "settle_s": settle_s,
                "observe_s": observe_s if station.needs_observation else 0.0,
                "narration_s": round(narration_s, 1),
                "listen_s": listen_s,
                "total_s": round(station_total, 1),
                "cumulative_s": round(total, 1),
            }
        )
    return {"rows": rows, "total_s": round(total, 1), "stations": len(rows)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Estimate the tourism guide mission timing")
    parser.add_argument("--stations", default=str(TOURISM_ROOT / "configs" / "stations.example.yaml"))
    parser.add_argument("--knowledge", default=None, help="knowledge_base.json (narration text)")
    parser.add_argument("--manifest", default=str(ROOT / "assets" / "narration" / "manifest.json"))
    parser.add_argument("--observe-s", type=float, default=3.0)
    parser.add_argument("--settle-s", type=float, default=2.0)
    parser.add_argument("--listen-s", type=float, default=8.0)
    parser.add_argument("--budget-s", type=float, default=1800.0)
    parser.add_argument("--reserve-s", type=float, default=180.0)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest) if args.manifest else None
    if manifest_path is not None and not manifest_path.is_file():
        print("[rehearsal] manifest not found, estimating duration by text length: %s" % manifest_path)
        manifest_path = None
    timeline = build_timeline(
        Path(args.stations),
        knowledge_path=Path(args.knowledge) if args.knowledge else None,
        manifest_path=manifest_path,
        observe_s=args.observe_s,
        settle_s=args.settle_s,
        listen_s=args.listen_s,
    )
    print("%-6s %-22s %6s %6s %6s %6s %6s" % ("ID", "站点", "步行", "识别", "讲解", "聆听", "累计"))
    for row in timeline["rows"]:
        print(
            "%-6s %-22s %5.0fs %5.0fs %5.1fs %5.0fs %6.0fs"
            % (
                row["station_id"],
                str(row["name"])[:20],
                row["walk_s"],
                row["observe_s"],
                row["narration_s"],
                row["listen_s"],
                row["cumulative_s"],
            )
        )
    total = float(timeline["total_s"])
    limit = float(args.budget_s) - float(args.reserve_s)
    status = "OK" if total <= limit else "OVER"
    print(
        "\n[rehearsal] stations=%d total=%.0fs (%.1f min)  budget=%.0fs reserve=%.0fs  usable=%.0fs -> %s"
        % (timeline["stations"], total, total / 60.0, args.budget_s, args.reserve_s, limit, status)
    )
    if total > limit:
        print(
            "[rehearsal] 超出 %.0fs：建议缩短单站讲解上限、减少停留点或压缩步行 ETA。"
            % (total - limit)
        )
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "timeline": timeline,
                    "budget_s": args.budget_s,
                    "reserve_s": args.reserve_s,
                    "usable_s": limit,
                    "status": status,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
