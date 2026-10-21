#!/usr/bin/env python3
"""Validate the tourism guide configuration before going to the robot.

Checks (no ROS / no camera needed):
  stations.yaml   : ids, tour order, exhibit mapping, poses, brief lengths
  knowledge_base  : narration / images presence, exhibit ids
  dialogue KB     : verified flag, P1 fact categories
  templates dir   : every referenced image file exists
  fallback audio  : every narration/brief has a generated wav entry

Exit code 0 = no errors (warnings allowed), 1 = errors found.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

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

P1_CATEGORIES = ("场馆基本信息", "建筑导览", "庭院服务", "参观建议")


@dataclass
class Report:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.info.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "info": self.info}


def _load_json(path: Optional[Path]):
    if path is None or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check(
    stations_path: Path,
    *,
    knowledge_path: Optional[Path] = None,
    dialogue_path: Optional[Path] = None,
    templates_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    max_brief_chars: int = 30,
) -> Report:
    report = Report()
    try:
        book = StationBook.load(stations_path)
    except Exception as exc:
        report.error("stations config invalid: %s" % exc)
        return report
    report.note("stations: %d (tour order %d)" % (len(book.stations), len(book.tour_order)))

    knowledge = _load_json(knowledge_path)
    knowledge_ids: Dict[str, dict] = {}
    if knowledge is not None:
        for item in (knowledge.get("exhibits") or []) + (knowledge.get("composite_boards") or []):
            item_id = str(item.get("id") or "")
            if item_id:
                knowledge_ids[item_id] = item
        report.note("knowledge_base exhibits: %d" % len(knowledge_ids))
    else:
        report.warn("knowledge_base.json not provided; exhibit mapping not checked")

    tour_ids = set(book.tour_order) or {station.station_id for station in book.stations}
    placeholder_poses = 0
    for station in book.stations:
        if station.pose is None:
            if station.station_id in tour_ids:
                report.warn("station %s has no pose (navigation will fail)" % station.station_id)
        elif abs(station.pose.x) < 1e-6 and abs(station.pose.y) < 1e-6 and abs(station.pose.yaw) < 1e-6:
            placeholder_poses += 1
        for exhibit_id in station.exhibit_ids:
            if knowledge_ids and exhibit_id not in knowledge_ids:
                report.error("station %s references unknown exhibit %s" % (station.station_id, exhibit_id))
        for exhibit_id in station.route_match_exhibit_ids:
            if knowledge_ids and exhibit_id not in knowledge_ids:
                report.warn("station %s route_match_exhibit %s missing in knowledge_base" % (station.station_id, exhibit_id))
        if station.route_brief and len(station.route_brief) > max_brief_chars:
            report.warn(
                "station %s route_brief is %d chars (>%d), P3 should stay short"
                % (station.station_id, len(station.route_brief), max_brief_chars)
            )
        if station.needs_observation and not station.exhibit_ids:
            report.error("station %s is exhibit-kind but has no exhibit_ids" % station.station_id)
    if placeholder_poses:
        report.warn("%d/%d stations still have placeholder pose (0,0,0)" % (placeholder_poses, len(book.stations)))

    dialogue = _load_json(dialogue_path)
    if dialogue is not None:
        meta = dialogue.get("meta") or {}
        verified = meta.get("verified")
        if verified in (None, False, "false", "no", "unknown"):
            report.warn("dialogue knowledge is still a placeholder (meta.verified=%r)" % (verified,))
        elif verified == "partial":
            report.note("dialogue knowledge verified=partial (pending_verification filled in file)")
        facts = dialogue.get("venue_facts") or {}
        for category in P1_CATEGORIES:
            if category not in facts:
                report.warn("P1 category missing: %s" % category)
        if not dialogue.get("refusal_text"):
            report.warn("P1 refusal_text missing (out-of-scope answers must decline)")
        if len(dialogue.get("refusal_rules") or []) < 2:
            report.warn("P1 refusal_rules is short (<2)")
        if len(dialogue.get("faq") or []) < 10:
            report.warn("P1 FAQ is short (<10 Q&A pairs)")
        if len(meta.get("sources") or []) < 2:
            report.warn("P1 sources missing (<2 URLs) - facts must be traceable")
        if len(dialogue.get("recommendations") or []) < 3:
            report.warn("P5 recommendation list is short (<3)")
    else:
        report.warn("dialogue knowledge json not provided (P1/P5 answers will be empty)")

    if templates_dir is not None:
        if not Path(templates_dir).is_dir():
            report.error("templates dir does not exist: %s" % templates_dir)
        elif knowledge is not None:
            missing = 0
            for item in (knowledge.get("exhibits") or []) + (knowledge.get("composite_boards") or []):
                for name in list(item.get("associated_images") or []) + [item.get("primary_image")]:
                    if not name:
                        continue
                    if not (Path(templates_dir) / name).is_file():
                        report.error("template image missing: %s" % name)
                        missing += 1
            if missing == 0:
                report.note("template images: all referenced files present")

    if manifest_path is not None and knowledge is not None:
        manifest = load_manifest(manifest_path)
        if not manifest:
            report.warn("fallback manifest missing or empty: %s" % manifest_path)
        else:
            missing_texts = 0
            for item in (knowledge.get("exhibits") or []) + (knowledge.get("composite_boards") or []):
                narration = str(item.get("narration") or "").strip()
                if narration and text_key(narration) not in manifest:
                    report.warn("no fallback audio for %s narration" % (item.get("id") or "?"))
                    missing_texts += 1
            for station in book.stations:
                brief = str(station.route_brief or "").strip()
                if brief and text_key(brief) not in manifest:
                    report.warn("no fallback audio for %s route_brief" % station.station_id)
                    missing_texts += 1
            if missing_texts == 0:
                report.note("fallback audio: all narrations/briefs covered")

    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate tourism guide configuration")
    parser.add_argument("--stations", default=str(TOURISM_ROOT / "configs" / "stations.example.yaml"))
    parser.add_argument("--knowledge", default=None, help="knowledge_base.json")
    parser.add_argument(
        "--dialogue",
        default=None,
        help="dialogue KB (default: knowledge_dialogue.json, then example)",
    )
    parser.add_argument("--templates", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    dialogue_path = Path(args.dialogue) if args.dialogue else None
    if dialogue_path is None:
        for name in ("knowledge_dialogue.json", "knowledge_dialogue.example.json"):
            candidate = TOURISM_ROOT / "configs" / name
            if candidate.is_file():
                dialogue_path = candidate
                break
    report = check(
        Path(args.stations),
        knowledge_path=Path(args.knowledge) if args.knowledge else None,
        dialogue_path=dialogue_path,
        templates_dir=Path(args.templates) if args.templates else None,
        manifest_path=Path(args.manifest) if args.manifest else None,
    )
    for line in report.info:
        print("[ok]   " + line)
    for line in report.warnings:
        print("[warn] " + line)
    for line in report.errors:
        print("[err]  " + line)
    print("\n[config-check] errors=%d warnings=%d -> %s" % (len(report.errors), len(report.warnings), "PASS" if report.ok else "FAIL"))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
