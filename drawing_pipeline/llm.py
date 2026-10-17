"""Stateless Gemini generateContent calls with structured JSON output.

No response caching: each call is one fresh contents message, so sampled runs
differ. The API key travels only in a header and is redacted from every log.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel

API = "https://generativelanguage.googleapis.com/v1beta"
RETRYABLE = (408, 429, 500, 502, 503, 504)
T = TypeVar("T", bound=BaseModel)


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing; run with uv run --env-file .env")
    return key


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def image_part(png: bytes) -> dict:
    return {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode()}}


def api_schema(model: type[BaseModel]) -> dict:
    # Nested bounded arrays exceed Gemini's schema compiler limits. Bounds stay in local validation.
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in ("minItems", "maxItems")}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return strip(model.model_json_schema())


def request_body(parts: list[dict], schema: type[BaseModel], *, temperature: float = 1.0, thinking: str = "low",
                 resolution: str = "high", max_tokens: int = 16000) -> dict:
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": api_schema(schema),
                                 "mediaResolution": "MEDIA_RESOLUTION_" + resolution.upper(),
                                 "thinkingConfig": {"thinkingLevel": thinking.upper()},
                                 "maxOutputTokens": max_tokens, "temperature": temperature}}


def request_record(body: dict) -> dict:
    """The request as logged: text parts verbatim, images as hashes."""
    parts = []
    for part in body["contents"][0]["parts"]:
        if "inlineData" in part:
            parts.append({"image_sha256": sha256(base64.b64decode(part["inlineData"]["data"]))})
        else:
            parts.append(part)
    return {"parts": parts, "generation_config": body["generationConfig"]}


def parse_response(response: dict, schema: type[T]) -> T:
    candidates = response.get("candidates", [])
    if not candidates or candidates[0].get("finishReason") != "STOP":
        reason = candidates[0].get("finishReason") if candidates else response.get("promptFeedback")
        raise ValueError(f"No complete candidate: {reason}")
    parts = candidates[0].get("content", {}).get("parts", [])
    return schema.model_validate_json("".join(p.get("text", "") for p in parts if not p.get("thought")))


def call(client: httpx.Client, model: str, key: str, body: dict, schema: type[T], out: Path,
         sleeper=time.sleep, attempts: int = 2) -> tuple[T | None, list[dict]]:
    """POST once, retry once on transport, HTTP 408/429/5xx or invalid JSON. Saves every raw response in out."""
    out.mkdir(parents=True, exist_ok=True)
    save(out / "request.json", {"model": model, **request_record(body)})
    history = []
    for attempt in range(1, attempts + 1):
        start = time.perf_counter()
        entry, retryable = {"attempt": attempt}, True
        try:
            response = client.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body)
            entry["http_status"] = response.status_code
            if response.status_code >= 400:
                retryable = response.status_code in RETRYABLE
                save(out / f"attempt_{attempt}_error.json", response.json())
                raise ValueError(f"HTTP {response.status_code}")
            raw = response.json()
            save(out / f"attempt_{attempt}_response.json", raw)
            entry.update(usage=raw.get("usageMetadata", {}), model_version=raw.get("modelVersion"))
            parsed = parse_response(raw, schema)
            entry["seconds"] = round(time.perf_counter() - start, 2)
            history.append(entry)
            save(out / "attempts.json", history)
            return parsed, history
        except (httpx.RequestError, ValueError) as error:
            entry.update(error=str(error).replace(key, "[redacted]")[:2000], seconds=round(time.perf_counter() - start, 2))
            history.append(entry)
            save(out / "attempts.json", history)
            if not retryable or attempt == attempts:
                return None, history
            sleeper(2)
    return None, history


def replay(out: Path, schema: type[T]) -> T | None:
    """Re-read the last successful saved response in out, with no API call. For rebuilding later stages."""
    for path in sorted(out.glob("attempt_*_response.json"), reverse=True):
        try:
            return parse_response(json.loads(path.read_text()), schema)
        except ValueError:
            continue
    return None
