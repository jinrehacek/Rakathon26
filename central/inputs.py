"""Validate immutable report-3 and frozen drawing-1 input bundles."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from report_extractor.models import (
    StrictModel, TextLayer, Evidence, Subject, Observation, CoverageCheck,
    ExtractionIssue, SCHEMA_VERSION,
)
from .drawing_contract import DrawingOutput

from report_extractor.contract import (
    FOCUS_PROPERTIES, SPECIMEN_PROPERTIES, OTHER_PROPERTIES, REQUIRED_PROPERTIES,
    ALLOWED_PROPERTIES, LOCATION_COMPONENTS, CODE_DOMAINS, validate_content,
)


class Document(StrictModel):
    id: str = Field(min_length=1)
    kind: Literal["text_report"]
    language: str
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportExtraction(StrictModel):
    id: str = Field(min_length=1)
    document_id: str
    source_text_layer_id: str
    created_at: datetime
    extractor_version: str
    schema_version: Literal[SCHEMA_VERSION]
    prompt_version: str
    output_contract_version: Literal["report-3"]
    mode: str
    model_id: str | None = None
    call_settings: dict = Field(default_factory=dict)
    complete: Literal[True]
    evidence: tuple[Evidence, ...]
    subjects: tuple[Subject, ...]
    coverage: tuple[CoverageCheck, ...]
    observations: tuple[Observation, ...]
    issues: tuple[ExtractionIssue, ...]


class ReportBundle(StrictModel):
    document: Document
    text_layer: TextLayer
    extraction: ReportExtraction
    quarantine: tuple[()]
    validation_errors: tuple[()]


def sha256_file(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path):
    def invalid_constant(value):
        raise ValueError(f"non-finite JSON number: {value}")
    payload = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                         parse_constant=invalid_constant)
    # Reject unpaired surrogates throughout, including metadata and reasons.
    json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return payload


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _index(items, label):
    result = {}
    for item in items:
        _require(item.id and item.id not in result, f"empty or duplicate {label} ID: {item.id}")
        result[item.id] = item
    return result


def _refs(refs, index, label):
    _require(len(refs) == len(set(refs)), f"duplicate {label} reference")
    _require(all(ref in index for ref in refs), f"missing {label} reference")


def _acyclic(graph, label):
    done, active = set(), set()
    def visit(node):
        _require(node not in active, f"{label} cycle")
        if node in done:
            return
        active.add(node)
        for child in graph.get(node, ()):
            visit(child)
        active.remove(node)
        done.add(node)
    for node in graph:
        visit(node)


def load_report(path: str | Path) -> dict:
    raw = _load(path)
    _require(raw.get("extraction", {}).get("complete") is True, "report extraction must be complete=true")
    bundle = ReportBundle.model_validate_json(json.dumps(raw), strict=True)
    doc, layer, extraction = bundle.document, bundle.text_layer, bundle.extraction
    _require(extraction.document_id == doc.id and extraction.source_text_layer_id == layer.id,
             "report document/text layer reference identity mismatch")
    _require(doc.source_sha256 == layer.source_sha256 and doc.source_path == layer.source_path,
             "report source identity mismatch")
    _require(hashlib.sha256(layer.text.encode("utf-8")).hexdigest() == layer.text_sha256,
             "text layer hash mismatch")
    _require(bool(layer.text), "empty text layer")
    all_ids = [doc.id, layer.id, extraction.id] + [item.id for collection in
               (extraction.evidence, extraction.subjects, extraction.observations, extraction.coverage, extraction.issues) for item in collection]
    _require(len(all_ids) == len(set(all_ids)), "duplicate report ID across collections")
    validate_content(layer, extraction)
    return raw


def load_drawing(path: str | Path) -> dict:
    raw = _load(path)
    drawing = DrawingOutput.model_validate_json(json.dumps(raw), strict=True)
    _require(drawing.extraction.schema_version == "drawing-1", "expected drawing-1 schema version")
    _require(len(drawing.extraction.source_sha256) == 64 and all(c in "0123456789abcdef" for c in drawing.extraction.source_sha256), "invalid drawing source hash")
    views = _index(drawing.views, "view")
    marks = _index(drawing.marks, "mark")
    groups = _index(drawing.groups, "group")
    regions = _index(drawing.cv_regions, "CV region")
    ids = [*views, *marks, *groups, *regions]
    _require(len(ids) == len(set(ids)), "duplicate drawing ID across collections")
    with (Path(__file__).resolve().parents[1] / "Other/redcap/sector_crosswalk.csv").open() as stream:
        codes = {r["redcap_code"]: r for r in csv.DictReader(stream)}
    def sector_check(sector):
        _require(sector.zone in {"pza", "pzpl", "pzpm", "tza", "tzp", "cz", "as", "sv", "urethra", "prostate", "anterior", "posterior"}, "unknown sector zone")
        _require(sector.level in {"base", "mid", "apex", "urethra"}, "unknown sector level")
        if sector.redcap is not None:
            _require(sector.redcap in codes, "unknown sector code")
            row = codes[sector.redcap]
            if sector.redcap == "urethra":
                # The registry has one unsided choice spanning the organ. Drawing-1
                # names its separate panel level 'urethra' and its side 'midline'.
                _require(sector.zone == "urethra" and sector.level == "urethra"
                         and sector.patient_side in {None, "midline", "not applicable"}, "invalid urethra sector")
            else:
                _require(sector.zone == row["zone"] and sector.level == row["level"], "sector code anatomy mismatch")
                _require(sector.patient_side == row["patient_side"], "sector code side mismatch")
        if hasattr(sector, "share"):
            _require(math.isfinite(sector.share) and 0 <= sector.share <= 1 and sector.px >= 0, "invalid sector share or pixels")
    def reference(ref):
        return ref in ids or any(ref.startswith(ident + ".") for ident in ids)
    partition = []
    for group in groups.values():
        _refs(group.members, marks, "group mark")
        partition.extend(group.members)
    for entry in [*drawing.standalone, *drawing.not_lesion]:
        _require(entry.mark in marks, "partition references missing mark")
        partition.append(entry.mark)
    _require(len(partition) == len(set(partition)) and set(partition) == set(marks), "marks must partition exactly into groups, standalone and not_lesion")
    for view in views.values():
        _refs(view.letters, marks, "view letter")
        _require(all(marks[ref].kind == "side letter" for ref in view.letters), "view letter reference is not a side letter")
        orientation = view.orientation
        for refs in (orientation.evidence, orientation.derived_from):
            _require(len(refs) == len(set(refs)) and all(reference(ref) for ref in refs), "invalid orientation reference")
        if orientation.status == "recorded":
            _require(orientation.value in {"patient right at x<0", "patient right at x>0"}, "invalid orientation value")
            _require(orientation.basis is not None, "recorded orientation requires basis")
            if orientation.basis == "explicit":
                _require(bool(orientation.evidence), "explicit orientation requires evidence")
        else:
            _require(orientation.value is None, "unavailable orientation has a value")
    for mark in marks.values():
        _require(mark.view in views, "mark references missing view")
        _require(mark.runs_found >= 0, "negative run count")
        _refs(mark.cv_regions, regions, "mark CV region")
        if mark.linked_to:
            _require(mark.linked_to.mark in marks and mark.linked_to.mark != mark.id, "invalid linked mark")
        if mark.patient_side:
            _require(all(reference(r) for r in mark.patient_side.derived_from), "invalid patient side derivation")
        _require(all(code in codes for code in mark.redcap), "unknown mark sector code")
        for sectors in [mark.sectors_named, mark.sectors_polygon, mark.sectors_cv, *mark.sectors_named_by_run]:
            for sector in sectors:
                sector_check(sector)
    _acyclic({m.id: [m.linked_to.mark] if m.linked_to else [] for m in marks.values()}, "mark link")
    for region in regions.values():
        _require(region.view in views and region.px >= 0 and region.bridged_px >= 0, "invalid CV region")
        if region.paired_with:
            _require(region.paired_with in marks, "CV region references missing mark")
            _require(marks[region.paired_with].view == region.view, "CV region and paired mark belong to different views")
        for sector in region.sectors:
            sector_check(sector)
    for signal in drawing.signals:
        _require(all(reference(ref) for ref in signal.observations), "signal references missing drawing entity")
    return raw
