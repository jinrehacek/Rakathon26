from __future__ import annotations

import hashlib
import io
from pathlib import Path

from .models import (
    ExtractionMethod,
    InputKind,
    TextLayer,
)


class IngestionError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _layer_id(source_hash: str, text_hash: str, method: str, tool_version: str) -> str:
    identity = f"{source_hash}:{text_hash}:{method}:{tool_version}".encode("utf-8")
    return "tl-" + hashlib.sha256(identity).hexdigest()[:24]


def build_text_layer(source: str | Path, *, transport=None, key=None) -> TextLayer:
    path = Path(source).expanduser()
    if not path.is_file():
        raise IngestionError(f"Input file does not exist: {path}")
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in {".txt", ".text"}:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestionError("Plain-text input must be UTF-8.") from exc
        source_hash = _sha256(raw)
        text_hash = _sha256(text.encode("utf-8"))
        tool_version = "1"
        return TextLayer(
            id=_layer_id(
                source_hash, text_hash, ExtractionMethod.PLAIN_TEXT.value, tool_version
            ),
            source_path=str(path.resolve()),
            source_sha256=source_hash,
            text_sha256=text_hash,
            input_kind=InputKind.TEXT,
            extraction_method=ExtractionMethod.PLAIN_TEXT,
            tool="UTF-8 decoder",
            tool_version=tool_version,
            text=text,
        )
    if suffix not in {".jpg", ".jpeg", ".png"}:
        raise IngestionError("Supported input formats are UTF-8 text, JPEG, and PNG.")
    if suffix == ".png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise IngestionError("The .png input does not have a PNG signature.")
    if suffix in {".jpg", ".jpeg"} and not raw.startswith(b"\xff\xd8"):
        raise IngestionError("The JPEG input does not have a JPEG signature.")

    from PIL import Image, UnidentifiedImageError
    from .gemini import MODEL_ID, TRANSCRIPTION_VERSION, transcribe_image

    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise IngestionError("Could not read report image dimensions.") from exc
    text = transcribe_image(raw, mime="image/png" if suffix == ".png" else "image/jpeg",
                            transport=transport, key=key)
    version = f"{MODEL_ID}/{TRANSCRIPTION_VERSION}"
    source_hash = _sha256(raw)
    text_hash = _sha256(text.encode("utf-8"))
    return TextLayer(
        id=_layer_id(
            source_hash, text_hash, ExtractionMethod.GEMINI.value, version
        ),
        source_path=str(path.resolve()),
        source_sha256=source_hash,
        text_sha256=text_hash,
        input_kind=InputKind.IMAGE,
        extraction_method=ExtractionMethod.GEMINI,
        tool="Gemini",
        tool_version=version,
        language="ces",
        text=text,
        image_width=width,
        image_height=height,
    )
