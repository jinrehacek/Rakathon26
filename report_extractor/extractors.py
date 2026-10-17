from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .models import TextLayer

PROMPT_VERSION = "report-extraction-v2"
OUTPUT_CONTRACT_VERSION = "report-3"


class ExtractionError(RuntimeError):
    pass


class Extractor(Protocol):
    mode: str

    def extract(self, text_layer: TextLayer) -> Any: ...


class FixtureExtractor:
    mode = "fixture"

    def __init__(self, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)

    def extract(self, text_layer: TextLayer, *, validation_errors=None) -> Any:
        try:
            fixture = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExtractionError(f"Could not read fixture response: {exc}") from exc
        if not isinstance(fixture, dict) or fixture.get("mode") != "fixture":
            raise ExtractionError("Fixture file must explicitly declare mode='fixture'.")
        if fixture.get("prompt_version") != PROMPT_VERSION:
            raise ExtractionError("Fixture prompt_version does not match this extractor.")
        if fixture.get("output_contract_version") != OUTPUT_CONTRACT_VERSION:
            raise ExtractionError("Fixture output contract version is unsupported.")
        if fixture.get("for_text_sha256") != text_layer.text_sha256:
            raise ExtractionError(
                "Fixture is bound to different text; fixture output was not applied."
            )
        return fixture.get("response")


class ExternalExtractorDisabled:
    mode = "external-disabled"

    def extract(self, text_layer: TextLayer) -> Any:
        raise ExtractionError(
            "External extraction is disabled and unconfigured. No network calls "
            "were made; only fixture mode is available in this prototype."
        )
