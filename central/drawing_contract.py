"""Frozen drawing-1 contract copied from drawing worktree commit e5b5424.

No runtime dependency on drawing_pipeline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from report_extractor.models import AvailabilityStatus, Basis, Certainty, CertaintyLevel, ReviewStatus

__all__ = ["AvailabilityStatus", "Basis", "Certainty", "CertaintyLevel", "ReviewStatus"]

SCHEMA_VERSION = "drawing-1"
MarkKind = Literal["closed outline", "open arc", "small circle", "shading", "side letter", "text", "arrow", "other",
                   "unknown ink"]
BUBBLE_KINDS = frozenset({"closed outline", "open arc", "small circle", "shading"})
ImageSide = Literal["left", "right", "midline", "none"]
PatientSideValue = Literal["right", "left", "midline", "bilateral", "unknown", "not applicable"]

SignalKind = Literal["sources_disagree", "named_vs_polygon", "run_instability", "single_source", "unknown_ink",
                     "not_in_ink", "group_check_failed", "coronal_maybe_mirrored", "letter_conflict",
                     "letter_in_sagittal", "low_trust_note"]
Suggestion = Literal["would flag", "info only", "text is probably right"]
DEFAULT_SUGGESTION: dict[str, Suggestion] = {
    "sources_disagree": "would flag", "named_vs_polygon": "would flag", "run_instability": "would flag",
    "single_source": "info only", "unknown_ink": "would flag", "not_in_ink": "would flag",
    "group_check_failed": "would flag", "coronal_maybe_mirrored": "info only", "letter_conflict": "would flag",
    "letter_in_sagittal": "would flag", "low_trust_note": "text is probably right",
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sector(Model):
    """Zone + level + image side. Patient side and REDCap code are filled by the sides stage."""
    zone: str
    level: str
    image_side: ImageSide
    patient_side: PatientSideValue | None = None
    redcap: str | None = None


class SectorShare(Sector):
    px: int
    share: float


class Signal(Model):
    kind: SignalKind
    observations: list[str]          # mark, view or group IDs, optionally with a field: "base.m2", "base.orientation"
    reason: str
    suggestion: Suggestion


def signal(kind: SignalKind, observations: list[str], reason: str, suggestion: Suggestion | None = None) -> Signal:
    return Signal(kind=kind, observations=observations, reason=reason,
                  suggestion=suggestion or DEFAULT_SUGGESTION[kind])


class RunMark(Model):
    """One mark from one Gemini run, converted to crop px."""
    run: int
    local_id: str
    kind: MarkKind
    polygon_crop: list[list[float]] | None = None
    closed: bool = False
    box_crop: list[float] | None = None   # x0, y0, x1, y1
    text: str | None = None
    sectors: list[Sector] = []


class PatientSide(Model):
    value: PatientSideValue
    basis: Basis = Basis.INFERRED
    derived_from: list[str] = []


class Link(Model):
    mark: str
    basis: Basis = Basis.INFERRED


class Mark(Model):
    """A diagram mark subject. Never a lesion."""
    id: str                               # "<view>.m<n>", stable across re-runs of later stages
    view: str
    kind: MarkKind
    runs_found: int                       # 0 for CV-only unknown ink
    run_local_ids: list[str | None] = []  # the mark's local ID in each run, None where it was missing
    polygon_ref: list[list[int]] | None = None
    closed: bool = False
    box_ref: list[int] | None = None
    text: str | None = None
    basis: Basis = Basis.INFERRED         # explicit for transcribed text
    sectors_named_by_run: list[list[Sector]] = []
    sectors_named: list[Sector] = []      # source (a), union over runs
    sectors_polygon: list[SectorShare] = []  # source (b)
    sectors_cv: list[SectorShare] = []    # source (c), from paired CV regions
    cv_regions: list[str] = []
    ink_px_under_polygon: int | None = None
    patient_side: PatientSide | None = None
    redcap: list[str] = []
    linked_to: Link | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    certainty: Certainty = Certainty()


class CVRegion(Model):
    """One CV region or open stroke. Never shown to Gemini."""
    id: str                               # "<view>.cv<n>"
    view: str
    kind: Literal["closed outline", "bridged outline", "shading", "open stroke"]
    px: int
    box_ref: list[int]
    bridged_px: int = 0
    sectors: list[SectorShare] = []
    paired_with: str | None = None


class Observation(Model):
    status: AvailabilityStatus
    value: str | None = None
    basis: Basis | None = None
    evidence: list[str] = []
    derived_from: list[str] = []
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    certainty: Certainty = Certainty()


class ViewOut(Model):
    """A diagram view subject."""
    id: str
    kind: Literal["diagram view"] = "diagram view"
    view_type: str
    level: str
    panel_region_ref: list[int]           # x, y, width, height
    coordinate_convention: dict
    orientation: Observation              # value "patient right at x<0" | "patient right at x>0"; sagittal not applicable
    letters: list[str] = []               # side-letter mark IDs assigned to this view


class Group(Model):
    """A predicted lesion: a within-document matching hypothesis (MATCHING.md), two or more marks."""
    id: str
    members: list[str] = Field(min_length=2)
    proposed_finding_kind: Literal["tumour", "other", "unresolved"]
    reason: str
    bilateral: bool = False
    fixed: bool = False                   # kept unchanged from an earlier run at the app's request
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    matching_certainty: CertaintyLevel = CertaintyLevel.UNASSESSED
    certainty: Certainty = Certainty()   # carries the signal reasons in explanation


class MarkReason(Model):
    mark: str
    reason: str


class Extraction(Model):
    case_id: str
    source_path: str
    source_sha256: str
    timestamp_utc: str
    git_sha: str | None
    extractor_version: str = "drawing_pipeline"
    schema_version: str = SCHEMA_VERSION
    model: str
    prompt_sha256: dict[str, str]
    thresholds: dict
    alignment: dict
    runs_completed: dict[str, int] = {}   # per view
    notes: list[str] = []


class DrawingOutput(Model):
    extraction: Extraction
    views: list[ViewOut]
    marks: list[Mark]
    cv_regions: list[CVRegion]
    groups: list[Group]
    standalone: list[MarkReason]
    not_lesion: list[MarkReason]
    signals: list[Signal]
