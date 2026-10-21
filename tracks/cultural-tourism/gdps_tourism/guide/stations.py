"""Station / target configuration for the cultural-tourism guide.

The site map and waypoints are produced on the robot (SLAM + save_map), so the
checked-in file is an EXAMPLE: fill real poses, tour order, dwell times and
P2 targets after the first mapping session.  Everything else (name resolution,
reachability, ETA) is data-driven and unit-tested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PREFILTER_KINDS = ("exhibit", "landmark", "shop", "poi", "entrance", "outdoor")


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = "map"


@dataclass(frozen=True)
class Station:
    station_id: str
    name: str
    kind: str = "exhibit"
    exhibit_ids: Tuple[str, ...] = ()
    pose: Optional[Pose] = None
    narration_profile: str = "long"  # long | brief
    route_brief: str = ""
    target_aliases: Tuple[str, ...] = ()
    reachable: str = "indoor"  # indoor | outdoor | surrounding
    eta_s: int = 60  # walking time from the tour start point
    area: str = ""

    @property
    def needs_observation(self) -> bool:
        return self.kind == "exhibit" and bool(self.exhibit_ids)


@dataclass(frozen=True)
class TargetResolution:
    query: str
    station: Optional[Station]
    matched_alias: str = ""
    reachable: str = ""
    eta_s: int = 0
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.station is not None


@dataclass
class StationBook:
    stations: List[Station] = field(default_factory=list)
    tour_order: List[str] = field(default_factory=list)
    frame_id: str = "map"

    def __post_init__(self) -> None:
        self._by_id = {station.station_id: station for station in self.stations}
        if not self.tour_order:
            self.tour_order = [station.station_id for station in self.stations]

    # -- queries -----------------------------------------------------------
    def get(self, station_id: str) -> Optional[Station]:
        return self._by_id.get(station_id)

    def ordered_stations(self) -> List[Station]:
        ordered = [self._by_id[sid] for sid in self.tour_order if sid in self._by_id]
        return ordered or list(self.stations)

    def next_after(self, station_id: Optional[str]) -> Optional[Station]:
        ordered = self.ordered_stations()
        if not ordered:
            return None
        if station_id is None:
            return ordered[0]
        ids = [station.station_id for station in ordered]
        if station_id not in ids:
            return ordered[0]
        index = ids.index(station_id)
        if index + 1 >= len(ordered):
            return None
        return ordered[index + 1]

    def resolve_target(self, query: str) -> TargetResolution:
        text = (query or "").strip()
        if not text:
            return TargetResolution(query=query, station=None, note="empty_query")
        # Exact station name / id first, then aliases, then containment match.
        for station in self.stations:
            if text == station.station_id or text == station.name:
                return self._resolution(text, station, text)
        best: Optional[Tuple[int, Station, str]] = None
        for station in self.stations:
            names = [station.name] + list(station.target_aliases)
            for alias in names:
                if not alias:
                    continue
                if alias in text:
                    score = len(alias)
                    if best is None or score > best[0]:
                        best = (score, station, alias)
        if best is not None:
            return self._resolution(text, best[1], best[2])
        return TargetResolution(query=query, station=None, note="unknown_target")

    def _resolution(self, query: str, station: Station, alias: str) -> TargetResolution:
        return TargetResolution(
            query=query,
            station=station,
            matched_alias=alias,
            reachable=station.reachable,
            eta_s=station.eta_s,
        )

    # -- loading -----------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "StationBook":
        payload = _load_mapping(Path(path))
        frame_id = str(payload.get("frame_id") or "map")
        raw_stations = payload.get("stations")
        if not isinstance(raw_stations, list) or not raw_stations:
            raise ValueError("stations config must contain a non-empty stations list")
        stations: List[Station] = []
        seen = set()
        for entry in raw_stations:
            if not isinstance(entry, dict):
                raise ValueError("station entry must be a mapping")
            station_id = str(entry.get("id") or "").strip()
            if not station_id or station_id in seen:
                raise ValueError("station id missing or duplicated: %r" % (station_id,))
            seen.add(station_id)
            pose = entry.get("pose")
            parsed_pose = None
            if isinstance(pose, dict):
                parsed_pose = Pose(
                    x=float(pose.get("x", 0.0)),
                    y=float(pose.get("y", 0.0)),
                    yaw=float(pose.get("yaw", 0.0)),
                    frame_id=str(pose.get("frame_id") or frame_id),
                )
            kind = str(entry.get("kind") or "exhibit")
            if kind not in PREFILTER_KINDS:
                raise ValueError("station %s has unknown kind %r" % (station_id, kind))
            stations.append(
                Station(
                    station_id=station_id,
                    name=str(entry.get("name") or station_id),
                    kind=kind,
                    exhibit_ids=tuple(str(x) for x in entry.get("exhibit_ids") or ()),
                    pose=parsed_pose,
                    narration_profile=str(entry.get("narration_profile") or "long"),
                    route_brief=str(entry.get("route_brief") or ""),
                    target_aliases=tuple(str(x) for x in entry.get("target_aliases") or ()),
                    reachable=str(entry.get("reachable") or "indoor"),
                    eta_s=int(entry.get("eta_s") or 60),
                    area=str(entry.get("area") or ""),
                )
            )
        order = [str(sid) for sid in payload.get("tour_order") or []]
        unknown = [sid for sid in order if sid not in seen]
        if unknown:
            raise ValueError("tour_order references unknown stations: %r" % (unknown,))
        return cls(stations=stations, tour_order=order, frame_id=frame_id)


def _load_mapping(path: Path) -> Dict[str, Any]:
    """Load YAML config, falling back to a sibling .json (robot may lack PyYAML)."""

    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            fallback = path.with_suffix(".json")
            if not fallback.is_file():
                raise ImportError("PyYAML is required for %s (or provide %s)" % (path, fallback.name))
            return _read_json(fallback)
        return _as_mapping(yaml.safe_load(path.read_text(encoding="utf-8")), path)
    if suffix == ".json":
        return _read_json(path)
    raise ValueError("unsupported config suffix: %s" % suffix)


def _read_json(path: Path) -> Dict[str, Any]:
    return _as_mapping(json.loads(path.read_text(encoding="utf-8")), path)


def _as_mapping(value: Any, path: Path) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("config root must be a mapping: %s" % path)
    return value


__all__ = ["Pose", "Station", "StationBook", "TargetResolution"]
