"""Assemble drawing.json: apply signals to the observations they name, then write."""

from __future__ import annotations

from pathlib import Path

from . import reference
from .models import (CVRegion, DrawingOutput, Extraction, Group, Mark, MarkReason, Observation, ReviewStatus, Signal,
                     ViewOut)


def view_out(view_name: str, orientation: Observation, letters: list[str]) -> ViewOut:
    view = reference.VIEWS[view_name]
    return ViewOut(id=view_name, view_type=view.view_type, level=view.level, panel_region_ref=list(view.bounds),
                   coordinate_convention=reference.coordinate_convention(view_name), orientation=orientation,
                   letters=letters)


def _flag(target, text: str) -> None:
    """needs_review plus the reason in certainty.explanation."""
    target.review_status = ReviewStatus.NEEDS_REVIEW
    previous = target.certainty.explanation
    explanation = text if not previous else previous if text in previous else f"{previous}; {text}"
    target.certainty = target.certainty.model_copy(update={"explanation": explanation})


def build_output(extraction: Extraction, views: list[ViewOut], marks: list[Mark], cv_regions: list[CVRegion],
                 groups: list[Group], standalone: list[MarkReason], not_lesion: list[MarkReason],
                 signals: list[Signal]) -> DrawingOutput:
    views = [v.model_copy(deep=True) for v in views]
    marks = [m.model_copy(deep=True) for m in marks]
    groups = [g.model_copy(deep=True) for g in groups]
    targets = {m.id: m for m in marks} | {g.id: g for g in groups} | {v.id + ".orientation": v.orientation for v in views}
    mark_ids = {m.id for m in marks}
    for group in groups:
        if unknown := set(group.members) - mark_ids:
            raise ValueError(f"Group {group.id} has unknown marks {sorted(unknown)}")
    for item in [*standalone, *not_lesion]:
        if item.mark not in mark_ids:
            raise ValueError(f"Unknown mark {item.mark} in standalone or not_lesion")
    cv_ids = {r.id for r in cv_regions}
    for item in signals:
        for observation in item.observations:
            target = targets.get(observation) or targets.get(observation.rpartition(".")[0])  # "base.m2.sectors"
            if target is not None:
                _flag(target, f"{item.kind}: {item.reason}")
            elif observation not in cv_ids:
                raise ValueError(f"Signal {item.kind} names unknown observation {observation!r}")
    return DrawingOutput(extraction=extraction, views=views, marks=marks, cv_regions=cv_regions, groups=groups,
                         standalone=standalone, not_lesion=not_lesion, signals=signals)


def write(output: DrawingOutput, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load(path: Path) -> DrawingOutput:
    return DrawingOutput.model_validate_json(Path(path).read_text(encoding="utf-8"))
