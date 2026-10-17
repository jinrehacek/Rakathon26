"""Grading sheets and the markdown template the grader fills in (spec, Testing)."""

from __future__ import annotations

import html
from pathlib import Path

import cv2 as cv
import numpy as np

from . import reference
from .grouping import draw_marks
from .models import BUBBLE_KINDS, DrawingOutput, Mark, Sector, Signal

GRADING_DIR = reference.ROOT / "Other/output/grading"
SOURCES = (("(a) named", "sectors_named"), ("(b) polygon", "sectors_polygon"), ("(c) cv", "sectors_cv"))
KIND_COLOUR = {"closed outline": (0, 160, 0), "bridged outline": (0, 160, 160), "shading": (200, 0, 200),
               "open stroke": (0, 0, 220)}


def _read(path: Path) -> np.ndarray:
    image = cv.imread(str(path), cv.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def save_overlay(case_out: Path, view: str, overlay: np.ndarray) -> None:
    folder = Path(case_out) / "cv"
    folder.mkdir(parents=True, exist_ok=True)
    cv.imwrite(str(folder / f"{view}_overlay.png"), overlay)


def load_overlays(case_out: Path, views: list[str]) -> dict[str, np.ndarray]:
    """CV overlays saved by the run. A missing one falls back to boxes from drawing.json, never a recompute."""
    found = {view: cv.imread(str(Path(case_out) / "cv" / f"{view}_overlay.png"), cv.IMREAD_COLOR) for view in views}
    return {view: image for view, image in found.items() if image is not None}


def _title(image: np.ndarray, text: str) -> np.ndarray:
    bar = np.full((24, image.shape[1], 3), 255, np.uint8)
    cv.putText(bar, text, (4, 17), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv.LINE_AA)
    return np.vstack([bar, image])


def _cv_panel(output: DrawingOutput, view: str, overlay: np.ndarray | None) -> np.ndarray:
    if overlay is not None:
        return overlay
    v = reference.VIEWS[view]
    x, y, w, h = v.bounds
    panel = cv.imread(str(reference.SECTOR_MAP), cv.IMREAD_COLOR)[y:y + h, x:x + w].copy()
    for region in output.cv_regions:
        if region.view != view:
            continue
        x0, y0, x1, y1 = np.asarray(region.box_ref) - (x, y, x, y)
        colour = KIND_COLOUR[region.kind]
        cv.rectangle(panel, (int(x0), int(y0)), (int(x1), int(y1)), colour, 2)
        cv.putText(panel, region.id, (int(x0), max(int(y0) - 3, 10)), cv.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv.LINE_AA)
    return panel


def _sector_text(sectors: list[Sector]) -> str:
    return "; ".join(f"{s.zone} {s.level} {s.image_side}, patient {s.patient_side or '?'}"
                     + (f" {s.share:.0%}" if hasattr(s, "share") else "") for s in sectors) or "none"


def _signal_text(mark_id: str, signals: list[Signal]) -> str:
    return "; ".join(
        f"{s.kind} ({s.suggestion}): {s.reason}" for s in signals
        if any(observation == mark_id or observation.startswith(mark_id + ".") for observation in s.observations)
    ) or "none"


def make_sheets(case_out: Path, output: DrawingOutput, cv_overlays: dict[str, np.ndarray] | None = None) -> Path:
    """One PNG per view (three panels) and index.html with a sector table per bubble. Returns index.html."""
    out = Path(case_out) / "grading"
    out.mkdir(parents=True, exist_ok=True)
    sections = [f"<h1>Grading sheets: {html.escape(output.extraction.case_id)}</h1>"]
    for view in output.views:
        folder = Path(case_out) / "preprocess/views" / view.id
        original, cleaned = _read(folder / "original.png"), _read(folder / "cleaned.png")
        marks = [m for m in output.marks if m.view == view.id]
        origin = reference.VIEWS[view.id].origin
        panels = [_title(original, "1 original"), _title(draw_marks(cleaned, marks, origin), "2 cleaned + Gemini marks"),
                  _title(_cv_panel(output, view.id, (cv_overlays or {}).get(view.id)), "3 CV over sector map")]
        height = max(p.shape[0] for p in panels)
        panels = [cv.copyMakeBorder(p, 0, height - p.shape[0], 0, 6, cv.BORDER_CONSTANT, value=(255, 255, 255)) for p in panels]
        cv.imwrite(str(out / f"{view.id}.png"), np.hstack(panels))
        sections.append(_view_section(view.id, view.orientation, marks, output.signals))
    index = out / "index.html"
    index.write_text("<!doctype html><meta charset=utf-8><title>Grading sheets</title>"
                     "<style>body{font:14px sans-serif}img{max-width:100%}table{border-collapse:collapse;margin:8px 0}"
                     "td,th{border:1px solid #999;padding:2px 6px;text-align:left;vertical-align:top}</style>"
                     + "\n".join(sections), encoding="utf-8")
    return index


def _view_section(view: str, orientation, marks: list[Mark], signals: list[Signal]) -> str:
    e = html.escape
    lines = [f"<h2>{e(view)}</h2>",
             f"<p>Orientation: {e(orientation.value or orientation.status.value)} "
             f"({e(orientation.basis.value if orientation.basis else 'no basis')})</p>",
             f'<img src="{e(view)}.png" alt="{e(view)}">']
    bubbles = [m for m in marks if m.kind in BUBBLE_KINDS]
    if bubbles:
        lines.append("<table><tr><th>bubble</th><th>kind</th><th>(a) named</th><th>(b) polygon</th><th>(c) cv</th><th>signals</th></tr>")
        for m in bubbles:
            cells = [e(m.id), e(m.kind)] + [e(_sector_text(getattr(m, attr))) for _, attr in SOURCES] + [e(_signal_text(m.id, signals))]
            lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        lines.append("</table>")
    others = [m for m in marks if m.kind not in BUBBLE_KINDS]
    if others:
        lines.append("<table><tr><th>other mark</th><th>kind</th><th>text</th><th>signals</th></tr>")
        for m in others:
            lines.append("<tr>" + "".join(f"<td>{e(c)}</td>" for c in (m.id, m.kind, m.text or "", _signal_text(m.id, signals))) + "</tr>")
        lines.append("</table>")
    return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def grading_template(outputs: list[DrawingOutput], round_n: int) -> str:
    lines = [f"# Grading round {round_n}", "",
             "Edit this file and save it. Fill the empty verdict cells; leave a cell empty when you did not grade it.", "",
             "- Per bubble and per source (a), (b), (c): `ok`, `extra <sector>` or `missing <sector>`.",
             "- Per bubble, row `mark`: `wrong kind` or `not a mark`.",
             "- Per view: marks nobody found (IDs or a short description) and orientation `right` or `wrong`.",
             "- Per group: `right`, `split <marks>` or `merge with <group>`.", ""]
    for output in outputs:
        lines += [f"## Case {output.extraction.case_id}", ""]
        for view in output.views:
            marks = [m for m in output.marks if m.view == view.id]
            lines += [f"### {view.id}", "", "| item | value | verdict |", "| --- | --- | --- |",
                      f"| marks nobody found | | |",
                      f"| orientation | {_cell(view.orientation.value or view.orientation.status.value)} | |", ""]
            bubbles = [m for m in marks if m.kind in BUBBLE_KINDS]
            if bubbles:
                lines += ["| bubble | source | sectors | verdict |", "| --- | --- | --- | --- |"]
                for m in bubbles:
                    lines += [f"| {m.id} | {label} | {_cell(_sector_text(getattr(m, attr)))} | |" for label, attr in SOURCES]
                    lines.append(f"| {m.id} | mark | {_cell(m.kind)} | |")
                lines.append("")
        lines += ["### groups", ""]
        if output.groups:
            lines += ["| group | members | proposed kind | verdict |", "| --- | --- | --- | --- |"]
            lines += [f"| {g.id} | {', '.join(g.members)} | {g.proposed_finding_kind} | |" for g in output.groups]
        else:
            lines.append("No groups.")
        lines.append("")
    return "\n".join(lines)


def write_template(outputs: list[DrawingOutput], round_n: int, root: Path = GRADING_DIR) -> Path:
    """Write round-<n>.md. An existing file holds grades, so never overwrite it."""
    path = Path(root) / f"round-{round_n}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(grading_template(outputs, round_n))
    return path
