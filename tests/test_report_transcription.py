"""Gemini transcription is the report's sole image-to-text source."""
import base64
import hashlib
import json
import subprocess
from unittest.mock import patch

import pytest

from central.inputs import load_report
from report_extractor.cli import main
from report_extractor.ingest import build_text_layer
from report_extractor.gemini import GeminiExtractor, response_schema
from report_extractor.extractors import ExtractionError
from report_extractor.pipeline import run_extraction
from report_extractor.render import render_text_layer_preview
from test_report_gemini import prepared, response


def transcription(text, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [
        {"text": "private reasoning", "thought": True}, {"text": text}]}}]}


def test_new_extractions_do_not_request_ocr_disagreement_issues():
    kinds = response_schema()["$defs"]["ExtractionIssue"]["properties"]["kind"]["enum"]
    assert "ocr_disagreement" not in kinds


def test_gemini_text_is_preserved_and_anchors_published_values(tmp_path):
    path, old_layer, raw = prepared(tmp_path)
    from PIL import Image
    source = tmp_path / "report.jpg"
    Image.new("RGB", (100, 100), "white").save(source)
    text = old_layer.text + "\nZávěr: Žluťoučký kůň.\n"
    calls = []

    def transport(body, key):
        calls.append(body)
        assert key == "test-key"
        if len(calls) == 1:
            return transcription(text)
        return response(raw)

    with patch.object(subprocess, "run", side_effect=AssertionError("Local OCR invoked")):
        layer = build_text_layer(source, transport=transport, key="test-key")
        raw["extraction"]["source_text_sha256"] = layer.text_sha256
        run = run_extraction(layer, GeminiExtractor(key="test-key", transport=transport), path.parent)
    bundle = load_report(run / "report.json")
    assert len(calls) == 2
    assert layer.text == text
    assert layer.extraction_method == "gemini"
    assert layer.tool_version == "gemini-3.8-flash/report-transcription-v1"
    assert layer.words == ()
    assert (layer.image_width, layer.image_height) == (100, 100)
    assert layer.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert layer.text_sha256 == hashlib.sha256(text.encode()).hexdigest()
    parts = calls[0]["contents"][0]["parts"]
    assert base64.b64decode(parts[1]["inlineData"]["data"]) == source.read_bytes()
    assert calls[0]["generationConfig"]["responseMimeType"] == "text/plain"
    assert "verbatim" in parts[0]["text"].lower()
    assert "Tesseract" not in json.dumps(calls)
    assert bundle["text_layer"]["text"] == text
    for anchor in bundle["extraction"]["evidence"]:
        if anchor["quotation"] is not None:
            assert text[anchor["start_offset"]:anchor["end_offset"]] == anchor["quotation"]
    preview = render_text_layer_preview(layer)
    assert "Gemini transcription" in preview
    assert "Plain-text input has no scan coordinates" not in preview


@pytest.mark.parametrize("raw", [transcription("partial", "MAX_TOKENS"), transcription("  "),
    {"candidates": []}, {"error": {"message": "secret payload"}}])
def test_failed_transcription_never_falls_back_to_local_ocr(tmp_path, raw):
    from PIL import Image
    source = tmp_path / "report.png"
    Image.new("RGB", (100, 100), "white").save(source)
    with patch.object(subprocess, "run", side_effect=AssertionError("Local OCR invoked")):
        with pytest.raises(ExtractionError, match="complete transcription"):
            build_text_layer(source, key="key", transport=lambda body, key: raw)


def test_ingest_cli_uses_gemini_and_saves_only_transcription_artifacts(tmp_path, monkeypatch):
    from PIL import Image
    source = tmp_path / "report.png"
    Image.new("RGB", (30, 40), "white").save(source)
    text = "Závěr: pT2, R0.\n"
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("report_extractor.gemini._post", lambda body, key: transcription(text))
    assert main(["ingest", "--input", str(source), "--output-dir", str(tmp_path / "out")]) == 0
    run, = (tmp_path / "out").iterdir()
    assert (run / "page-1-text.txt").read_text() == text
    layer = json.loads((run / "text-layer.json").read_text())
    assert layer["extraction_method"] == "gemini"
    assert sorted(p.name for p in run.iterdir()) == ["page-1-text.txt", "review.html", "text-layer.json"]
