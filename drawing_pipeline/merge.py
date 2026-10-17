"""Merge the sampled Gemini runs of one view into marks with stable IDs."""

from __future__ import annotations

from collections import Counter

import numpy as np

from .geometry import crop_to_ref, grow, iou, raster
from .models import THRESHOLDS, Basis, Mark, RunMark, Signal, signal
from .reference import VIEWS


# Matching only. Two traces of one thin arc a few px apart overlap badly at the normal stroke width
# (IoU 0.44 at a 3 px offset with 6 px), so arcs match on a wider stroke (0.65 at 3 px, 0.56 at 4 px).
# Text and letters usually have no polygon and match on their box, grown so a 20 px letter box
# shifted 4 px diagonally still clears 0.5.
MATCH_STROKE_PX = 14
MATCH_BOX_GROW_PX = 6


def _raster(mark: RunMark, shape) -> np.ndarray:
    if mark.polygon_crop and len(mark.polygon_crop) >= 2:
        return raster(shape, mark.polygon_crop, mark.closed, stroke_px=MATCH_STROKE_PX)
    return grow(raster(shape, None, box=mark.box_crop), MATCH_BOX_GROW_PX)


def _suggestion(found: int, total: int) -> str:
    # The spec's rule for 3 runs: 2 of 3 is info only, 1 of 3 would flag. Generalised as majority vs not.
    return "info only" if found * 2 > total else "would flag"


def _text_key(text: str) -> str:
    return "".join(text.split()).casefold()  # "15mm" and "15 mm" are one reading


def _majority_text(kept: RunMark, members: list[RunMark]) -> str | None:
    """The reading most runs agree on, ignoring case and spaces. Ties go to the geometry winner."""
    texts = [m.text for m in members if m.text]
    if not texts:
        return None
    counts = Counter(map(_text_key, texts))
    best = max(counts.values())
    if kept.text and counts[_text_key(kept.text)] == best:
        return kept.text
    return next(t for t in texts if counts[_text_key(t)] == best)


def _top_left(mark: RunMark) -> tuple[float, float]:
    points = np.asarray(mark.polygon_crop if mark.polygon_crop else np.reshape(mark.box_crop, (2, 2)))
    return float(points[:, 1].min()), float(points[:, 0].min())


def _clusters(marks: list[RunMark], masks: list[np.ndarray]) -> list[list[int]]:
    """Greedy single link by descending IoU; a cluster holds at most one mark per run."""
    pairs = sorted(((iou(masks[i], masks[j]), i, j) for i in range(len(marks)) for j in range(i + 1, len(marks))
                    if marks[i].run != marks[j].run), reverse=True)
    cluster = {i: {i} for i in range(len(marks))}
    for value, i, j in pairs:
        if value < THRESHOLDS["merge_iou"]:
            break
        a, b = cluster[i], cluster[j]
        if a is b or {marks[k].run for k in a} & {marks[k].run for k in b}:
            continue
        a |= b
        for k in b:
            cluster[k] = a
    unique = {id(c): sorted(c) for c in cluster.values()}
    return list(unique.values())


def merge_runs(view: str, runs: list[list[RunMark] | None]) -> tuple[list[Mark], list[Signal]]:
    completed = [i for i, run in enumerate(runs) if run is not None]
    total = len(completed)
    # Index each mark by its position in `runs`, so run_local_ids line up whatever RunMark.run holds.
    marks = [m.model_copy(update={"run": i}) for i in completed for m in runs[i]]
    shape = VIEWS[view].shape
    masks = [_raster(m, shape) for m in marks]

    merged = []
    for members in _clusters(marks, masks):
        overlap = {k: sum(iou(masks[k], masks[o]) for o in members if o != k) for k in members}
        kept = marks[max(members, key=lambda k: overlap[k])]
        kinds = Counter(marks[k].kind for k in members)
        best = max(kinds.values())
        kind = kept.kind if kinds[kept.kind] == best else next(marks[k].kind for k in members
                                                               if kinds[marks[k].kind] == best)
        merged.append((kept, members, kind, _majority_text(kept, [marks[k] for k in members])))

    merged.sort(key=lambda item: _top_left(item[0]))
    result, signals = [], []
    for n, (kept, members, kind, text) in enumerate(merged, 1):
        mark_id = f"{view}.m{n}"
        by_run = {marks[k].run: marks[k] for k in members}
        found = sorted(by_run)
        named_by_run = [by_run[r].sectors for r in found]
        named = []
        for sectors in named_by_run:
            named += [s for s in sectors if s not in named]
        polygon = (np.round(crop_to_ref(kept.polygon_crop, view)).astype(int).tolist()
                   if kept.polygon_crop else None)
        box = (np.round(crop_to_ref(np.reshape(kept.box_crop, (2, 2)), view)).astype(int).ravel().tolist()
               if kept.box_crop else None)
        result.append(Mark(
            id=mark_id, view=view, kind=kind, runs_found=len(found),
            run_local_ids=[by_run[i].local_id if i in by_run else None for i in range(len(runs))],
            polygon_ref=polygon, closed=kept.closed, box_ref=box, text=text,
            basis=Basis.EXPLICIT if kind in ("text", "side letter") else Basis.INFERRED,
            sectors_named_by_run=named_by_run, sectors_named=named))
        if len(found) < total:
            signals.append(signal("run_instability", [mark_id], f"found in {len(found)} of {total} runs",
                                  _suggestion(len(found), total)))
        readings = [by_run[r].text for r in found if by_run[r].text]
        if len({_text_key(t) for t in readings}) > 1:
            agree = sum(_text_key(t) == _text_key(text) for t in readings)
            signals.append(signal("run_instability", [f"{mark_id}.text"],
                                  f"text read as {', '.join(repr(t) for t in readings)}; kept {text!r}",
                                  _suggestion(agree, len(found))))
        for sector in named:
            count = sum(sector in sectors for sectors in named_by_run)
            if count < len(found):
                signals.append(signal(
                    "run_instability", [f"{mark_id}.sectors_named"],
                    f"sector {sector.zone} {sector.level} {sector.image_side} named in {count} of "
                    f"{len(found)} runs that found the mark", _suggestion(count, len(found))))
    return result, signals
