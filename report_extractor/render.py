from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any

from .models import TextLayer
from .validation import QuarantinedItem, ValidationResult


def _escape(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=True, indent=2, default=str)
    value = str(value).encode("utf-8", errors="replace").decode("utf-8")
    return html.escape(str(value), quote=True)


def _embedded_image(text_layer: TextLayer) -> str | None:
    source = Path(text_layer.source_path)
    if text_layer.input_kind.value != "image" or not source.is_file():
        return None
    media_type = "image/png" if source.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def render_html(
    document: dict[str, Any],
    text_layer: TextLayer,
    extraction: dict[str, Any],
    result: ValidationResult,
) -> str:
    evidence = {item.id: item for item in result.evidence}
    subjects = {item.id: item for item in result.subjects}
    image_data = _embedded_image(text_layer)

    evidence_regions = [
        item.image_region.model_dump(mode="json")
        for item in result.evidence
        if item.image_region is not None
    ]
    page_image = ""
    if image_data:
        boxes = "".join(
            f'<rect x="{region["x"]}" y="{region["y"]}" '
            f'width="{region["width"]}" height="{region["height"]}" '
            'fill="none" stroke="#c53030" stroke-width="4" />'
            for region in evidence_regions
        )
        page_image = (
            '<section><h2>Source scan (local copy)</h2>'
            f'<svg class="scan" viewBox="0 0 {text_layer.image_width} '
            f'{text_layer.image_height}" role="img" aria-label="Original report '
            'image with evidence regions outlined">'
            f'<image href="{image_data}" width="{text_layer.image_width}" '
            f'height="{text_layer.image_height}" />{boxes}</svg></section>'
        )

    evidence_rows = []
    for item in result.evidence:
        region = item.image_region
        region_text = (
            f"x={region.x}, y={region.y}, width={region.width}, "
            f"height={region.height} pixels"
            if region
            else "No image region available"
        )
        evidence_rows.append(
            "<article><h3>"
            + _escape(item.id)
            + "</h3><blockquote>"
            + _escape(item.quotation)
            + "</blockquote><p>Page "
            + _escape(item.page)
            + "; text offsets ["
            + _escape(item.start_offset)
            + ", "
            + _escape(item.end_offset)
            + "); "
            + _escape(region_text)
            + "</p></article>"
        )

    subject_rows = []
    for item in result.subjects:
        citations = ", ".join(item.evidence_ids)
        parent = subjects.get(item.parent_id or "")
        subject_rows.append(
            "<tr><td>"
            + _escape(item.kind.value)
            + "</td><td>"
            + _escape(item.label)
            + "</td><td>"
            + (_escape(parent.label) if parent else "—")
            + "</td><td>"
            + _escape(item.identification_basis)
            + "</td><td>"
            + _escape(citations)
            + "</td></tr>"
        )

    observation_rows = []
    for item in result.observations:
        subject = subjects.get(item.subject_id)
        supporting = [
            evidence[evidence_id].quotation
            for evidence_id in item.evidence_ids
            if evidence_id in evidence
        ]
        value = item.value.model_dump(mode="json") if item.value else "—"
        observation_rows.append(
            "<tr><td>"
            + _escape(subject.label if subject else item.subject_id)
            + "</td><td>"
            + _escape(item.property.value)
            + "</td><td>"
            + _escape(item.status.value)
            + "</td><td><pre>"
            + _escape(value)
            + "</pre></td><td>"
            + _escape(item.basis.value)
            + "</td><td>"
            + _escape(item.review_status)
            + "</td><td>"
            + _escape(
                "reading: "
                + item.certainty.extraction.value
                + "; interpretation: "
                + item.certainty.interpretation.value
            )
            + "</td><td>"
            + "<br>".join(_escape(quote) for quote in supporting)
            + "</td></tr>"
        )

    coverage_rows = "".join(
        "<tr><td>"
        + _escape(item.subject_id)
        + "</td><td>"
        + _escape(item.property.value)
        + "</td><td>"
        + _escape(item.checked)
        + "</td><td>"
        + _escape(item.source_complete)
        + "</td><td>"
        + _escape(item.rationale)
        + "</td></tr>"
        for item in result.coverage
    )
    issue_rows = "".join(
        "<li><strong>"
        + _escape(item.kind)
        + ":</strong> "
        + _escape(item.summary)
        + " — evidence "
        + _escape(", ".join(item.evidence_ids))
        + "; alternatives "
        + _escape(", ".join(item.alternative_subject_ids) or "unlisted")
        + "</li>"
        for item in result.issues
    )
    quarantine_rows = "".join(
        "<details><summary>"
        + _escape(item.item_type)
        + " "
        + _escape(item.item_id or "(no id)")
        + ": "
        + _escape("; ".join(item.reasons))
        + "</summary><pre>"
        + _escape(item.raw)
        + "</pre></details>"
        for item in result.quarantine
    )
    if result.errors:
        quarantine_rows += "<p>" + "<br>".join(
            _escape(error) for error in result.errors
        ) + "</p>"

    mode = extraction["mode"]
    status = "COMPLETE" if extraction["complete"] else "INCOMPLETE"
    fixture_banner = (
        '<p class="warning">FIXTURE MODE — synthetic response only; this is not '
        "model extraction and is not evidence of real-report interpretation "
        "accuracy.</p>"
        if mode == "fixture"
        else ""
    )
    limitations = (
        "<p>Deterministic validation checks structure, references, declared "
        "coverage, and evidence offsets; it cannot prove that an interpretation "
        "or subject attribution is semantically correct. No clinical confidence "
        "or clinical validity is claimed.</p>"
        "<p>OCR confidence, when present, is a word-reading signal only and is "
        "not a calibrated medical certainty.</p>"
    )
    original_text = _escape(text_layer.text)
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offline report extraction review</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#202124}}
h1,h2{{line-height:1.2}} table{{border-collapse:collapse;width:100%;margin:1rem 0;display:block;overflow-x:auto}}
th,td{{border:1px solid #aaa;padding:.5rem;text-align:left;vertical-align:top}}
blockquote,pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:.7rem}}
.warning,.incomplete{{background:#fff0d0;border:2px solid #9c4a00;padding:1rem;font-weight:700}}
.complete{{background:#e5f5e8;border:2px solid #26713b;padding:1rem;font-weight:700}}
.scan{{width:100%;height:auto;border:1px solid #777}}
</style>
<body>
<h1>Offline report extraction review</h1>
{fixture_banner}
<p class="{ 'complete' if extraction['complete'] else 'incomplete' }">
{_escape(status)} — all results are unreviewed; this is not a clinical record.
</p>
<p>Mode: {_escape(mode)}; document: {_escape(document['id'])}; source:
{_escape(document['source_path'])}; SHA-256: {_escape(document['source_sha256'])}</p>
<p>Text layer: {_escape(text_layer.id)}; method:
{_escape(text_layer.extraction_method.value)}; tool:
{_escape(text_layer.tool)} {_escape(text_layer.tool_version)}; page 1;
text SHA-256: {_escape(text_layer.text_sha256)}</p>
{page_image}
<h2>Subjects</h2>
<table><thead><tr><th>Kind</th><th>Label</th><th>Parent</th><th>Identification</th><th>Evidence IDs</th></tr></thead>
<tbody>{''.join(subject_rows) or '<tr><td colspan="5">No valid subjects</td></tr>'}</tbody></table>
<h2>Observations</h2>
<table><thead><tr><th>Subject</th><th>Property</th><th>Status</th><th>Value</th><th>Basis</th><th>Review</th><th>Certainty (separate)</th><th>Evidence quotation</th></tr></thead>
<tbody>{''.join(observation_rows) or '<tr><td colspan="8">No valid observations</td></tr>'}</tbody></table>
<h2>Coverage checks</h2>
<table><thead><tr><th>Subject</th><th>Property</th><th>Checked</th><th>Source complete</th><th>Rationale / limitation</th></tr></thead>
<tbody>{coverage_rows or '<tr><td colspan="5">No coverage checks; omitted catalogue properties are not implied to be absent.</td></tr>'}</tbody></table>
<h2>Unresolved issues</h2><ul>{issue_rows or '<li>None recorded</li>'}</ul>
<h2>Evidence</h2>{''.join(evidence_rows) or '<p>No valid evidence.</p>'}
<h2>Quarantined items</h2>
<p>Invalid raw inputs are separate from valid schema output. Extraction is incomplete when any items are quarantined.</p>
{quarantine_rows or '<p>None</p>'}
<h2>Original immutable text layer</h2><pre>{original_text}</pre>
<h2>Limits</h2>{limitations}
</body></html>
"""


def render_text_layer_preview(text_layer: TextLayer) -> str:
    image_data = _embedded_image(text_layer)
    is_ocr = text_layer.extraction_method.value == "tesseract"
    is_gemini = text_layer.extraction_method.value == "gemini"
    scan = ""
    if image_data:
        boxes = "".join(
            f'<rect x="{word.x}" y="{word.y}" width="{word.width}" '
            f'height="{word.height}" fill="none" stroke="#1769aa" '
            'stroke-width="2" />'
            for word in text_layer.words
        )
        scan = (
            '<h2>Original source image</h2>'
            f'<svg class="scan" viewBox="0 0 {text_layer.image_width} '
            f'{text_layer.image_height}" role="img" aria-label="Original source image">'
            f'<image href="{image_data}" width="{text_layer.image_width}" '
            f'height="{text_layer.image_height}" />{boxes}</svg>'
        )
    word_rows = "".join(
        "<tr><td>"
        + _escape(word.text)
        + "</td><td>"
        + _escape(word.start_offset)
        + "–"
        + _escape(word.end_offset)
        + "</td><td>"
        + _escape(f"{word.x}, {word.y}, {word.width}, {word.height}")
        + "</td><td>"
        + _escape(word.confidence if word.confidence is not None else "unavailable")
        + "</td></tr>"
        for word in text_layer.words
    )
    word_rows = word_rows or '<tr><td colspan="4">No OCR words returned</td></tr>'
    title = (
        "Gemini transcription review" if is_gemini
        else "Local OCR text-layer review" if is_ocr
        else "Plain-text layer review"
    )
    review_detail = (
        "<details><summary>OCR word boxes and confidence</summary>"
        "<p>Boxes use source-image pixels from the upper-left origin. Tesseract "
        "word confidence is a reading signal only, not medical certainty.</p>"
        "<table><thead><tr><th>Word</th><th>Text offsets</th><th>x, y, width, "
        "height</th><th>Tesseract confidence (0–100)</th></tr></thead>"
        f"<tbody>{word_rows}</tbody></table></details>"
        if is_ocr
        else "<p>Plain-text input has no scan coordinates and no claim of "
        "verified OCR accuracy.</p>"
    )
    if is_gemini:
        review_detail = "<p>Gemini transcribed this scan verbatim. Word boxes and word confidence are not available.</p>"
    warning = (
        "OCR ONLY — no semantic extraction or medical interpretation was run."
        if is_ocr
        else "TEXT INGEST ONLY — no semantic extraction or medical interpretation was run."
    )
    if is_gemini:
        warning = "TRANSCRIPTION ONLY. No semantic extraction was run."
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#202124}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:.7rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0;display:block;overflow-x:auto}}
th,td{{border:1px solid #aaa;padding:.5rem;text-align:left;vertical-align:top}}
.warning{{background:#fff0d0;border:2px solid #9c4a00;padding:1rem;font-weight:700}}
.scan{{width:100%;height:auto;border:1px solid #777}}
</style>
<body>
<h1>{_escape(title)}</h1>
<p class="warning">{_escape(warning)}</p>
<p>Source: {_escape(text_layer.source_path)}; SHA-256: {_escape(text_layer.source_sha256)};
method: {_escape(text_layer.extraction_method.value)}; tool:
{_escape(text_layer.tool)} {_escape(text_layer.tool_version)}; language:
{_escape(text_layer.language or "not applicable")}; page 1.</p>
{scan}
<h2>Immutable extracted text</h2><pre>{_escape(text_layer.text)}</pre>
{review_detail}
</body></html>
"""
