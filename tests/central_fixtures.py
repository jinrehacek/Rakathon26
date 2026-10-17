"""Synthetic complete contracts for exercising the public case pipeline."""

import hashlib
import json
from pathlib import Path


FOCUS_PROPERTIES = ("reported_label", "dominant", "laterality", "level", "zone", "anteroposterior",
                    "textual_location", "dimensions", "gleason_patterns", "gleason_score", "grade_group",
                    "extraprostatic_extension", "perineural_invasion", "histology_type")
SPECIMEN_PROPERTIES = ("classification_pt", "classification_pn", "classification_pm", "classification_r",
                       "classification_l", "classification_v", "grade_group", "reported_lesion_count",
                       "multifocality", "histology", "icd_o", "seminal_vesicle_invasion")


def write_case(root: Path, case="synthetic-case") -> tuple[Path, Path]:
    from report_extractor.models import OFFSET_CONVENTION

    text = "Syntetický vzorek. Ložisko A vpravo uprostřed PZ. Ložisko B vlevo v apexu TZ."
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    source_hash = hashlib.sha256(b"synthetic report scan").hexdigest()
    source_path = str(root / "Other/preprocessed" / case / "report.jpg")
    evidence = {"id": "e1", "text_layer_id": "text-1", "page": 1, "quotation": text,
                "start_offset": 0, "end_offset": len(text), "offset_convention": OFFSET_CONVENTION}
    subjects = [{"id": ident, "kind": kind, "label": ident, "identification_basis": "explicit",
                 "parent_id": None if kind == "specimen" else "specimen", "evidence_ids": ["e1"]}
                for ident, kind in (("specimen", "specimen"), ("f1", "tumour_focus"), ("f2", "tumour_focus"))]
    observations, coverage = [], []
    values = {
        ("f1", "laterality"): {"type": "location", "laterality": "right", "original_wording": "vpravo"},
        ("f1", "level"): {"type": "location", "levels": ["mid"], "original_wording": "uprostřed"},
        ("f1", "zone"): {"type": "location", "zones": ["pz"], "original_wording": "PZ"},
        ("f2", "laterality"): {"type": "location", "laterality": "left", "original_wording": "vlevo"},
        ("f2", "level"): {"type": "location", "levels": ["apex"], "original_wording": "v apexu"},
        ("f2", "zone"): {"type": "location", "zones": ["tz"], "original_wording": "TZ"},
    }
    for subject in subjects:
        props = SPECIMEN_PROPERTIES if subject["kind"] == "specimen" else FOCUS_PROPERTIES
        for prop in props:
            ident = subject["id"] + "-" + prop
            value = values.get((subject["id"], prop))
            obs = {"id": ident, "subject_id": subject["id"], "property": prop,
                   "status": "recorded" if value else "not reported", "basis": "explicit",
                   "evidence_ids": ["e1"] if value else [], "derived_from": [], "review_status": "unreviewed",
                   "certainty": {"extraction": "high", "interpretation": "high", "explanation": "Synthetic explicit value."}}
            if value:
                obs["value"] = value
            else:
                obs["unavailable_reason"] = "Synthetic report checked; this property is not stated."
            observations.append(obs)
            coverage.append({"id": "cov-" + ident, "subject_id": subject["id"], "property": prop,
                             "checked": True, "source_complete": True, "rationale": "Whole synthetic text checked."})
    report = {
        "document": {"id": "doc-1", "kind": "text_report", "language": "cs", "source_path": source_path, "source_sha256": source_hash},
        "text_layer": {"id": "text-1", "source_path": source_path, "source_sha256": source_hash,
                       "text_sha256": text_hash, "input_kind": "text", "extraction_method": "plain_text",
                       "tool": "synthetic-fixture", "tool_version": "1", "language": "cs", "page": 1, "text": text, "words": []},
        "extraction": {"id": "extract-1", "document_id": "doc-1", "source_text_layer_id": "text-1",
                       "created_at": "2026-10-17T12:00:00Z", "extractor_version": "synthetic/1",
                       "schema_version": "1.0.0", "prompt_version": "synthetic-1", "output_contract_version": "report-2",
                       "mode": "manual", "complete": True, "evidence": [evidence], "subjects": subjects,
                       "coverage": coverage, "observations": observations, "issues": []},
        "quarantine": [], "validation_errors": [],
    }
    sectors = [
        {"zone": "pzpl", "level": "mid", "image_side": "left", "patient_side": "right", "redcap": "pzpl_mid_rs"},
        {"zone": "pzpl", "level": "base", "image_side": "left", "patient_side": "right", "redcap": "pzpl_base_rs"},
        {"zone": "tza", "level": "apex", "image_side": "right", "patient_side": "left", "redcap": "tza_apex_ls"},
    ]
    views = [{"id": name, "kind": "diagram view", "view_type": "axial", "level": name,
              "panel_region_ref": [0, 0, 100, 100], "coordinate_convention": {},
              "orientation": {"status": "recorded", "value": "patient right at x<0", "basis": "explicit",
                              "evidence": [name + ".letter"], "derived_from": [], "review_status": "unreviewed",
                              "certainty": {"extraction": "high", "interpretation": "high"}}, "letters": [name + ".letter"]}
             for name in ("mid", "base", "apex")]
    marks = [{"id": sector["level"] + ".m1", "view": sector["level"], "kind": "closed outline", "runs_found": 3,
              "run_local_ids": ["m1", "m1", "m1"], "polygon_ref": None, "closed": True, "box_ref": None,
              "basis": "inferred", "sectors_named_by_run": [[sector]] * 3, "sectors_named": [sector], "sectors_polygon": [{**sector, "share": 0.8, "px": 80}],
              "sectors_cv": [], "cv_regions": [], "redcap": [sector["redcap"]], "review_status": "unreviewed"}
             for sector in sectors]
    letters = [{"id": name + ".letter", "view": name, "kind": "side letter", "runs_found": 3,
                "text": "P", "basis": "explicit"} for name in ("mid", "base", "apex")]
    marks.extend(letters)
    drawing = {"extraction": {"case_id": case, "source_path": str(root / "Other/preprocessed" / case / "drawing.jpg"),
                               "source_sha256": "b" * 64, "timestamp_utc": "2026-10-17T12:00:00Z", "git_sha": "c" * 40,
                               "schema_version": "drawing-1", "model": "synthetic", "prompt_sha256": {},
                               "thresholds": {}, "alignment": {}},
               "views": views, "marks": marks, "cv_regions": [],
               "groups": [{"id": "g1", "members": ["mid.m1", "base.m1"], "proposed_finding_kind": "tumour", "reason": "Synthetic grouping."}],
               "standalone": [{"mark": "apex.m1", "reason": "Single depiction."}],
               "not_lesion": [{"mark": mark["id"], "reason": "Orientation letter."} for mark in letters], "signals": []}
    paths = (root / "Other/output/report" / case / "report.json", root / "Other/output/drawing" / case / "drawing.json")
    for path, payload in zip(paths, (report, drawing)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return paths
