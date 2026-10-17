from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .extractors import OUTPUT_CONTRACT_VERSION, PROMPT_VERSION, Extractor, ExtractionError
from .models import SCHEMA_VERSION, TextLayer
from .render import render_html
from .validation import QuarantinedItem, ValidationResult, validate_payload


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    kind: str = "text_report"
    language: str = "cs"
    source_path: str
    source_sha256: str


class ExtractionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    document_id: str
    source_text_layer_id: str
    created_at: datetime
    extractor_version: str
    schema_version: str
    prompt_version: str
    output_contract_version: str
    mode: str
    model_id: str | None = None
    call_settings: dict = Field(default_factory=dict)
    complete: bool
    evidence: list[dict[str, Any]]
    subjects: list[dict[str, Any]]
    coverage: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    issues: list[dict[str, Any]]


def _has_surrogate(value: Any) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                return True
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return False


def _json_dump(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=_has_surrogate(value),
            indent=2,
            default=str,
        )
        + "\n"
    )


def run_extraction(
    text_layer: TextLayer,
    extractor: Extractor,
    output_root: str | Path,
) -> Path:
    output_root = Path(output_root).expanduser().resolve()
    result = ValidationResult()
    for attempt in range(2):
        try:
            if attempt:
                feedback = result.errors + [
                    f"{item.item_type} {item.item_id}, property {item.raw.get('property') if isinstance(item.raw, dict) else 'unknown'}: {reason}"
                    for item in result.quarantine for reason in item.reasons]
                raw_payload = extractor.extract(text_layer, validation_errors=feedback)
            else:
                raw_payload = extractor.extract(text_layer)
            if getattr(extractor, "combined_response", False):
                from .anchoring import anchor_response
                raw_payload = anchor_response(raw_payload, text_layer)
            result = validate_payload(raw_payload, text_layer, contract=True)
        except (ExtractionError, ValueError, KeyError, TypeError) as exc:
            result = ValidationResult(errors=[str(exc)])
        if result.complete or not getattr(extractor, "retry_validation", False):
            break
    for item in result.quarantine:
        if item.item_type == "payload":
            item.raw = None
    document = DocumentMetadata(
        id=str(uuid.uuid4()),
        source_path=text_layer.source_path,
        source_sha256=text_layer.source_sha256,
    )
    extraction = ExtractionMetadata(
        id=str(uuid.uuid4()),
        document_id=document.id,
        source_text_layer_id=text_layer.id,
        created_at=datetime.now(UTC),
        extractor_version=f"report-extractor/{__version__}",
        schema_version=SCHEMA_VERSION,
        prompt_version=getattr(extractor, "prompt_version", PROMPT_VERSION),
        output_contract_version=OUTPUT_CONTRACT_VERSION,
        mode=extractor.mode,
        model_id=getattr(extractor, "model_id", None),
        call_settings=getattr(extractor, "call_settings", {}),
        complete=result.complete,
        evidence=[item.model_dump(mode="json") for item in result.evidence],
        subjects=[item.model_dump(mode="json") for item in result.subjects],
        coverage=[item.model_dump(mode="json") for item in result.coverage],
        observations=[item.model_dump(mode="json") for item in result.observations],
        issues=[item.model_dump(mode="json") for item in result.issues],
    )
    quarantine = [
        {
            "item_type": item.item_type,
            "item_id": item.item_id,
            "raw": None if item.item_type == "payload" else item.raw,
            "reasons": item.reasons,
        }
        for item in result.quarantine
    ]
    bundle = {
        "document": document.model_dump(mode="json"),
        "text_layer": text_layer.model_dump(mode="json"),
        "extraction": extraction.model_dump(mode="json"),
        "quarantine": quarantine,
        "validation_errors": result.errors,
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(output_root).expanduser() / f"{timestamp}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "text-layer.json").write_text(
        _json_dump(text_layer.model_dump(mode="json")), encoding="utf-8"
    )
    target = run_dir / "report.json"
    target.write_text(_json_dump(bundle), encoding="utf-8")
    # Keep the original diagnostic filename as a link to the one bundle.
    (run_dir / "result.json").symlink_to("report.json")
    (run_dir / "review.html").write_text(
        render_html(
            document.model_dump(mode="json"),
            text_layer,
            extraction.model_dump(mode="json"),
            result,
        ),
        encoding="utf-8",
    )
    if result.complete:
        # Validate the exact file central will consume, before publishing it.
        from central.inputs import load_report
        load_report(target)
        case_dir = Path(output_root)
        _preserve_manual_reference(case_dir)
        publish = case_dir / (".report-" + uuid.uuid4().hex)
        try:
            publish.symlink_to(Path(run_dir.name) / "report.json")
            os.replace(publish, Path(output_root) / "report.json")
        finally:
            publish.unlink(missing_ok=True)
    return run_dir


def _preserve_manual_reference(case_dir: Path) -> None:
    """Keep the pre-extractor probe inputs before publishing the first live run."""
    prior = case_dir / "report.json"
    if case_dir.parent.name != "report" or prior.is_symlink() or not prior.is_file():
        return
    content = prior.read_bytes()
    metadata = json.loads(content).get("extraction", {})
    if metadata.get("mode") != "manual":
        return
    reference_dir = case_dir.parent.parent / "central-eval" / case_dir.name
    reference_dir.mkdir(parents=True, exist_ok=True)
    original = reference_dir / "report-reference-original.json"
    if original.exists():
        if original.read_bytes() != content:
            raise ValueError("A different manual report reference is already archived; refusing replacement.")
    else:
        with original.open("xb") as stream:
            stream.write(content)
    reference = reference_dir / "report-reference.json"
    if not reference.exists():
        with reference.open("xb") as stream:
            stream.write(content)
