#!/usr/bin/env python3
"""Two independent Gemini readings of prepared crops. A probe, not production export."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Annotated, Literal

import cv2 as cv
import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts/gemini_drawing.md"
API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_CASES = ["1:mid", "3:coronal", "7:base", "13:apex", "14:mid", "17:mid", "27:sagittal", "33:apex"]
Status = Literal["recorded", "not reported", "unreadable", "not assessed", "not applicable"]
Certainty = Literal["unassessed", "high", "medium", "low"]
Coord = Annotated[int, Field(strict=True, ge=0, le=1000)]
Point = Annotated[list[Coord], Field(min_length=2, max_length=2)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextReading(Strict):
    status: Status
    value: str | None
    certainty: Certainty
    reason: str

    @model_validator(mode="after")
    def available_value(self):
        if (self.status == "recorded" and not self.value) or (self.status != "recorded" and self.value is not None):
            raise ValueError("Recorded text needs a nonempty value; unavailable text needs null")
        return self


class Sector(Strict):
    zone: Literal["AFS", "PZa", "PZpl", "PZpm", "TZa", "TZp", "CZ", "SV", "urethra"]
    level: Literal["base", "mid", "apex", "seminal_vesicles", "urethra", "unspecified"]
    image_side: Literal["left", "right", "midline", "unclear"]
    contact: Literal["enclosed", "boundary_touch", "unclear"]


class SectorReading(Strict):
    status: Status
    value: list[Sector] | None
    candidates: list[Sector]
    certainty: Certainty
    reason: str

    @model_validator(mode="after")
    def available_value(self):
        if (self.status == "recorded" and not self.value) or (self.status != "recorded" and self.value is not None):
            raise ValueError("Recorded sectors need values; unavailable sectors need null")
        return self


class Geometry(Strict):
    kind: Literal["closed_outline", "open_polyline", "filled_region", "none"]
    points_xy: Annotated[list[Point], Field(max_length=64)]
    reason: str

    @model_validator(mode="after")
    def enough_points(self):
        minimum = {"none": 0, "open_polyline": 2, "closed_outline": 3, "filled_region": 3}[self.kind]
        if len(self.points_xy) < minimum or (self.kind == "none" and self.points_xy):
            raise ValueError("Geometry kind and point count disagree")
        return self


class Mark(Strict):
    id: str
    kind: Literal["outline", "open_arc", "filled_region", "arrow", "measurement", "text", "laterality_label", "other", "uncertain"]
    appearance: str
    location_note: str
    box_2d: Annotated[list[Coord], Field(min_length=4, max_length=4)]
    geometry: Geometry
    handwriting: TextReading
    sectors: SectorReading
    extraction_certainty: Certainty
    interpretation_certainty: Certainty
    uncertainty_reason: str

    @model_validator(mode="after")
    def ordered_box(self):
        y0, x0, y1, x1 = self.box_2d
        if y0 >= y1 or x0 >= x1:
            raise ValueError("box_2d must have positive width and height")
        if self.kind == "open_arc" and self.geometry.kind in ("closed_outline", "filled_region"):
            raise ValueError("An open arc cannot acquire a closed polygon")
        return self


class Reading(Strict):
    coverage: Literal["complete", "partial", "unreadable"]
    coverage_issues: list[str]
    marks: Annotated[list[Mark], Field(max_length=60)]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({m.id for m in self.marks}) != len(self.marks):
            raise ValueError("Mark IDs must be unique within a reading")
        return self


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def api_schema():
    # Nested bounded arrays exceed Gemini's schema compiler limits on this route.
    # Keep exact lengths and maxima in local Pydantic validation.
    def remove_array_bounds(value):
        if isinstance(value, dict):
            return {k: remove_array_bounds(v) for k, v in value.items() if k not in ("minItems", "maxItems")}
        if isinstance(value, list):
            return [remove_array_bounds(v) for v in value]
        return value
    return remove_array_bounds(Reading.model_json_schema())


def request_body(prompt, image_bytes, resolution="high", thinking="low"):
    return {"contents": [{"role": "user", "parts": [
        {"text": prompt},
        {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image_bytes).decode()}},
    ]}], "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": api_schema(),
        "mediaResolution": "MEDIA_RESOLUTION_" + resolution.upper(), "thinkingConfig": {"thinkingLevel": thinking.upper()},
        "maxOutputTokens": 12000, "temperature": 1.0}}


def parse_response(response):
    candidates = response.get("candidates", [])
    if not candidates or candidates[0].get("finishReason") != "STOP":
        raise ValueError("No complete candidate: " + str(candidates[0].get("finishReason") if candidates else response.get("promptFeedback")))
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    return Reading.model_validate_json(text)


def call_with_retry(client, url, key, body, out, sleeper=time.sleep):
    history = []
    for attempt in (1, 2):
        start = time.perf_counter()
        retryable = True
        entry = {"attempt": attempt}
        try:
            response = client.post(url, headers={"x-goog-api-key": key}, json=body)
            entry["http_status"] = response.status_code
            if response.status_code >= 400:
                retryable = response.status_code in (408, 429, 500, 502, 503, 504)
                save(out / f"attempt_{attempt}_error.json", response.json())
                raise ValueError(f"HTTP {response.status_code}")
            raw = response.json()
            save(out / f"attempt_{attempt}_response.json", raw)
            entry["usage"] = raw.get("usageMetadata", {})
            entry["model_version"] = raw.get("modelVersion")
            parsed = parse_response(raw)
            entry["seconds"] = round(time.perf_counter() - start, 2)
            history.append(entry)
            return parsed, history
        except (httpx.RequestError, ValueError) as error:
            # Keys are only in a header, never in the URL, payload or log.
            entry.update(error=str(error).replace(key, "[redacted]"), seconds=round(time.perf_counter() - start, 2))
            history.append(entry)
            if not retryable or attempt == 2:
                return None, history
            sleeper(2)
    raise AssertionError("Unreachable")


def has_crossing_segments(points):
    points = list(points)
    if np.array_equal(points[0], points[-1]):
        points = points[:-1]
    def orientation(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            c, d = points[j], points[(j + 1) % n]
            if orientation(a, b, c) * orientation(a, b, d) < 0 and orientation(c, d, a) * orientation(c, d, b) < 0:
                return True
    return False


def polygon_diagnostics(mark, mask, bounds, crop_to_original, sectors):
    geometry = mark.geometry
    if not geometry.points_xy:
        return {"available": False}
    h, w = mask.shape
    points = np.array(geometry.points_xy, np.float32) * [w / 1000, h / 1000]
    closed = geometry.kind in ("closed_outline", "filled_region")
    crossing = closed and has_crossing_segments(points)
    contour = np.round(points).astype(np.int32).reshape(-1, 1, 2)
    stroke = np.zeros_like(mask)
    cv.polylines(stroke, [contour], closed, 255, 1)
    distance = cv.distanceTransform((mask == 0).astype(np.uint8), cv.DIST_L2, 3)
    values = distance[stroke > 0]
    result = {"available": True, "basis": "calculated", "review_status": "needs review",
              "geometry_basis": "inferred", "closed": closed,
              "source_points_xy": cv.perspectiveTransform(points.astype(np.float64).reshape(-1, 1, 2), np.array(crop_to_original))[:, 0].tolist(),
              "median_distance_to_cv_ink_px": float(np.median(values)) if values.size and mask.any() else None,
              "fraction_within_3px_of_cv_ink": float(np.mean(values <= 3)) if values.size and mask.any() else None,
              "caveat": "CV ink is incomplete and is not ground truth. Reference keys describe template positions, not confirmed patient side or REDCap codes."}
    issues = []
    if crossing:
        issues.append("Polygon has crossing segments; no filled-area overlap was computed.")
    if closed and cv.contourArea(contour) == 0:
        issues.append("Closed polygon has zero area.")
    box = mark.box_2d
    normalized = np.array(geometry.points_xy)
    if (np.any(normalized[:, 0] < box[1] - 20) or np.any(normalized[:, 0] > box[3] + 20)
            or np.any(normalized[:, 1] < box[0] - 20) or np.any(normalized[:, 1] > box[2] + 20)):
        issues.append("Contour extends beyond the model's own box; coordinate proposals disagree.")
    result["geometry_issues"] = issues
    eligible = mark.kind in ("outline", "open_arc", "filled_region") and not issues
    region = stroke.copy()
    if closed and eligible:
        cv.fillPoly(region, [contour], 255)
    contacts = []
    if eligible:
        for sector in sectors:
            polygon = np.array(sector["reference_coordinates_px"]) - bounds[:2]
            target = np.zeros_like(mask)
            cv.fillPoly(target, [np.round(polygon).astype(np.int32)], 255)
            pixels = int(np.count_nonzero((region > 0) & (target > 0)))
            if pixels:
                contacts.append({"reference_key": sector["key"], "template_name": sector["name"], "intersection_pixels": pixels, "marginal": pixels < 10})
    result["reference_polygon_contacts"] = contacts
    result["polygon_area_px"] = float(cv.contourArea(contour)) if closed else None
    return result


def run_job(job, args, run_root, key):
    case, model, pass_name = job
    number, view = case.split(":")
    prepared = args.input_root / f"scan_{int(number):04}"
    source_metadata = json.loads((prepared / "metadata.json").read_text())
    if "failure" in source_metadata:
        raise ValueError(f"{case}: preprocessing failed")
    crop_metadata = source_metadata["views"][view]
    image = prepared / view / ("original.png" if pass_name == "A" else "modified.png")
    out = run_root / model / f"scan_{int(number):04}_{view}" / pass_name
    out.mkdir(parents=True)
    shutil.copy2(image, out / "input.png")
    representation = "A: original colour scan. Inspect all visible additions, including those faint or absent in any unknown preprocessing." if pass_name == "A" else "B: recovered solid-black handwriting on the clean coloured reference. Only this modified image is supplied. Its original ink colours are unavailable."
    prompt = PROMPT.read_text() + f"\n\nCurrent panel: {view}.\nRepresentation {representation}\n"
    body = request_body(prompt, image.read_bytes(), args.resolution, args.thinking)
    request = {"case": case, "requested_model": model, "provider_route": "Gemini Developer API / stateless generateContent",
               "pass": pass_name, "prompt": prompt, "prompt_sha256": digest(PROMPT), "schema": Reading.model_json_schema(),
               "generation_config": body["generationConfig"], "input_sha256": digest(image),
               "source_metadata": source_metadata, "crop_metadata": crop_metadata,
               "script_sha256": digest(Path(__file__)), "input_path": str(image.relative_to(ROOT)),
               "independence": "One image, one fresh contents message; no report, CV candidates, other-pass or other-model answer."}
    save(out / "request.json", request)
    if args.dry_run:
        return {"case": case, "model": model, "pass": pass_name, "status": "prepared", "path": str(out.relative_to(run_root))}
    with httpx.Client(timeout=args.timeout) as client:
        reading, history = call_with_retry(client, f"{API}/models/{model}:generateContent", key, body, out)
    result = {"case": case, "model": model, "pass": pass_name, "status": "ok" if reading else "failed",
              "attempts": history, "input_sha256": request["input_sha256"], "source_sha256": source_metadata["source_sha256"],
              "crop_metadata": crop_metadata, "review_status": "needs review", "schema_version": "drawing-probe-1",
              "path": str(out.relative_to(run_root))}
    if reading:
        result["reading"] = reading.model_dump()
        mask = cv.imread(str(prepared / view / "mask.png"), 0)
        sectors = json.loads((ROOT / "Other/reference/sectors.json").read_text())["sectors"]
        result["geometry_diagnostics"] = {m.id: polygon_diagnostics(m, mask, np.array(crop_metadata["bounds_xywh"]), crop_metadata["crop_to_original"], sectors) for m in reading.marks}
        result["observation_bases"] = {"handwriting": "explicit", "mark_kind": "inferred", "sectors": "inferred", "geometry": "inferred"}
    save(out / "result.json", result)
    print(f"{model} {case} {pass_name}: {result['status']}, {len(reading.marks) if reading else 0} marks, {len(history)} attempt(s)", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["gemini-3.5-flash-lite", "gemini-3.8-flash"])
    parser.add_argument("--cases", nargs="+", default=DEFAULT_CASES, help="scan:view pairs")
    parser.add_argument("--input-root", type=Path, default=ROOT / "Other/output/handwriting")
    parser.add_argument("--output", type=Path, help="New directory under ignored Other/output")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--resolution", choices=["low", "medium", "high"], default="high")
    parser.add_argument("--thinking", choices=["low", "medium", "high"], default="low")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--dry-run", action="store_true", help="Prepare inputs/requests without API calls")
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9._-]+", m) for m in args.models):
        parser.error("Invalid model ID")
    if any(not re.fullmatch(r"\d+:[a-z_]+", case) for case in args.cases):
        parser.error("Cases must use scan:view format")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_root = args.output or ROOT / "Other/output/gemini-probe" / stamp
    if not run_root.resolve().is_relative_to((ROOT / "Other/output").resolve()):
        parser.error("Outputs must stay under ignored Other/output")
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not args.dry_run and not key:
        parser.error("GEMINI_API_KEY is missing; use uv run --env-file .env python scripts/probe_gemini.py")
    jobs = [(case, model, pass_name) for case in args.cases for model in args.models for pass_name in ("A", "B")]
    if len(set(jobs)) != len(jobs):
        parser.error("Duplicate cases or models would overwrite attempt outputs")
    for case in args.cases:
        number, view = case.split(":")
        for filename in ("original.png", "modified.png", "mask.png"):
            if not (args.input_root / f"scan_{int(number):04}" / view / filename).is_file():
                parser.error(f"Missing prepared crop: {case}/{filename}")
    run_root.mkdir(parents=True, exist_ok=False)
    manifest = {"timestamp_utc": stamp, "models": args.models, "cases": args.cases, "planned_requests": len(jobs),
                "maximum_attempts_per_reading": 2, "resolution": args.resolution, "thinking": args.thinking, "dry_run": args.dry_run}
    save(run_root / "manifest.json", manifest)
    print(f"{len(jobs)} independent readings; maximum one retry each. Output: {run_root}", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(run_job, job, args, run_root, key): job for job in jobs}
        for future in as_completed(pending):
            job = pending[future]
            try:
                results.append(future.result())
            except Exception as error:
                results.append({"case": job[0], "model": job[1], "pass": job[2], "status": "failed", "error": str(error).replace(key, "[redacted]") if key else str(error)})
            save(run_root / "summary.json", results)
    failures = sum(result["status"] == "failed" for result in results)
    print(f"Finished {len(results)} readings; {failures} failed. {run_root / 'summary.json'}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
