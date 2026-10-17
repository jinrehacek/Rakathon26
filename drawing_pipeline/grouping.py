"""Group marks into predicted lesions: one Gemini call per case, then code checks.

The call never sees the report. Groups only point at marks; marks are never merged.
"""

from __future__ import annotations

import colorsys
import json
from pathlib import Path
from typing import Literal

import cv2 as cv
import httpx
import numpy as np

from . import llm, reference
from .models import (GEMINI_MODEL, THRESHOLDS, Group, Mark, MarkReason, Model, Observation, Signal, signal)

PROMPT = reference.ROOT / "prompts/gemini_grouping.md"
AXIAL_LEVELS = ("base", "mid", "apex")


class GroupOut(Model):
    id: str
    members: list[str]
    proposed_finding_kind: Literal["tumour", "other", "unresolved"]
    reason: str
    bilateral: bool


class GroupingResponse(Model):
    groups: list[GroupOut]
    standalone: list[MarkReason]
    not_lesion: list[MarkReason]


def prompt_sha256() -> str:
    return llm.sha256(PROMPT.read_bytes())


def draw_marks(image: np.ndarray, marks: list[Mark], origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Draw every mark's polygon or box with its ID, on a BGR image whose top-left is `origin` in reference px."""
    ox, oy = origin
    for index, mark in enumerate(marks):
        r, g, b = colorsys.hsv_to_rgb((index * 0.17) % 1, 0.9, 0.85)
        colour = (int(b * 255), int(g * 255), int(r * 255))
        if mark.polygon_ref:
            points = np.round(np.asarray(mark.polygon_ref) - (ox, oy)).astype(np.int32).reshape(-1, 1, 2)
            cv.polylines(image, [points], mark.closed, colour, 2)
            x, y = points[points[:, 0, 1].argmin(), 0]
        elif mark.box_ref:
            x0, y0, x1, y1 = np.asarray(mark.box_ref) - (ox, oy, ox, oy)
            cv.rectangle(image, (int(x0), int(y0)), (int(x1), int(y1)), colour, 2)
            x, y = x0, y0
        else:
            continue
        (w, h), base = cv.getTextSize(mark.id, cv.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        x, y = int(x), max(int(y), h + 4)
        cv.rectangle(image, (x, y - h - 4), (x + w + 2, y + base - 2), (255, 255, 255), cv.FILLED)
        cv.putText(image, mark.id, (x + 1, y - 3), cv.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv.LINE_AA)
    return image


def annotated_sheet(cleaned: np.ndarray, marks: list[Mark]) -> np.ndarray:
    image = cv.cvtColor(cleaned, cv.COLOR_GRAY2BGR) if cleaned.ndim == 2 else cleaned[:, :, :3].copy()
    return draw_marks(image, marks)


def _sectors(mark: Mark) -> list[dict]:
    """The best available source for the prompt: polygon, then named, then CV."""
    for sectors in (mark.sectors_polygon, mark.sectors_named, mark.sectors_cv):
        if sectors:
            return [{"zone": s.zone, "level": s.level, "image_side": s.image_side, "patient_side": s.patient_side,
                     **({"share": s.share} if hasattr(s, "share") else {})} for s in sectors]
    return []


def marks_json(marks: list[Mark], orientations: dict[str, Observation]) -> dict:
    rows = []
    for mark in marks:
        row = {"id": mark.id, "view": mark.view, "kind": mark.kind, "text": mark.text,
               "linked_to": mark.linked_to.mark if mark.linked_to else None, "sectors": _sectors(mark),
               "patient_side": mark.patient_side.value if mark.patient_side else None}
        rows.append({k: v for k, v in row.items() if v not in (None, [])})
    orientation = {view: (o.value or o.status.value) for view, o in orientations.items()}
    return {"orientation": orientation, "marks": rows}


def _marks_text(marks: list[Mark], orientations, fixed: list[Group]) -> str:
    payload = marks_json(marks, orientations)
    payload["fixed_groups"] = [{"id": g.id, "members": g.members, "bilateral": g.bilateral} for g in fixed]
    return "Marks JSON:\n" + json.dumps(payload, ensure_ascii=False)


def _replay(out: Path, marks: list[Mark], orientations, fixed: list[Group]) -> GroupingResponse | None:
    # Mark IDs such as base.u1 are renumbered when a threshold changes, so a saved answer is only valid
    # for the exact marks it was asked about.
    saved = json.loads((out / "request.json").read_text(encoding="utf-8"))
    sent = [p["text"] for p in saved["parts"] if p.get("text", "").startswith("Marks JSON:")]
    if sent != [_marks_text(marks, orientations, fixed)]:
        raise RuntimeError(f"Saved grouping request in {out} was for different marks; rerun without --replay")
    return llm.replay(out, GroupingResponse)


def _ask(case_out: Path, marks: list[Mark], orientations, fixed: list[Group], client: httpx.Client, key: str,
         model: str, out: Path) -> GroupingResponse | None:
    cleaned = cv.imread(str(case_out / "preprocess/cleaned.png"), cv.IMREAD_COLOR)
    if cleaned is None:
        raise FileNotFoundError(case_out / "preprocess/cleaned.png")
    out.mkdir(parents=True, exist_ok=True)
    annotated = annotated_sheet(cleaned, marks)
    cv.imwrite(str(out / "annotated.png"), annotated)
    parts = [{"text": PROMPT.read_text(encoding="utf-8")},
             {"text": "Original scan:"}, llm.image_part((case_out / "preprocess/aligned.png").read_bytes()),
             {"text": "Cleaned sheet with mark IDs:"}, llm.image_part(cv.imencode(".png", annotated)[1].tobytes()),
             {"text": _marks_text(marks, orientations, fixed)}]
    parsed, _ = llm.call(client, model, key, llm.request_body(parts, GroupingResponse), GroupingResponse, out)
    return parsed


def run_grouping(case_out: Path, marks: list[Mark], orientations: dict[str, Observation], *, client: httpx.Client,
                 key: str, model: str = GEMINI_MODEL, fixed_groups: list[Group] | None = None,
                 replay: bool = False) -> tuple[list[Group], list[MarkReason], list[MarkReason], list[Signal]]:
    case_out, out = Path(case_out), Path(case_out) / "grouping"
    fixed = [g.model_copy(update={"fixed": True}) for g in fixed_groups or []]
    known = {m.id for m in marks}
    for group in fixed:
        if unknown := set(group.members) - known:
            raise ValueError(f"Fixed group {group.id} has unknown marks {sorted(unknown)}")
    if not marks:
        return fixed, [], [], check_groups(fixed, marks)
    response = _replay(out, marks, orientations, fixed) if replay else _ask(case_out, marks, orientations, fixed, client, key, model, out)
    if response is None:
        raise RuntimeError(f"Grouping call produced no usable response; see {out}")
    groups, standalone, not_lesion = _clean(response, known, fixed)
    return groups, standalone, not_lesion, check_groups(groups, marks)


def _clean(response: GroupingResponse, known: set[str], fixed: list[Group]):
    """Drop unknown IDs and fixed members from model groups; send groups below two members to standalone."""
    kept = {m for g in fixed for m in g.members}
    taken = {g.id for g in fixed}
    groups, standalone = list(fixed), [r for r in response.standalone if r.mark in known and r.mark not in kept]
    not_lesion = [r for r in response.not_lesion if r.mark in known and r.mark not in kept]
    for item in response.groups:
        members = list(dict.fromkeys(m for m in item.members if m in known and m not in kept))
        if len(members) < 2:
            have = {r.mark for r in standalone}
            standalone += [MarkReason(mark=m, reason=f"group {item.id} left with fewer than two marks: {item.reason}")
                           for m in members if m not in have]
            continue
        group_id, n = item.id, len(taken)
        while group_id in taken:
            n += 1
            group_id = f"g{n}"
        taken.add(group_id)
        groups.append(Group(id=group_id, members=members, proposed_finding_kind=item.proposed_finding_kind,
                            reason=item.reason, bilateral=item.bilateral))
    return groups, standalone, not_lesion


def _sides(mark: Mark) -> set[str]:
    if mark.patient_side is None:
        return set()
    return {"left", "right"} if mark.patient_side.value == "bilateral" else (
        {mark.patient_side.value} & {"left", "right"})


def _bands(marks: list[Mark]) -> set[str]:
    """Level bands named by longitudinal members: named sectors, else polygon sectors above the share floor."""
    bands = set()
    for mark in marks:
        levels = [s.level for s in mark.sectors_named] or [
            s.level for s in mark.sectors_polygon if s.share >= THRESHOLDS["named_vs_polygon_share"]]
        bands |= set(levels) & set(AXIAL_LEVELS)
    return bands


def check_groups(groups: list[Group], marks: list[Mark]) -> list[Signal]:
    by_id = {m.id: m for m in marks}
    signals = []
    for group in groups:
        if unknown := [m for m in group.members if m not in by_id]:
            raise ValueError(f"Group {group.id} has unknown marks {unknown}")
        members = [by_id[m] for m in group.members]
        if not group.bilateral:
            others = [m for m in members if m.view != "coronal"]
            other_sides = set().union(*map(_sides, others)) if others else set()
            all_sides = other_sides.union(*map(_sides, members))
            if len(all_sides) > 1:
                if len(other_sides) == 1:
                    coronal = [m.id for m in members if m.view == "coronal"]
                    signals.append(signal("coronal_maybe_mirrored", [group.id, *coronal, "coronal.orientation"],
                                          f"group {group.id}: coronal marks {coronal} disagree in side with the other members"))
                else:
                    sides = {m.id: sorted(_sides(m)) for m in members if _sides(m)}
                    signals.append(signal("group_check_failed", [group.id],
                                          f"group {group.id} mixes patient sides without being bilateral: {sides}"))
        covered = {m.view for m in members} & set(AXIAL_LEVELS)
        coronal = [m for m in members if m.view == "coronal"]
        sagittal = [m for m in members if m.view == "sagittal"]
        if covered and coronal and sagittal:
            for name, longitudinal in (("coronal", coronal), ("sagittal", sagittal)):
                bands = _bands(longitudinal)
                if bands and bands != covered:
                    signals.append(signal("group_check_failed", [group.id],
                                          f"group {group.id}: axial levels {sorted(covered)} differ from the "
                                          f"{name} level bands {sorted(bands)}"))
    seen: dict[str, list[str]] = {}
    for group in groups:
        for mark_id in group.members:
            seen.setdefault(mark_id, []).append(group.id)
    for mark_id, ids in seen.items():
        if len(ids) > 1:
            signals.append(signal("group_check_failed", [*ids, mark_id],
                                  f"mark {mark_id} is in several groups: {', '.join(ids)}"))
    return signals
