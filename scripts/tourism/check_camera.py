#!/usr/bin/env python3
"""Read-only camera check for the tourism guide.

Lists video nodes, tries to open each one, prints formats/fps, saves one frame
and (optionally) runs the exhibit matcher on that frame.  Never moves the robot.

Examples:
    python3 scripts/tourism/check_camera.py                      # list + capture
    python3 scripts/tourism/check_camera.py --camera 4 --flip 180
    python3 scripts/tourism/check_camera.py --match-templates ~/tourism_guide/templates
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOURISM_ROOT = ROOT / "tracks" / "cultural-tourism"
for candidate in (ROOT, TOURISM_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import cv2  # noqa: E402


def list_nodes() -> list:
    nodes = sorted(Path("/dev").glob("video*"), key=lambda p: int(p.name.replace("video", "") or 0))
    return [str(node) for node in nodes]


def apply_flip(frame, flip: str):
    if flip == "180":
        return frame[::-1, ::-1].copy()
    if flip == "hflip":
        return frame[:, ::-1].copy()
    if flip == "vflip":
        return frame[::-1].copy()
    return frame


def probe_node(device: str, width: int, height: int, frames: int) -> dict:
    report = {"device": device, "opened": False}
    if shutil.which("v4l2-ctl"):
        try:
            text = subprocess.check_output(
                ["v4l2-ctl", "-d", device, "--list-formats-ext"],
                stderr=subprocess.STDOUT,
                timeout=5,
            ).decode("utf-8", "replace")
            report["formats"] = [
                line.strip() for line in text.splitlines() if ":" in line and ("Size" in line or "[" in line)
            ][:6]
        except (subprocess.SubprocessError, OSError) as exc:
            report["formats_error"] = str(exc)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        report["opened"] = False
        return report
    report["opened"] = True
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    report["reported"] = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": round(float(cap.get(cv2.CAP_PROP_FPS)), 1),
    }
    frame = None
    started = time.perf_counter()
    good = 0
    for _ in range(max(1, frames)):
        ok, current = cap.read()
        if ok and current is not None:
            frame = current
            good += 1
    elapsed = time.perf_counter() - started
    report["frames"] = good
    report["measured_fps"] = round(good / elapsed, 1) if good and elapsed > 0 else 0.0
    if frame is not None:
        report["shape"] = list(frame.shape)
    cap.release()
    report["frame"] = frame
    return report


def match_frame(frame, templates: str, method: str) -> dict:
    from gdps_tourism.matching.feature_matcher import ExhibitMatcher, TemplateLibrary

    library = TemplateLibrary.from_directory(Path(templates), method=method, max_side=1200, max_features=1500)
    matcher = ExhibitMatcher(library, max_side=1200, prefilter="orb")
    result = matcher.match(frame)
    best = result.best
    return {
        "accepted": result.accepted,
        "unknown_reason": result.unknown_reason,
        "best": None
        if best is None
        else {
            "template_id": best.template_id,
            "display_name": best.display_name,
            "confidence": round(best.confidence, 3),
            "inliers": best.inliers,
            "exhibit_id": best.info.exhibit_id,
        },
        "diagnostics": result.diagnostics,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only camera check")
    parser.add_argument("--camera", default="auto", help="auto | device path | index")
    parser.add_argument("--width", type=int, default=0, help="0 = keep driver default")
    parser.add_argument("--height", type=int, default=0)
    parser.add_argument("--frames", type=int, default=15)
    parser.add_argument("--flip", choices=("none", "180", "hflip", "vflip"), default="none")
    parser.add_argument("--out", default="/tmp/tourism_camera_frame.jpg")
    parser.add_argument("--match-templates", default=None)
    parser.add_argument("--method", choices=("orb", "sift"), default="orb")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    nodes = list_nodes()
    print("[camera] nodes:", nodes or "none")
    candidates = []
    if args.camera == "auto":
        preferred = ["/dev/video4", "/dev/video2"]
        candidates = [d for d in preferred if d in nodes] + [d for d in nodes if d not in preferred]
    elif str(args.camera).isdigit():
        candidates = [int(args.camera)]
    else:
        candidates = [args.camera]

    chosen = None
    reports = []
    for device in candidates:
        report = probe_node(device, args.width, args.height, args.frames)
        frame = report.pop("frame", None)
        reports.append(report)
        print("[camera] %r opened=%s frames=%s fps=%s shape=%s" % (
            report["device"], report.get("opened"), report.get("frames"), report.get("measured_fps"), report.get("shape"))
        )
        if frame is not None and chosen is None:
            chosen = {"device": device, "frame": frame, "report": report}

    output = {"nodes": nodes, "reports": reports, "capture": None, "match": None}
    if chosen is None:
        print("[camera] no working video node", file=sys.stderr)
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    frame = apply_flip(chosen["frame"], args.flip)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    output["capture"] = {"device": chosen["device"], "flip": args.flip, "path": str(out_path), "shape": list(frame.shape)}
    print("[camera] captured %s -> %s shape=%s" % (chosen["device"], out_path, frame.shape))

    if args.match_templates:
        result = match_frame(frame, args.match_templates, args.method)
        output["match"] = result
        print("[camera] match:", json.dumps(result, ensure_ascii=False))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
