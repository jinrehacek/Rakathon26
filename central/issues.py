"""Review issues and filtering of drawing signals into issues or details."""
from __future__ import annotations

from copy import deepcopy

from .candidates import mark_index, sector_code
from .matching import dimensions_mm, observed
from .rules import SIZE_TOLERANCE_MM


def issue(kind: str, severity: str, context: list[str], explanation: str, **extra) -> dict:
    return {"kind": kind, "severity": severity, "raised_by": ["rules"],
            "context": list(dict.fromkeys(context)), "explanation": explanation,
            "alternatives": [], "status": "open", **extra}


def signal_touches(signal: dict, candidate: dict, marks: dict) -> bool:
    refs = signal.get("observations", [])
    dependencies = set(candidate.get("depends_on", [])) | {candidate["source"]}
    dependencies |= {dep.removeprefix("group:") for dep in dependencies}
    for ref in refs:
        if ref in dependencies or any(ref == mark or ref.startswith(mark + ".") for mark in candidate["marks"]):
            return True
        if any(ref in marks[mark].get("cv_regions", []) for mark in candidate["marks"]):
            return True
        if ref in candidate.get("sectors_in", []):
            return True
        # View-wide observations apply to every member in that panel.
        if any(ref == marks[mark]["view"] or ref.startswith(marks[mark]["view"] + ".orientation")
               for mark in candidate["marks"]):
            return True
    return False


def candidate_signals(drawing: dict, candidates: list[dict]) -> list[dict]:
    marks = mark_index(drawing)
    result = []
    for signal in drawing.get("signals", []):
        affected = [candidate for candidate in candidates if signal_touches(signal, candidate, marks)]
        if not affected:
            continue
        entry = deepcopy(signal)
        if entry["kind"] == "run_instability":
            affected_marks = [marks[mark] for candidate in affected for mark in candidate["marks"]
                              if any(ref == mark or ref in marks[mark].get("cv_regions", [])
                                     for ref in signal.get("observations", []))]
            if affected_marks and all(mark.get("runs_found") == 2 for mark in affected_marks):
                entry["suggestion"] = "info only"
        result.append(entry)
    return result


def filter_signals(drawing: dict, lesions: list[dict], candidates: list[dict], rows: list[dict]) -> tuple[list[dict], list[dict]]:
    marks = mark_index(drawing)
    candidate_map = {candidate["id"]: candidate for candidate in candidates}
    lesion_sectors = {code for lesion in lesions for code in lesion["sectors"]["in"]}
    active = [(lesion, candidate_map[cid]) for lesion in lesions
              for cid in lesion.get("candidates", [])]
    issues, details = [], []
    excluded = {item["mark"] for item in drawing.get("not_lesion", [])}
    for signal in drawing.get("signals", []):
        touched = [(lesion, candidate) for lesion, candidate in active if signal_touches(signal, candidate, marks)]
        refs = signal.get("observations", [])
        if refs and all(ref in excluded for ref in refs):
            details.append({"kind": "drawing_signal", "signal": deepcopy(signal),
                            "explanation": "Signal concerns a mark explicitly excluded as a lesion."})
            continue
        contact_codes = set(refs) & {row["redcap_code"] for row in rows}
        unknown_codes = set()
        for ref in refs:
            if ref in marks:
                for source in ("sectors_named", "sectors_polygon", "sectors_cv"):
                    unknown_codes.update(code for sector in marks[ref].get(source, [])
                                         if (code := sector_code(sector, rows)))
            for region in drawing.get("cv_regions", []):
                if ref == region["id"]:
                    unknown_codes.update(code for sector in region.get("sectors", [])
                                         if (code := sector_code(sector, rows)))
        unknown_codes.update(contact_codes)
        missed_ink = signal["kind"] == "unknown_ink" and bool(unknown_codes - lesion_sectors)
        if not touched and not unknown_codes.intersection(lesion_sectors) and not missed_ink:
            details.append({"kind": "drawing_signal", "signal": deepcopy(signal),
                            "explanation": "Signal does not affect a lesion mark or selected lesion sector."})
            continue
        severity = "question" if signal.get("suggestion") == "would flag" else "info"
        if missed_ink:
            severity = "question"
        elif signal["kind"] == "run_instability" and touched and all(
                lesion.get("side_agrees") and lesion.get("level_agrees") for lesion, _ in touched):
            severity = "info"
        issues.append(issue(signal["kind"], severity,
                            [lesion["id"] for lesion, _ in touched] + refs,
                            signal["reason"], signal=deepcopy(signal)))
    return issues, details


def size_note_issues(report: dict, drawing: dict, lesions: list[dict],
                     details: list[dict] | None = None) -> list[dict]:
    """Read only dimensions explicitly carrying mm/cm; never turn notes into values."""
    import re

    found = []
    for note in drawing["marks"]:
        link = note.get("linked_to")
        if not link or not note.get("text"):
            continue
        target = link["mark"]
        for lesion in lesions:
            if target not in lesion.get("marks", []) or not lesion.get("focus"):
                continue
            obs = observed(report, lesion["focus"], "dimensions")
            dimensions = dimensions_mm(obs)
            if not dimensions:
                continue
            # A unit at the end applies to each number in an explicit dimension chain.
            notes = []
            for match in re.finditer(r"(?<![\w.,])((?:\d+(?:[.,]\d+)?\s*[x×*]\s*)*\d+(?:[.,]\d+)?)\s*(mm|cm)\b", note["text"], re.I):
                factor = 10 if match.group(2).lower() == "cm" else 1
                notes.extend(float(number.replace(",", ".")) * factor
                             for number in re.findall(r"\d+(?:[.,]\d+)?", match.group(1)))
            if not notes and details is not None:
                details.append({"kind": "size_note_comparison", "status": "not assessed",
                                "certainty": "unassessed", "context": [lesion["id"], note["id"]],
                                "explanation": "The linked note has no explicit supported physical unit; no default unit is defined."})
            if notes and any(all(abs(number - dimension) > SIZE_TOLERANCE_MM for dimension in dimensions)
                             for number in notes):
                found.append(issue("size_note_conflict", "info",
                                   [lesion["id"], note["id"], target, "report:" + obs["id"]],
                                   "A linked handwritten size differs from every report dimension by more than 2 mm.",
                                   note_mm=notes, report_dimensions_mm=dimensions))
    return found


def number_issues(issues: list[dict]) -> list[dict]:
    for number, entry in enumerate(issues, 1):
        entry["id"] = f"i{number}"
    return issues
