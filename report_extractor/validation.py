from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import ValidationError

from .models import (
    COORDINATE_CONVENTION,
    OFFSET_CONVENTION,
    AvailabilityStatus,
    CoverageCheck,
    Evidence,
    ExtractionIssue,
    ImageRegion,
    Observation,
    Subject,
    SubjectKind,
    TextLayer,
)

T = TypeVar("T")


@dataclass
class QuarantinedItem:
    item_type: str
    item_id: str | None
    raw: Any
    reasons: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    evidence: list[Evidence] = field(default_factory=list)
    subjects: list[Subject] = field(default_factory=list)
    coverage: list[CoverageCheck] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    issues: list[ExtractionIssue] = field(default_factory=list)
    quarantine: list[QuarantinedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.quarantine and not self.errors


def _identifier(raw: Any) -> str | None:
    value = raw.get("id") if isinstance(raw, dict) else None
    return value if isinstance(value, str) else None


def _contains_surrogate(value: Any) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                return True
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _cycle_nodes(graph: dict[str, str | None]) -> set[str]:
    cycles: set[str] = set()
    completed: set[str] = set()
    for start in graph:
        path: list[str] = []
        positions: dict[str, int] = {}
        node: str | None = start
        while node in graph and node not in completed:
            if node in positions:
                cycles.update(path[positions[node] :])
                break
            positions[node] = len(path)
            path.append(node)
            node = graph[node]
        completed.update(path)
    return cycles


def _dependency_cycles(raw_items: list[Any]) -> set[str]:
    graph: dict[str, list[str]] = {}
    for raw in raw_items:
        item_id = _identifier(raw)
        dependencies = raw.get("derived_from", []) if isinstance(raw, dict) else []
        if item_id and isinstance(dependencies, list):
            graph[item_id] = [value for value in dependencies if isinstance(value, str)]
    cycle_nodes: set[str] = set()
    state: dict[str, int] = {}
    for start in graph:
        if state.get(start, 0):
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        stack: list[tuple[str, Any]] = [(start, iter(graph[start]))]
        state[start] = 1
        positions[start] = 0
        path.append(start)
        while stack:
            node, targets = stack[-1]
            try:
                target = next(targets)
            except StopIteration:
                stack.pop()
                state[node] = 2
                positions.pop(node, None)
                path.pop()
                continue
            if target not in graph:
                continue
            target_state = state.get(target, 0)
            if target_state == 1:
                cycle_nodes.update(path[positions[target] :])
            elif target_state == 0:
                state[target] = 1
                positions[target] = len(path)
                path.append(target)
                stack.append((target, iter(graph[target])))
    return cycle_nodes


def _collect_duplicates(raw_items: list[Any]) -> dict[str, str]:
    counts: dict[str, int] = defaultdict(int)
    for raw in raw_items:
        item_id = _identifier(raw)
        if item_id:
            counts[item_id] += 1
    return {
        item_id: "duplicate identifier"
        for item_id, count in counts.items()
        if count > 1
    }


def _quarantine(
    result: ValidationResult,
    item_type: str,
    raw: Any,
    reasons: list[str],
) -> None:
    result.quarantine.append(
        QuarantinedItem(
            item_type=item_type,
            item_id=_identifier(raw),
            raw=raw,
            reasons=list(dict.fromkeys(reasons)),
        )
    )


def _add_quarantine_reason(
    result: ValidationResult, item_type: str, item_id: str, reason: str
) -> None:
    for item in result.quarantine:
        if item.item_type == item_type and item.item_id == item_id:
            if reason not in item.reasons:
                item.reasons.append(reason)


def _validate_collection(
    raw_items: list[Any],
    model: type[T],
    item_type: str,
    result: ValidationResult,
    preexisting_reasons: dict[str, list[str]] | None = None,
) -> tuple[list[T], dict[str, T]]:
    valid: list[T] = []
    by_id: dict[str, T] = {}
    duplicates = _collect_duplicates(raw_items)
    reasons_by_id = preexisting_reasons or {}
    for raw in raw_items:
        reasons = list(reasons_by_id.get(_identifier(raw) or "", []))
        if not isinstance(raw, dict):
            _quarantine(result, item_type, raw, reasons + ["item must be a JSON object"])
            continue
        item_id = _identifier(raw)
        if _contains_surrogate(raw):
            reasons.append("item contains an unpaired Unicode surrogate")
        if item_id in duplicates:
            reasons.append(duplicates[item_id])
        if reasons:
            _quarantine(result, item_type, raw, reasons)
            continue
        try:
            item = model.model_validate(raw)
        except ValidationError as exc:
            _quarantine(
                result,
                item_type,
                raw,
                [error["msg"] for error in exc.errors()],
            )
            continue
        valid.append(item)
        if item_id:
            by_id[item_id] = item
    return valid, by_id


def _validate_evidence(
    raw_items: list[Any], text_layer: TextLayer, result: ValidationResult
) -> tuple[list[Evidence], dict[str, Evidence]]:
    valid: list[Evidence] = []
    by_id: dict[str, Evidence] = {}
    duplicates = _collect_duplicates(raw_items)
    for raw in raw_items:
        reasons: list[str] = []
        if not isinstance(raw, dict):
            _quarantine(result, "evidence", raw, ["item must be a JSON object"])
            continue
        item_id = _identifier(raw)
        if item_id in duplicates:
            reasons.append(duplicates[item_id])
        if _contains_surrogate(raw):
            reasons.append("item contains an unpaired Unicode surrogate")
        try:
            evidence = Evidence.model_validate(raw)
        except ValidationError as exc:
            _quarantine(
                result,
                "evidence",
                raw,
                reasons + [error["msg"] for error in exc.errors()],
            )
            continue
        if evidence.text_layer_id != text_layer.id:
            reasons.append("evidence points to a different text layer")
        if evidence.quotation is None:
            pass
        elif evidence.end_offset > len(text_layer.text):
            reasons.append("evidence offsets exceed the immutable text layer")
        elif (
            evidence.start_offset >= evidence.end_offset
            or text_layer.text[evidence.start_offset : evidence.end_offset]
            != evidence.quotation
        ):
            reasons.append("quotation does not match its exact text offsets")

        if evidence.image_region is not None:
            region = evidence.image_region
            if text_layer.input_kind.value != "image":
                reasons.append("plain-text input cannot have image coordinates")
            elif (
                region.x + region.width > (text_layer.image_width or 0)
                or region.y + region.height > (text_layer.image_height or 0)
                or region.coordinate_convention != COORDINATE_CONVENTION
            ):
                reasons.append("image region exceeds the source-image coordinates")
        if evidence.offset_convention != OFFSET_CONVENTION:
            reasons.append("unsupported text offset convention")
        if reasons:
            _quarantine(result, "evidence", raw, reasons)
        else:
            if evidence.quotation is not None and evidence.image_region is None and text_layer.input_kind.value == "image":
                overlapping = [
                    word
                    for word in text_layer.words
                    if word.start_offset < evidence.end_offset
                    and word.end_offset > evidence.start_offset
                ]
                if overlapping:
                    left = min(word.x for word in overlapping)
                    top = min(word.y for word in overlapping)
                    right = max(word.x + word.width for word in overlapping)
                    bottom = max(word.y + word.height for word in overlapping)
                    evidence = evidence.model_copy(
                        update={
                            "image_region": ImageRegion(
                                x=left,
                                y=top,
                                width=right - left,
                                height=bottom - top,
                            )
                        }
                    )
        if not reasons and item_id:
            valid.append(evidence)
            by_id[item_id] = evidence
    return valid, by_id


def _as_list(payload: dict[str, Any], field_name: str) -> list[Any]:
    value = payload.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"response field {field_name!r} must be an array")
    return value


def validate_payload(payload: Any, text_layer: TextLayer, *, contract: bool = False) -> ValidationResult:
    result = ValidationResult()
    required = {
        "source_text_sha256",
        "evidence",
        "subjects",
        "coverage",
        "observations",
        "issues",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required
        or payload.get("source_text_sha256") != text_layer.text_sha256
    ):
        _quarantine(
            result,
            "payload",
            payload,
            ["whole response is malformed or bound to different source text"],
        )
        result.errors.append("Whole-payload corruption; no response items were usable.")
        return result
    try:
        evidence_raw = _as_list(payload, "evidence")
        subjects_raw = _as_list(payload, "subjects")
        coverage_raw = _as_list(payload, "coverage")
        observations_raw = _as_list(payload, "observations")
        issues_raw = _as_list(payload, "issues")
    except ValueError as exc:
        _quarantine(result, "payload", payload, [str(exc)])
        result.errors.append("Whole-payload corruption; no response items were usable.")
        return result

    result.evidence, evidence_by_id = _validate_evidence(
        evidence_raw, text_layer, result
    )
    subject_graph = {
        item_id: raw.get("parent_id")
        if isinstance(raw.get("parent_id"), str)
        else None
        for raw in subjects_raw
        if isinstance(raw, dict) and isinstance((item_id := raw.get("id")), str)
    }
    subject_cycles = _cycle_nodes(subject_graph)
    subject_reasons = {
        item_id: ["subject containment cycle"] for item_id in subject_cycles
    }
    result.subjects, subjects_by_id = _validate_collection(
        subjects_raw, Subject, "subject", result, subject_reasons
    )
    invalid_subject_ids = {
        item_id
        for raw in subjects_raw
        if (item_id := _identifier(raw)) and item_id not in subjects_by_id
    }

    for subject in list(result.subjects):
        reasons: list[str] = []
        if any(evidence_id not in evidence_by_id for evidence_id in subject.evidence_ids):
            reasons.append("subject references missing or quarantined evidence")
        if subject.kind == SubjectKind.SPECIMEN and subject.parent_id is not None:
            reasons.append("specimen cannot have a parent")
        if subject.kind == SubjectKind.TUMOUR_FOCUS:
            if subject.identification_basis != "explicit":
                reasons.append("tumour-focus subjects must be explicit in the report")
            if subject.parent_id is None:
                reasons.append("tumour focus must belong to a specimen")
            elif subject.parent_id not in subjects_by_id:
                reasons.append("tumour focus references a missing or invalid specimen")
            elif subjects_by_id[subject.parent_id].kind != SubjectKind.SPECIMEN:
                reasons.append("tumour-focus parent must be a specimen")
        if subject.parent_id and subject.parent_id not in subjects_by_id:
            reasons.append("subject references a missing or invalid parent")
        if reasons:
            raw = next(
                (item for item in subjects_raw if _identifier(item) == subject.id),
                subject.model_dump(mode="json"),
            )
            result.subjects.remove(subject)
            subjects_by_id.pop(subject.id, None)
            invalid_subject_ids.add(subject.id)
            _quarantine(result, "subject", raw, reasons)

    result.coverage, _ = _validate_collection(
        coverage_raw, CoverageCheck, "coverage", result
    )
    for check in list(result.coverage):
        reasons = []
        if check.subject_id not in subjects_by_id:
            reasons.append("coverage references a missing or invalid subject")
        if not check.checked or not check.source_complete or not text_layer.text:
            if check.checked or check.source_complete:
                reasons.append(
                    "coverage cannot support absence unless source processing is complete"
                )
        if reasons:
            raw = next(
                (item for item in coverage_raw if _identifier(item) == check.id),
                check.model_dump(mode="json"),
            )
            result.coverage.remove(check)
            _quarantine(result, "coverage", raw, reasons)

    observation_cycles = _dependency_cycles(observations_raw)
    observation_reasons = {
        item_id: ["observation dependency cycle"] for item_id in observation_cycles
    }
    parsed_observations, observations_by_id = _validate_collection(
        observations_raw,
        Observation,
        "observation",
        result,
        observation_reasons,
    )
    invalid_observation_ids = {
        item_id
        for raw in observations_raw
        if (item_id := _identifier(raw)) and item_id not in observations_by_id
    }
    raw_observations = {
        item_id: raw
        for raw in observations_raw
        if isinstance(raw, dict) and (item_id := _identifier(raw))
    }
    propagated: set[str] = set()
    changed = True
    while changed:
        changed = False
        for item_id, raw in raw_observations.items():
            dependencies = raw.get("derived_from", [])
            if isinstance(dependencies, list) and any(
                dependency in invalid_observation_ids for dependency in dependencies
            ) and item_id not in propagated:
                propagated.add(item_id)
                invalid_observation_ids.add(item_id)
                _add_quarantine_reason(
                    result,
                    "observation",
                    item_id,
                    "depends on an invalid or quarantined observation",
                )
                changed = True

    for raw in observations_raw:
        item_id = _identifier(raw)
        observation = observations_by_id.get(item_id or "")
        if observation is None:
            continue
        reasons = []
        if observation.subject_id not in subjects_by_id:
            reasons.append("observation references a missing or invalid subject")
        if any(evidence_id not in evidence_by_id for evidence_id in observation.evidence_ids):
            reasons.append("observation references missing or quarantined evidence")
        if observation.status == AvailabilityStatus.NOT_REPORTED:
            if not any(
                check.subject_id == observation.subject_id
                and check.property == observation.property
                and check.checked
                and check.source_complete
                for check in result.coverage
            ):
                reasons.append(
                    "not reported requires a matching complete coverage assessment"
                )
        if reasons:
            observations_by_id.pop(observation.id, None)
            parsed_observations.remove(observation)
            _quarantine(result, "observation", raw, reasons)
    result.observations = parsed_observations

    for raw in issues_raw:
        if not isinstance(raw, dict):
            _quarantine(result, "issue", raw, ["item must be a JSON object"])
            continue
        if _contains_surrogate(raw):
            _quarantine(
                result, "issue", raw, ["item contains an unpaired Unicode surrogate"]
            )
            continue
        try:
            issue = ExtractionIssue.model_validate(raw)
        except ValidationError as exc:
            _quarantine(
                result, "issue", raw, [error["msg"] for error in exc.errors()]
            )
            continue
        reasons = []
        if any(evidence_id not in evidence_by_id for evidence_id in issue.evidence_ids):
            reasons.append("issue references missing or quarantined evidence")
        if any(
            subject_id not in subjects_by_id
            for subject_id in issue.alternative_subject_ids
        ):
            reasons.append("issue references a missing or invalid alternative subject")
        if reasons:
            _quarantine(result, "issue", raw, reasons)
        else:
            result.issues.append(issue)

    if invalid_subject_ids:
        # A child cannot remain valid after its containing subject was quarantined.
        changed = True
        while changed:
            changed = False
            for raw in subjects_raw:
                if not isinstance(raw, dict):
                    continue
                item_id = _identifier(raw)
                parent_id = raw.get("parent_id")
                if (
                    item_id in subjects_by_id
                    and isinstance(parent_id, str)
                    and parent_id in invalid_subject_ids
                ):
                    subject = subjects_by_id.pop(item_id)
                    result.subjects.remove(subject)
                    invalid_subject_ids.add(item_id)
                    _quarantine(
                        result,
                        "subject",
                        raw,
                        ["depends on a missing or quarantined parent subject"],
                    )
                    changed = True
        for observation in list(result.observations):
            if observation.subject_id in invalid_subject_ids:
                result.observations.remove(observation)
                _quarantine(
                    result,
                    "observation",
                    next(
                        (
                            raw
                            for raw in observations_raw
                            if _identifier(raw) == observation.id
                        ),
                        observation.model_dump(mode="json"),
                    ),
                    ["depends on a missing or quarantined subject"],
                )
        for check in list(result.coverage):
            if check.subject_id in invalid_subject_ids:
                result.coverage.remove(check)
                _quarantine(
                    result,
                    "coverage",
                    next(
                        (
                            raw
                            for raw in coverage_raw
                            if _identifier(raw) == check.id
                        ),
                        check.model_dump(mode="json"),
                    ),
                    ["depends on a missing or quarantined subject"],
                )
        for issue in list(result.issues):
            if any(
                subject_id in invalid_subject_ids
                for subject_id in issue.alternative_subject_ids
            ):
                result.issues.remove(issue)
                _quarantine(
                    result,
                    "issue",
                    next(
                        (raw for raw in issues_raw if _identifier(raw) == issue.id),
                        issue.model_dump(mode="json"),
                    ),
                    ["depends on a missing or quarantined alternative subject"],
                )

    if contract and not result.quarantine:
        from .contract import validate_content
        try:
            validate_content(text_layer, result)
        except (ValueError, KeyError, TypeError) as exc:
            result.errors.append(str(exc))
    if result.quarantine and not result.errors:
        result.errors.append("Invalid items remain in quarantine.")
    return result
