"""Apply reviewed edits to fixed assignments, retaining source observations."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .candidates import build_candidates


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: str | None = None
    mark: str | None = None
    lesion: str | None = None
    property: str | None = None
    issue: str | None = None
    group: str | None = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    kind: Literal["assign_mark", "reject_membership", "reject_group", "set_value", "resolve_issue"]
    target: Target
    value: Any = None
    reviewer: str = Field(min_length=1)
    timestamp: datetime
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def required_target(self):
        target = self.target
        if self.timestamp.tzinfo is None:
            raise ValueError("decision timestamp needs a timezone")
        if self.kind in {"assign_mark", "reject_membership"} and not (target.focus and target.mark):
            raise ValueError("mark decisions require target.focus and target.mark")
        if self.kind == "reject_group" and not target.group:
            raise ValueError("reject_group requires target.group")
        if self.kind == "set_value" and not (target.lesion and target.property and isinstance(self.value, dict)):
            raise ValueError("set_value requires lesion, property and a typed value/status object")
        if self.kind == "resolve_issue" and not target.issue:
            raise ValueError("resolve_issue requires target.issue")
        return self


class Decisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["decisions-1"] = "decisions-1"
    decisions: list[Decision]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [item.id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("decision IDs must be unique")
        return self


def load_decisions(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    return Decisions.model_validate_json(path.read_bytes()).model_dump(mode="json")["decisions"]


def bind_property_targets(decisions: list[dict], current: dict, previous: dict | None, *,
                          history: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Replay lesion edits by source identity even when a fresh attempt renumbers lesions."""
    old = {lesion["id"]: lesion for lesion in (previous or current)["lesions"]}
    prior_decisions = {decision["id"]: decision for decision in
                       ((previous or {}).get("decisions_history") or (previous or {}).get("decisions_applied", []))}
    current_by_focus = {lesion.get("focus") or lesion.get("source_subject"): lesion for lesion in current["lesions"]}
    result, issues = [], []
    for original in decisions:
        decision = deepcopy(original)
        if decision["kind"] == "set_value":
            target = decision["target"]
            earlier = prior_decisions.get(decision["id"], {}).get("target", {})
            old_lesion = old.get(target["lesion"], {})
            focus = (target.get("focus") or earlier.get("focus") or old_lesion.get("focus")
                     or target.get("mark") or earlier.get("mark") or old_lesion.get("source_identity") or old_lesion.get("source_subject"))
            if focus:
                target["focus" if (target.get("focus") or earlier.get("focus") or old_lesion.get("focus")) else "mark"] = focus
            lesion = current_by_focus.get(focus)
            if not lesion:
                if history is not None:
                    history.append(decision)
                issues.append({"kind": "other", "severity": "info", "context": [decision["id"]],
                               "reason": "Decision lesion source identity no longer exists."})
                continue
            target.update(lesion=lesion["id"])
            target["focus" if lesion.get("focus") else "mark"] = focus
        if history is not None:
            history.append(deepcopy(decision))
        result.append(decision)
    return result, issues


def prepare_assignments(report: dict, drawing: dict, candidates: list[dict], previous: dict,
                        decisions: list[dict]) -> tuple[list[dict], dict, set[str], list[dict], list[dict]]:
    """Keep previous marks fixed. Split a candidate only when a review changes its members."""
    marks = {mark["id"] for mark in drawing["marks"]}
    foci = {subject["id"] for subject in report["extraction"]["subjects"] if subject["kind"] == "tumour_focus"}
    candidates = deepcopy(candidates)
    old_candidates = {candidate["id"]: candidate for candidate in previous.get("candidates", [])}
    ownership = {focus: set() for focus in foci}
    for hypothesis in previous["matching"].get("hypotheses", []):
        if hypothesis["focus"] in foci:
            ownership[hypothesis["focus"]].update(
                member["subject"] for member in hypothesis.get("memberships", [])
                if member["subject"] in marks)
    touched, issues, applied = set(), [], []
    direct_choices = {mark: candidate["source"].removeprefix("decision:")
                      for candidate in old_candidates.values() if candidate["source"].startswith("decision:")
                      for mark in candidate["marks"]}
    groups = {group["id"] for group in drawing["groups"]}
    for decision in decisions:
        target, kind = decision["target"], decision["kind"]
        missing = ((target.get("focus") and target["focus"] not in foci)
                   or (target.get("mark") and target["mark"] not in marks)
                   or (target.get("group") and target["group"].removeprefix("group:") not in groups))
        # Property/issue targets are checked after interpretations have been recomputed.
        if missing:
            issues.append({"kind": "other", "severity": "info", "context": [decision["id"]],
                           "reason": "Decision target no longer exists in the pinned inputs.", "raised_by": ["rules"]})
            continue
        if kind == "assign_mark":
            for focus, members in ownership.items():
                if target["mark"] in members:
                    members.remove(target["mark"])
                    touched.add(focus)
            ownership[target["focus"]].add(target["mark"])
            direct_choices[target["mark"]] = decision["id"]
            touched.update({target["focus"], target["mark"]})
        elif kind == "reject_membership":
            ownership[target["focus"]].discard(target["mark"])
            touched.update({target["focus"], target["mark"]})
        elif kind == "reject_group":
            group = "group:" + target["group"].removeprefix("group:")
            dependent = {mark for candidate in old_candidates.values()
                         if group in candidate.get("depends_on", []) or candidate.get("source") == group
                         for mark in candidate["marks"]}
            dependent.difference_update(direct_choices)
            for focus, members in ownership.items():
                affected = members & dependent
                if affected:
                    members.difference_update(affected)
                    touched.update({focus, *affected})
                    issues.append({"kind": "other", "severity": "question", "context": [focus, group, *sorted(affected)],
                                   "reason": "Rejected drawing group invalidates these memberships; reassessment is required."})
        if kind in {"assign_mark", "reject_membership", "reject_group"}:
            applied.append(decision)

    represented = {mark for candidate in candidates for mark in candidate["marks"]}
    for mark in sorted(set().union(*ownership.values()) - represented) if ownership else []:
        fragment = deepcopy(drawing)
        fragment.update(groups=[], standalone=[{"mark": mark}], not_lesion=[])
        item = build_candidates(fragment)[0]
        item["id"] = "review:" + mark
        candidates.append(item)

    # Partition candidates along reviewed ownership while keeping their original provenance.
    replacement, assignments = [], {focus: [] for focus in foci}
    for candidate in candidates:
        remainder = set(candidate["marks"])
        parts = []
        for focus, owned in ownership.items():
            subset = remainder & owned
            if subset:
                direct = subset & direct_choices.keys()
                parts.extend((focus, {mark}) for mark in sorted(direct))
                if subset - direct:
                    parts.append((focus, subset - direct))
                remainder -= subset
        if remainder:
            parts.append((None, remainder))
        for focus, subset in parts:
            if subset == set(candidate["marks"]):
                item = candidate
            else:
                fragment = deepcopy(drawing)
                fragment["groups"] = [{"id": "review-fragment", "members": sorted(subset)}]
                fragment["standalone"] = []
                fragment["not_lesion"] = []
                item = build_candidates(fragment)[0]
                suffix = hashlib.sha256(json.dumps(sorted(subset)).encode()).hexdigest()[:8]
                item.update(id=candidate["id"] + "~" + suffix, source=candidate["source"],
                            depends_on=candidate.get("depends_on", []), standalone=candidate.get("standalone", False))
            selected_mark = next(iter(subset)) if len(subset) == 1 else None
            if selected_mark in direct_choices:
                item = deepcopy(item)
                item.update(id="review:" + selected_mark, source="decision:" + direct_choices[selected_mark],
                            depends_on=["decision:" + direct_choices[selected_mark]],
                            source_history={"candidate": candidate["id"], "source": candidate["source"],
                                            "depends_on": candidate.get("depends_on", [])})
            replacement.append(item)
            if focus:
                assignments[focus].append(item["id"])
    return replacement, assignments, touched, issues, applied


def reviewed_report(report: dict, interpretation: dict, decisions: list[dict]) -> dict:
    """An internal computation view, never written back as a source extraction."""
    result = deepcopy(report)
    lesions = {lesion["id"]: lesion for lesion in interpretation["lesions"]}
    for decision in decisions:
        if decision["kind"] != "set_value":
            continue
        target = decision["target"]
        lesion = lesions.get(target["lesion"])
        if not lesion:
            continue
        for obs in result["extraction"]["observations"]:
            if obs["subject_id"] == lesion.get("focus") and obs["property"] == target["property"]:
                status, value = validate_override(target["property"], decision["value"])
                obs.update(status=status, value=value, basis="inferred", certainty={"extraction": "unassessed", "interpretation": "unassessed",
                                                                "explanation": decision["reason"]})
                obs["review_decision"] = decision["id"]
    return result


def validate_override(prop: str, override: dict) -> tuple[str, dict | None]:
    from .inputs import CODE_DOMAINS
    from report_extractor.models import ObservationProperty, ObservationValue, PROPERTY_VALUE_TYPES
    from pydantic import TypeAdapter

    status, value = override.get("status", "recorded"), override.get("value")
    if status == "recorded":
        value = TypeAdapter(ObservationValue).validate_python(value).model_dump(mode="json")
        if value["type"] not in PROPERTY_VALUE_TYPES[ObservationProperty(prop)]:
            raise ValueError("reviewed value type does not match the property")
        if prop in CODE_DOMAINS and value["code"] not in CODE_DOMAINS[prop]:
            raise ValueError(f"invalid {prop} code")
        components = {"laterality": "laterality", "level": "levels", "zone": "zones",
                      "anteroposterior": "anteroposterior", "textual_location": "description"}
        if prop in components:
            component = components[prop]
            if not value.get(component) or any(value.get(key) for key in components.values() if key != component):
                raise ValueError("a reviewed location must set only the component named by its property")
    elif status not in {"not reported", "unreadable", "not assessed", "not applicable"} or value is not None:
        raise ValueError("unavailable reviewer values need a schema status and no value")
    return status, value


def apply_interpretation_decisions(result: dict, decisions: list[dict], *,
                                   source_interpretation: dict | None = None) -> tuple[dict, set[str], list[dict]]:
    """Retain reviewer overrides separately from source-derived assessments."""
    result = deepcopy(result)
    lesions = {item["id"]: item for item in result["lesions"]}
    sources = {item["id"]: item for item in (source_interpretation or result)["lesions"]}
    touched, applied = set(), []
    for decision in decisions:
        target = decision["target"]
        if decision["kind"] == "set_value":
            lesion = lesions.get(target["lesion"])
            if lesion and target["property"] == "sectors":
                from .candidates import crosswalk_rows
                codes = {row["redcap_code"] for row in crosswalk_rows()}
                selected = decision["value"].get("value", {})
                if (decision["value"].get("status", "recorded") != "recorded"
                        or set(selected) != {"type", "in", "maybe"} or selected.get("type") != "sectors"
                        or not isinstance(selected["in"], list) or not isinstance(selected["maybe"], list)
                        or any(not isinstance(code, str) or code not in codes for code in selected["in"] + selected["maybe"])):
                    raise ValueError("sector override requires known REDCap codes in a typed in/maybe set")
                prior = sources[lesion["id"]]["sectors"]
                lesion["sectors"] = {"in": sorted(set(selected["in"])), "maybe": sorted(set(selected["maybe"]) - set(selected["in"])),
                                     "status": "recorded", "basis": "inferred", "disposition": "adopted",
                                     "tags": ["reviewer selection"], "rationale": decision["reason"],
                                     "review_status": "accepted", "supports": ["decision:" + decision["id"]], "opposes": [],
                                     "source_assessment": deepcopy(prior), "decision": decision["id"],
                                     "confidence": {"rules": "unassessed", "final": "unassessed", "explanations": [decision["reason"]]}}
                touched.update({lesion["id"], lesion.get("focus", "")})
                applied.append(decision)
                continue
            prop = next((p for p in lesion.get("properties", []) if p["property"] == target["property"]), None) if lesion else None
            if prop is None:
                result["issues"].append({"kind": "other", "severity": "info", "context": [decision["id"]],
                                         "reason": "Decision property target no longer exists."})
                continue
            status, value = validate_override(target["property"], decision["value"])
            source_prop = next((p for p in sources[lesion["id"]]["properties"] if p["property"] == target["property"]), prop)
            prop["source_assessment"] = deepcopy(source_prop)
            for field in ("unavailable_reason", "source_certainty", "evidence_ids", "derived_from", "source_inputs"):
                prop.pop(field, None)
            prop.update(status=status, value=value, basis="inferred", tags=["reviewer selection"],
                        disposition="adopted" if value else "not applicable" if status == "not applicable" else "unavailable",
                        review_status="accepted", decision=decision["id"], rationale=decision["reason"],
                        confidence={"rules": "unassessed", "final": "unassessed",
                                    "explanations": ["Reviewer selection; no new source evidence."]})
            prop["supports"] = ["decision:" + decision["id"]]
            if status != "recorded":
                prop["unavailable_reason"] = decision["reason"]
            touched.update({lesion["id"], lesion.get("focus", "")})
            applied.append(decision)
        elif decision["kind"] == "resolve_issue":
            issue = next((issue for issue in result["issues"] if issue.get("id") == target["issue"]), None)
            if issue is None:
                result["issues"].append({"kind": "other", "severity": "info", "context": [decision["id"]],
                                         "reason": "Decision issue target no longer exists."})
                continue
            issue.update(status="resolved", decision=decision)
            applied.append(decision)
    return result, touched, applied
