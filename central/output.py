"""Validate and append a run; publish latest only after its JSON is complete."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputPin(Model):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_id: str | None = None
    git_sha: str | None = None


class Inputs(Model):
    report: InputPin
    drawing: InputPin
    decisions: InputPin | None = None
    previous_run: str | None = None


class Pairing(Model):
    basis: Literal["supplied association"] = "supplied association"
    certainty: Literal["high"] = "high"
    assessment: Literal["supported"] = "supported"
    case_id: str
    documents: list[str]
    explanation: str
    review_status: Literal["unreviewed"] = "unreviewed"


class CombinedOutput(Model):
    schema_version: Literal["combined-1"] = "combined-1"
    rules_version: Literal["rules-1"] = "rules-1"
    created_at: str
    case_id: str
    inputs: Inputs
    pairing: Pairing
    candidates: list[dict[str, Any]]
    matching: dict[str, Any]
    lesions: list[dict[str, Any]]
    specimen: dict[str, Any]
    other_findings: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    details: list[dict[str, Any]]
    brains: dict[str, Any]
    decisions_applied: list[dict[str, Any]]
    decisions_history: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_identifiers(self):
        for name in ("candidates", "lesions", "issues"):
            ids = [item["id"] for item in getattr(self, name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {name} identifiers")
        candidate_ids = {candidate["id"] for candidate in self.candidates}
        hypotheses = {hypothesis["id"]: hypothesis for hypothesis in self.matching.get("hypotheses", [])}
        for hypothesis in self.matching.get("hypotheses", []):
            if set(hypothesis["candidates"]) - candidate_ids:
                raise ValueError("hypothesis references an unknown candidate")
        for interpretation in [*self.lesions, self.specimen, *self.other_findings]:
            if bool(interpretation.get("hypothesis")) == bool(interpretation.get("source_subject")):
                raise ValueError("interpretation must reference one hypothesis or one unmatched source subject")
            if interpretation.get("hypothesis") and interpretation["hypothesis"] not in hypotheses:
                raise ValueError("interpretation references an unknown hypothesis")
            if set(interpretation.get("candidates", [])) - candidate_ids:
                raise ValueError("interpretation references an unknown candidate")
            for prop in interpretation.get("properties", []):
                if prop["status"] not in {"recorded", "not reported", "unreadable", "not assessed", "not applicable"}:
                    raise ValueError("property lost its source availability status")
                selected = prop.get("value")
                disposition = prop["disposition"]
                if disposition in {"adopted", "provisional"} and selected is None:
                    raise ValueError("selected property assessments require a typed value")
                if disposition in {"unresolved", "unavailable", "not applicable"} and selected is not None:
                    raise ValueError("unresolved or unavailable assessments cannot select a value")
                if selected is not None and not prop.get("supports"):
                    raise ValueError("selected values require traceable support")
        return self


def identify_issues(issues: list[dict]) -> list[dict]:
    """Stable IDs survive reruns without depending on issue queue order."""
    result = []
    seen = set()
    for original in issues:
        issue = dict(original)
        identity = json.dumps([issue["kind"], sorted(issue.get("context", [])),
                               issue.get("rule", ""), issue.get("reason", issue.get("explanation", issue.get("summary", "")))], sort_keys=True)
        issue["id"] = "i-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        issue.setdefault("status", "open")
        issue.setdefault("raised_by", ["rules"])
        if issue["id"] not in seen:
            result.append(issue)
            seen.add(issue["id"])
    return result


def write_run(combined: dict, case_dir: Path) -> Path:
    output = CombinedOutput.model_validate(combined)
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = case_dir / run_id
    run_dir.mkdir(exist_ok=False)
    target = run_dir / "combined.json"
    target.write_text(output.model_dump_json(indent=2) + "\n", encoding="utf-8")
    # A relative link keeps the run tree portable. Replace only our temporary link.
    temporary = case_dir / (".latest-" + uuid.uuid4().hex)
    try:
        temporary.symlink_to(run_id, target_is_directory=True)
        os.replace(temporary, case_dir / "latest")
    finally:
        temporary.unlink(missing_ok=True)
    return target
