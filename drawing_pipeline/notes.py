"""Handwritten notes: kept as marks, never mined into structured fields."""

from __future__ import annotations

import cv2 as cv
import numpy as np

from . import reference
from .geometry import raster, ref_to_crop
from .models import Basis, CertaintyLevel, Link, Mark, Signal, signal
from .orientation import is_side_letter


def _is_note(mark: Mark) -> bool:
    if is_side_letter(mark):
        return False
    return mark.kind == "text" or bool((mark.text or "").strip())


def _mask(mark: Mark) -> np.ndarray | None:
    """The mark rasterised in its view crop frame, or None when it has no geometry."""
    shape = reference.VIEWS[mark.view].shape
    box = ref_to_crop(np.reshape(mark.box_ref, (2, 2)), mark.view).ravel() if mark.box_ref else None
    polygon = ref_to_crop(mark.polygon_ref, mark.view) if mark.polygon_ref else None
    mask = raster(shape, polygon, mark.closed, box)
    return mask if mask.any() else None


def _distance(note: np.ndarray, other: np.ndarray) -> float:
    to_note = cv.distanceTransform((~note).astype(np.uint8), cv.DIST_L2, 3)
    return float(to_note[other].min())


def link_notes(marks: list[Mark]) -> list[Signal]:
    signals = []
    masks = {m.id: _mask(m) for m in marks}
    for note in filter(_is_note, marks):
        note.basis = Basis.EXPLICIT
        note.certainty = note.certainty.model_copy(update={"extraction": CertaintyLevel.LOW})
        candidates = [m for m in marks if m.view == note.view and m.id != note.id
                      and m.kind not in ("text", "side letter") and masks[m.id] is not None]
        if masks[note.id] is not None and candidates:
            nearest = min(candidates, key=lambda m: _distance(masks[note.id], masks[m.id]))
            note.linked_to = Link(mark=nearest.id, basis=Basis.INFERRED)
        signals.append(signal("low_trust_note", [note.id],
                              f"handwriting read by Gemini only: {note.text!r}"))
    return signals
