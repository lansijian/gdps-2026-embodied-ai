#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark harness for the tourism exhibit camera matcher.

Measures wall-clock matching cost and synthetic-scene accuracy (top-1 / top-k /
false accepts) so optimisations can be compared with numbers instead of claims.

Usage:
    .venv/bin/python tools/bench_camera.py --method sift --tag baseline
    .venv/bin/python tools/bench_camera.py --method orb  --tag orb
    .venv/bin/python tools/bench_camera.py --method sift --profile   # stage breakdown
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]  # repository root
TRACK_ROOT = ROOT / "tracks" / "cultural-tourism"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TRACK_ROOT))

from gdps_tourism.matching.feature_matcher import ExhibitMatcher, TemplateLibrary  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "bench_results"
CANVAS = (1280, 720)


def load_exhibit_map(templates_dir: Path) -> dict:
    """stem -> (exhibit_id, exhibit_name) from knowledge_base.json, if present."""
    mapping = {}
    for candidate in (templates_dir / "knowledge_base.json", templates_dir.parent / "knowledge_base.json"):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = payload.get("exhibits", []) + payload.get("composite_boards", [])
        for item in items:
            exhibit_id = item.get("id") or item.get("name")
            name = item.get("name") or exhibit_id
            for entry in list(item.get("associated_images", [])):
                mapping[Path(entry).stem] = (exhibit_id, name)
            if item.get("primary_image"):
                mapping[Path(item["primary_image"]).stem] = (exhibit_id, name)
        break
    return mapping

def group_of(stem, mapping):
    return mapping.get(stem, (stem, stem))[0]



def read_bgr(path: Path) -> np.ndarray:
    payload = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(payload, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("cannot read %s" % path)
    return image


def _background(rng: np.random.Generator) -> np.ndarray:
    width, height = CANVAS
    base = float(rng.integers(18, 70))
    grad = np.linspace(0.75, 1.25, height, dtype=np.float32)[:, None]
    column = np.clip(base * grad, 0, 255).astype(np.uint8)  # (height, 1)
    canvas = np.repeat(column[:, :, None], 3, axis=2)  # (height, 1, 3)
    canvas = np.repeat(canvas, width, axis=1)  # (height, width, 3)
    for _ in range(rng.integers(1, 4)):
        colour = tuple(int(v) for v in rng.integers(10, 80, size=3))
        p1 = (int(rng.integers(0, width)), int(rng.integers(0, height)))
        p2 = (int(rng.integers(0, width)), int(rng.integers(0, height)))
        cv2.rectangle(canvas, p1, p2, colour, -1)
    return canvas


def make_scene(template_bgr: np.ndarray, rng: np.random.Generator, fill: float) -> np.ndarray:
    """Paste a perspective-warped template onto a dark synthetic gallery scene."""
    width, height = CANVAS
    th, tw = template_bgr.shape[:2]
    target_w = fill * width * float(rng.uniform(0.85, 1.15))
    target_h = target_w * th / float(tw)
    if target_h > 0.92 * height:
        target_h = 0.92 * height
        target_w = target_h * tw / float(th)
    cx = width / 2.0 + float(rng.normal(0, 0.05 * width))
    cy = height / 2.0 + float(rng.normal(0, 0.05 * height))
    hw, hh = target_w / 2.0, target_h / 2.0
    jitter = 0.06 * min(hw, hh)
    dst = np.float32(
        [
            [cx - hw + rng.normal(0, jitter), cy - hh + rng.normal(0, jitter)],
            [cx + hw + rng.normal(0, jitter), cy - hh + rng.normal(0, jitter)],
            [cx + hw + rng.normal(0, jitter), cy + hh + rng.normal(0, jitter)],
            [cx - hw + rng.normal(0, jitter), cy + hh + rng.normal(0, jitter)],
        ]
    )
    src = np.float32([[0, 0], [tw, 0], [tw, th], [0, th]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(template_bgr, matrix, (width, height), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(
        np.full((th, tw), 255, np.uint8), matrix, (width, height), flags=cv2.INTER_NEAREST
    )
    scene = _background(rng)
    scene[mask > 0] = warped[mask > 0]
    if rng.random() < 0.75:
        scene = cv2.GaussianBlur(scene, (3, 3), float(rng.uniform(0.2, 1.0)))
    gain = float(rng.uniform(0.85, 1.18))
    scene = np.clip(scene.astype(np.float32) * gain + float(rng.normal(0, 4)), 0, 255).astype(np.uint8)
    ok, encoded = cv2.imencode(".jpg", scene, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) if ok else scene


def make_negative(rng: np.random.Generator, kind: int) -> np.ndarray:
    width, height = CANVAS
    if kind == 0:
        frame = rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)
    elif kind == 1:
        frame = _background(rng)
    else:
        frame = np.full((height, width, 3), 40, np.uint8)
        for _ in range(6):
            text = "".join(chr(int(c)) for c in rng.integers(65, 90, size=12))
            cv2.putText(
                frame,
                text,
                (int(rng.integers(0, width - 200)), int(rng.integers(30, height))),
                cv2.FONT_HERSHEY_SIMPLEX,
                float(rng.uniform(0.8, 2.0)),
                tuple(int(v) for v in rng.integers(120, 255, size=3)),
                2,
                cv2.LINE_AA,
            )
    return frame


def profile_match(matcher: ExhibitMatcher, frame: np.ndarray) -> dict:
    """Replicate ExhibitMatcher.match with stage timings (used for diagnosis only)."""
    cv2_mod = cv2
    marks = {}

    def mark(name: str, started: float) -> float:
        now = time.perf_counter()
        marks[name] = marks.get(name, 0.0) + (now - started) * 1000.0
        return now

    t = time.perf_counter()
    gray = cv2_mod.cvtColor(frame, cv2_mod.COLOR_BGR2GRAY)
    gray = cv2_mod.resize(gray, (matcher.max_side, matcher.max_side)) if max(gray.shape) > matcher.max_side else gray
    t = mark("pre", t)
    keypoints, query_des = matcher.library.detector.detectAndCompute(gray, None)
    t = mark("detect", t)
    per_template = []
    ratio_good = 0
    for info, template_kp, template_des in zip(
        matcher.library.templates, matcher.library.keypoints, matcher.library.descriptors
    ):
        started = time.perf_counter()
        good = matcher._ratio_matches(query_des, template_des)
        marks["bf"] = marks.get("bf", 0.0) + (time.perf_counter() - started) * 1000.0
        per_template.append(len(good))
        ratio_good += len(good)
        if len(good) < 4:
            continue
        started = time.perf_counter()
        template_pts = np.float32([template_kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        query_pts = np.float32([keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        try:
            cv2_mod.findHomography(template_pts, query_pts, cv2_mod.RANSAC, matcher.ransac_reproj_px)
        except cv2_mod.error:
            pass
        marks["ransac"] = marks.get("ransac", 0.0) + (time.perf_counter() - started) * 1000.0
        t = time.perf_counter()
    marks["total"] = sum(v for k, v in marks.items() if k != "total")
    marks["query_features"] = 0 if keypoints is None else len(keypoints)
    marks["good_matches"] = ratio_good
    marks["templates_with_4plus"] = int(sum(1 for v in per_template if v >= 4))
    return marks


def is_same_exhibit(pred_stem, gt_stem, mapping) -> bool:
    if not pred_stem or not gt_stem:
        return False
    if pred_stem == gt_stem:
        return True
    return group_of(pred_stem, mapping) == group_of(gt_stem, mapping)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", default=str(ROOT))
    parser.add_argument("--method", choices=("sift", "orb"), default="sift")
    parser.add_argument("--max-side", type=int, default=1200)
    parser.add_argument("--max-features", type=int, default=1500)
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=0, help="only the first N templates")
    parser.add_argument("--fills", default="0.45,0.70", help="simulated exhibit frame fill ratios")
    parser.add_argument("--negatives", type=int, default=6)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--tag", default="run")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--opt", action="append", default=[], help="extra ExhibitMatcher kwarg key=value")
    args = parser.parse_args(argv)

    mapping = load_exhibit_map(Path(args.templates))
    started = time.perf_counter()
    library = TemplateLibrary.from_directory(
        Path(args.templates), method=args.method, max_side=args.max_side, max_features=args.max_features
    )
    build_ms = (time.perf_counter() - started) * 1000.0
    extra = {}
    for item in args.opt:
        key, _, value = item.partition("=")
        if value.lower() in ("true", "false"):
            extra[key] = value.lower() == "true"
        elif value.replace(".", "", 1).lstrip("-").isdigit():
            extra[key] = int(value) if "." not in value else float(value)
        else:
            extra[key] = value
    matcher = ExhibitMatcher(library, max_side=args.max_side, **extra)
    print(
        "[bench] templates=%d method=%s build=%.0fms extra=%s"
        % (len(library), matcher.method_used, build_ms, json.dumps(extra, ensure_ascii=False)),
        flush=True,
    )

    fills = [float(v) for v in args.fills.split(",") if v.strip()]
    rng = np.random.default_rng(20261020)
    scenes = []
    for info in library.templates[: args.limit or None]:
        template_bgr = read_bgr(info.source_path)
        for fill in fills:
            seed = int(rng.integers(0, 2**31 - 1))
            scenes.append(
                (
                    info.template_id,
                    group_of(info.template_id, mapping),
                    fill,
                    make_scene(template_bgr, np.random.default_rng(seed), fill),
                )
            )

    warmup = scenes[0][3]
    for _ in range(2):
        matcher.match(warmup)

    timings, rows, profile_rows = [], [], []
    for gt_id, gt_group, fill, frame in scenes:
        started = time.perf_counter()
        result = matcher.match(frame)
        elapsed = (time.perf_counter() - started) * 1000.0
        timings.append(elapsed)
        best = result.best
        top = result.candidates
        top_ids = [c.template_id for c in top]
        pred_group = group_of(best.template_id, mapping) if best else None
        rows.append(
            {
                "gt": gt_id,
                "gt_group": gt_group,
                "fill": fill,
                "pred": best.template_id if best else None,
                "pred_group": pred_group,
                "pred_name": best.display_name if best else None,
                "accepted": result.accepted,
                "reason": result.unknown_reason,
                "inliers": best.inliers if best else 0,
                "second_inliers": top[1].inliers if len(top) > 1 else 0,
                "elapsed_ms": round(elapsed, 2),
                "top_ids": top_ids,
                "diagnostics": result.diagnostics,
            }
        )
        if args.profile and len(profile_rows) < 4:
            profile_rows.append(profile_match(matcher, frame))

    negative_accepts = 0
    negative_times = []
    for kind in range(args.negatives):
        frame = make_negative(rng, kind % 3)
        started = time.perf_counter()
        result = matcher.match(frame)
        negative_times.append((time.perf_counter() - started) * 1000.0)
        if result.accepted:
            negative_accepts += 1

    accepted = [r for r in rows if r["accepted"]]
    correct = [r for r in accepted if r["pred_group"] == r["gt_group"]]
    topk_hit = [r for r in rows if any(group_of(c, mapping) == r["gt_group"] for c in r["top_ids"])]
    all_ms = timings + negative_times

    def pct(values, p):
        if not values:
            return 0.0
        ordered = sorted(values)
        idx = min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1))))
        return ordered[idx]

    report = {
        "tag": args.tag,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": matcher.method_used,
        "max_side": args.max_side,
        "max_features": args.max_features,
        "matcher_extra": extra,
        "templates": len(library),
        "exhibits": len({group_of(t, mapping) for t in library.ids}),
        "build_ms": round(build_ms, 1),
        "mean_ms": round(statistics.fmean(all_ms), 1),
        "median_ms": round(statistics.median(all_ms), 1),
        "p95_ms": round(pct(all_ms, 95), 1),
        "queries": len(rows),
        "negatives": args.negatives,
        "accept_rate": round(len(accepted) / len(rows), 3) if rows else 0.0,
        "exhibit_top1_accuracy": round(len(correct) / len(accepted), 3) if accepted else 0.0,
        "exhibit_top1_overall": round(len(correct) / len(rows), 3) if rows else 0.0,
        "exhibit_topk_recall": round(len(topk_hit) / len(rows), 3) if rows else 0.0,
        "file_top1_accuracy": round(
            sum(1 for r in accepted if r["pred"] == r["gt"]) / len(accepted), 3
        ) if accepted else 0.0,
        "false_accepts": negative_accepts,
        "rows": rows,
    }
    if profile_rows:
        aggregate = {}
        for key in profile_rows[0]:
            aggregate[key] = round(statistics.fmean([row[key] for row in profile_rows]), 2)
        report["profile_ms"] = aggregate

    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2, ensure_ascii=False))
    if not args.quiet:
        for row in rows:
            flag = "OK " if row["accepted"] and row["pred_group"] == row["gt_group"] else "!! "
            print(
                "%s gt=%-4s grp=%-8s fill=%.2f pred=%-4s acc=%-5s inl=%-4d second=%-4d %7.1fms %s"
                % (
                    flag,
                    row["gt"],
                    row["gt_group"],
                    row["fill"],
                    row["pred"],
                    row["accepted"],
                    row["inliers"],
                    row["second_inliers"],
                    row["elapsed_ms"],
                    row["reason"] or "",
                )
            )

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        history = RESULTS_DIR / "history.jsonl"
        with history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        print("[bench] appended %s" % history)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())