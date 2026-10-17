"""Orientation per view from side letters, then patient side and REDCap codes.

The report never sets orientation. Orientation is an observation on the view:
"patient right at x<0" or "patient right at x>0", where x is measured from the
view's symmetry axis (viewer right is positive).
"""

from __future__ import annotations

import numpy as np

from . import reference
from .models import (AvailabilityStatus, Basis, CertaintyLevel, Certainty, Mark, Observation, PatientSide, Signal,
                     THRESHOLDS, signal)

RIGHT_AT_NEGATIVE = "patient right at x<0"
RIGHT_AT_POSITIVE = "patient right at x>0"
DEDUPE_PX = 15
AXIAL_ORDER = list(reference.AXIAL_BLOCK)

# The printed "Seminal Vesicles" label ends near y 350 on the reference and the base outline starts near
# y 385 (read off pirads_v2.1_grayscale.png). A letter centred in this band, over the axial column, belongs to
# the whole axial block. x0 sits left of the SV crop (770) so a letter just outside it still counts.
SV_BASE_GAP = (700, 350, reference.WIDTH, 385)  # x0, y0, x1, y1 in reference px


def is_side_letter(mark: Mark) -> bool:
    return mark.kind == "side letter" and _letter(mark) is not None


def _letter(mark: Mark) -> str | None:
    text = (mark.text or "").strip().upper()
    return text if text in ("P", "R", "L") else None


def mark_centre(mark: Mark) -> tuple[float, float] | None:
    """Centre of the polygon's or box's bounding box, in reference px."""
    if mark.polygon_ref:
        points = np.asarray(mark.polygon_ref, float)
        return tuple((points.min(axis=0) + points.max(axis=0)) / 2)
    if mark.box_ref:
        x0, y0, x1, y1 = mark.box_ref
        return (x0 + x1) / 2, (y0 + y1) / 2
    return None


def _id_key(mark_id: str) -> tuple[str, int]:
    view, _, local = mark_id.rpartition(".")
    digits = "".join(ch for ch in local if ch.isdigit())
    return view, int(digits) if digits else 0


def _view_of(centre: tuple[float, float]) -> str | None:
    """The view whose crop plus margin holds the centre; the closest crop wins an overlap."""
    margin, x, y = THRESHOLDS["letter_margin_px"], *centre
    best = None
    for name, view in reference.VIEWS.items():
        vx, vy, w, h = view.bounds
        dx, dy = max(vx - x, 0, x - (vx + w)), max(vy - y, 0, y - (vy + h))
        if dx > margin or dy > margin:
            continue
        key = (dx + dy, np.hypot(x - (vx + w / 2), y - (vy + h / 2)))
        if best is None or key < best[0]:
            best = key, name
    return best[1] if best else None


def view_letters(marks: list[Mark]) -> dict[str, list[Mark]]:
    """Side letters per view. A letter in the SV/base gap is listed under every axial view."""
    found = []
    for mark in sorted((m for m in marks if is_side_letter(m)), key=lambda m: _id_key(m.id)):
        centre = mark_centre(mark)
        # SV and base crops overlap, so one physical letter can arrive as two marks. Same text within
        # DEDUPE_PX: keep the lower ID.
        if centre is None or any(_letter(k) == _letter(mark) and np.hypot(centre[0] - c[0], centre[1] - c[1]) <= DEDUPE_PX
                                 for k, c in found):
            continue
        found.append((mark, centre))
    per_view: dict[str, list[Mark]] = {name: [] for name in reference.VIEWS}
    for mark, (x, y) in found:
        x0, y0, x1, y1 = SV_BASE_GAP
        if x0 <= x <= x1 and y0 <= y <= y1:
            targets = reference.AXIAL_BLOCK
        else:
            view = _view_of((x, y))
            targets = (view,) if view else ()
        for name in targets:
            per_view[name].append(mark)
    return per_view


def _orientation_of(letter: Mark, view: str) -> str | None:
    """Patient right/left of the letter plus its side of the axis give the sign convention."""
    axis = reference.VIEWS[view].axis_x
    centre = mark_centre(letter)
    if axis is None or centre is None or centre[0] == axis:
        return None
    on_negative = centre[0] < axis
    right = _letter(letter) in ("P", "R")
    return RIGHT_AT_NEGATIVE if on_negative == right else RIGHT_AT_POSITIVE


def orient_views(marks: list[Mark]) -> tuple[dict[str, Observation], dict[str, list[str]], list[Signal]]:
    letters = view_letters(marks)
    ids = {name: [m.id for m in found] for name, found in letters.items()}
    signals: list[Signal] = []
    result: dict[str, Observation] = {}
    for name, view in reference.VIEWS.items():
        if view.axis_x is None or name == "urethra":
            result[name] = Observation(status=AvailabilityStatus.NOT_APPLICABLE, evidence=ids[name],
                                       certainty=Certainty(explanation="no left/right in this view"))
            if name == "sagittal" and ids[name]:
                signals.append(signal("letter_in_sagittal", ids[name],
                                      "side letter in the sagittal view; P may mean posterior"))
            continue
        values = {_orientation_of(m, name) for m in letters[name]} - {None}
        if len(values) > 1:
            result[name] = Observation(status=AvailabilityStatus.UNREADABLE, evidence=ids[name],
                                       certainty=Certainty(explanation="letters in this view disagree"))
            signals.append(signal("letter_conflict", [*ids[name], f"{name}.orientation"],
                                  f"letters {', '.join(ids[name])} give opposite orientations"))
        elif values:
            result[name] = Observation(status=AvailabilityStatus.RECORDED, value=values.pop(), basis=Basis.EXPLICIT,
                                       evidence=ids[name])
    for name in AXIAL_ORDER:
        if name in result:
            continue
        lettered = [n for n in AXIAL_ORDER if n in result and result[n].status == AvailabilityStatus.RECORDED]
        conflicted = [n for n in AXIAL_ORDER if n in result and result[n].status == AvailabilityStatus.UNREADABLE]
        if lettered:
            source = min(lettered, key=lambda n: abs(AXIAL_ORDER.index(n) - AXIAL_ORDER.index(name)))
            result[name] = Observation(
                status=AvailabilityStatus.RECORDED, value=result[source].value, basis=Basis.INFERRED,
                evidence=result[source].evidence, derived_from=[f"{source}.orientation"],
                certainty=Certainty(explanation=f"no letter in this view; taken from {source}"))
        elif conflicted:
            result[name] = Observation(status=AvailabilityStatus.UNREADABLE, derived_from=[f"{n}.orientation" for n in conflicted],
                                       certainty=Certainty(explanation="no letter in this view; letters elsewhere in the axial block conflict"))
        else:
            result[name] = _default(name, "no axial letters on the sheet; default patient right on viewer left")
    # Lettered axial views that disagree with each other are a sheet-level conflict. Spec is silent; raise it.
    values = {n: result[n].value for n in AXIAL_ORDER if result[n].basis == Basis.EXPLICIT}
    if len(set(values.values())) > 1:
        signals.append(signal("letter_conflict", [f"{n}.orientation" for n in values],
                              "lettered axial views give opposite orientations: " + ", ".join(f"{n} {v}" for n, v in values.items())))
    if "coronal" not in result:
        result["coronal"] = _default("coronal", "no letter in the coronal view; default patient right on viewer left",
                                     interpretation=CertaintyLevel.LOW)
    return {name: result[name] for name in reference.VIEWS}, ids, signals


def _default(view: str, why: str, interpretation: CertaintyLevel = CertaintyLevel.UNASSESSED) -> Observation:
    return Observation(status=AvailabilityStatus.RECORDED, value=RIGHT_AT_NEGATIVE, basis=Basis.INFERRED,
                       certainty=Certainty(interpretation=interpretation, explanation=why))


def patient_side(image_side: str, orientation: Observation | None) -> str | None:
    if image_side == "midline":
        return "midline"
    if orientation is None or orientation.status != AvailabilityStatus.RECORDED or image_side not in ("left", "right"):
        return None
    right_is_left_of_viewer = orientation.value == RIGHT_AT_NEGATIVE
    return "right" if (image_side == "left") == right_is_left_of_viewer else "left"


def apply_sides(marks: list[Mark], orientations: dict[str, Observation]) -> None:
    for mark in marks:
        orientation = orientations.get(mark.view)
        lists = (mark.sectors_polygon, mark.sectors_named, mark.sectors_cv)
        for sectors in lists:
            for sector in sectors:
                sector.patient_side = patient_side(sector.image_side, orientation)
                sector.redcap = reference.redcap_code(sector.zone, sector.level, sector.patient_side)
        if not any(lists):
            continue
        derived = [f"{mark.view}.orientation"]
        if orientation is not None and orientation.status == AvailabilityStatus.NOT_APPLICABLE:
            midline = any(s.image_side == "midline" for sectors in lists for s in sectors)
            value = "midline" if midline else "not applicable"
        elif orientation is None or orientation.status != AvailabilityStatus.RECORDED:
            value = "unknown"
        else:
            value = _mark_side(lists)
        mark.patient_side = PatientSide(value=value, basis=Basis.INFERRED, derived_from=derived)
        codes = {s.redcap for s in mark.sectors_polygon or mark.sectors_named if s.redcap}
        mark.redcap = sorted(codes)


def _mark_side(lists) -> str | None:
    for sectors in lists:  # polygon, then named, then CV
        sides = {s.patient_side for s in sectors} - {None}
        if not sides:
            continue
        lateral = sides - {"midline"}
        if lateral == {"left", "right"}:
            return "bilateral"
        return lateral.pop() if lateral else "midline"
    return "unknown"
