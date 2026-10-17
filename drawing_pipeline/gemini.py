"""Gemini reading of one view: original crop + cleaned crop over the sector map, 3 sampled runs.

Gemini never sees CV output. Each run is a fresh request; failed runs come back as None.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

import cv2 as cv
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from . import llm, models
from .geometry import normalized_box_to_crop, normalized_to_crop
from .models import RunMark, Sector
from .reference import LONGITUDINAL_ZONES, PRINTED_ZONES, VIEWS, normalize_zone, regions_for

PROMPT = Path(__file__).resolve().parents[1] / "prompts/gemini_drawing.md"
CLOSED_KINDS = frozenset({"closed outline", "small circle", "shading"})
OPEN_KINDS = frozenset({"open arc", "arrow"})
MAP_COLOUR = (255, 0, 255)  # BGR magenta; named in the prompt so Gemini does not report it as ink
PRINTED_LABEL = {code: label for label, code in PRINTED_ZONES.items()}

Coord = Annotated[int, Field(ge=0, le=1000)]
Point = Annotated[list[Coord], Field(min_length=2, max_length=2)]
Kind = Literal["closed outline", "open arc", "small circle", "shading", "side letter", "text", "arrow", "other"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarkBase(Strict):
    id: str
    kind: Kind
    polygon: Annotated[list[Point], Field(max_length=80)]
    box_2d: Annotated[list[Coord], Field(min_length=4, max_length=4)]
    text: str | None

    @model_validator(mode="after")
    def geometry(self):
        y0, x0, y1, x1 = self.box_2d
        # Flat boxes are allowed: thin strokes and letters are what the box fallback is for.
        if y0 > y1 or x0 > x1:
            raise ValueError("box_2d must be [ymin, xmin, ymax, xmax]")
        minimum = 3 if self.kind in CLOSED_KINDS else 2
        if self.polygon and len(self.polygon) < minimum:
            raise ValueError(f"{self.kind} polygon needs at least {minimum} points")
        return self


def _literal(values):
    return Literal[tuple(sorted(values))]


@cache
def reading_schema(view: str) -> type[BaseModel]:
    """Response schema for one view. Zone, level and side enums are the view's sector map values."""
    found = regions_for(view)
    zones = {zone if zone in LONGITUDINAL_ZONES else PRINTED_LABEL[zone] for zone in (r.zone for r in found)}
    suffix = view.title().replace("_", "")
    sector = create_model(f"Sector{suffix}", __base__=Strict, zone=(_literal(zones), ...),
                          level=(_literal({r.level for r in found}), ...),
                          image_side=(_literal({r.image_side for r in found}), ...))
    mark = create_model(f"Mark{suffix}", __base__=MarkBase, sectors=(list[sector], ...))

    class Reading(Strict):
        marks: Annotated[list[mark], Field(max_length=60)]

        @model_validator(mode="after")
        def unique_ids(self):
            if len({m.id for m in self.marks}) != len(self.marks):
                raise ValueError("Mark IDs must be unique within a reading")
            return self

    Reading.__name__ = f"Reading{suffix}"
    return Reading


def prompt_sha256() -> str:
    return llm.sha256(PROMPT.read_bytes())


def map_image(cleaned_crop: np.ndarray, view: str) -> np.ndarray:
    """Image 2. SV, axial and urethra: the cleaned crop as is, since the printed zones are the map.
    Coronal and sagittal: the 6 level regions drawn as thin labelled outlines."""
    image = cleaned_crop if cleaned_crop.ndim == 3 else cv.cvtColor(cleaned_crop, cv.COLOR_GRAY2BGR)
    if VIEWS[view].view_type != "longitudinal":
        return image.copy()
    image = image.copy()
    origin = np.array(VIEWS[view].origin)
    for region in regions_for(view):
        polygon = (region.polygon - origin).astype(np.int32)
        cv.polylines(image, [polygon.reshape(-1, 1, 2)], True, MAP_COLOUR, 1, cv.LINE_AA)
        side = f"image {region.image_side}" if region.image_side != "none" else region.zone
        label = f"{region.level}, {side}"
        (w, h), _ = cv.getTextSize(label, cv.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        x, y = polygon.mean(axis=0).astype(int)
        cv.putText(image, label, (int(x - w / 2), int(y + h / 2)), cv.FONT_HERSHEY_SIMPLEX, 0.4, MAP_COLOUR, 1,
                   cv.LINE_AA)
    return image


def _png(image: np.ndarray) -> bytes:
    ok, data = cv.imencode(".png", image)
    if not ok:
        raise ValueError("PNG encoding failed")
    return data.tobytes()


def _prompt(view: str) -> str:
    v = VIEWS[view]
    return PROMPT.read_text() + f"\n\nView: {view} ({v.view_type}, level {v.level}).\n"


def _images(case_out: Path, view: str) -> tuple[bytes, bytes]:
    """Image 1 and image 2 as sent: the original crop and the cleaned crop over the map."""
    views_dir = Path(case_out) / "preprocess/views" / view
    original = (views_dir / "original.png").read_bytes()
    cleaned = cv.imread(str(views_dir / "cleaned.png"), cv.IMREAD_COLOR)
    if cleaned is None:
        raise FileNotFoundError(views_dir / "cleaned.png")
    return original, _png(map_image(cleaned, view))


def _prepare(case_out: Path, view: str) -> dict:
    """Request body for one view; saves the map image that is sent."""
    original, map_png = _images(case_out, view)
    out = Path(case_out) / "gemini" / view
    out.mkdir(parents=True, exist_ok=True)
    (out / "map.png").write_bytes(map_png)
    parts = [{"text": _prompt(view)}, {"text": "Image 1: original colour crop"}, llm.image_part(original),
             {"text": "Image 2: cleaned crop over the coloured sector map"}, llm.image_part(map_png)]
    return llm.request_body(parts, reading_schema(view), temperature=1.0)


def to_run_marks(reading, view: str, run: int) -> list[RunMark]:
    marks = []
    for mark in reading.marks:
        closed = mark.kind in CLOSED_KINDS and len(mark.polygon) >= 3
        polygon = normalized_to_crop(mark.polygon, view).tolist() if mark.polygon else None
        marks.append(RunMark(
            run=run, local_id=mark.id, kind=mark.kind, polygon_crop=polygon, closed=closed,
            box_crop=normalized_box_to_crop(mark.box_2d, view).tolist(), text=mark.text or None,
            sectors=[Sector(zone=normalize_zone(s.zone), level=s.level, image_side=s.image_side)
                     for s in mark.sectors]))
    return marks


def _run(case_out: Path, view: str, run: int, body: dict | None, *, client, key, model, replay) -> list[RunMark] | None:
    out = Path(case_out) / "gemini" / view / f"run_{run}"
    schema = reading_schema(view)
    if replay:
        llm.check_saved_request(out, model, _prompt(view), list(_images(case_out, view)))
        reading = llm.replay(out, schema)
    else:
        reading = llm.call(client, model, key, body, schema, out)[0]
    return None if reading is None else to_run_marks(reading, view, run)


def read_case(case_out: Path, views, *, client, key, model: str = models.GEMINI_MODEL, runs: int = 3,
              replay: bool = False, workers: int = 4) -> dict[str, list[list[RunMark] | None]]:
    """All views x runs concurrently. Run k of a view is saved under gemini/<view>/run_<k>/ (k from 1)."""
    bodies = {view: None if replay else _prepare(case_out, view) for view in views}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {view: [pool.submit(_run, case_out, view, k, bodies[view], client=client, key=key, model=model,
                                      replay=replay) for k in range(1, runs + 1)] for view in views}
        return {view: [f.result() for f in found] for view, found in futures.items()}


def read_view(case_out: Path, view: str, *, client, key, model: str = models.GEMINI_MODEL, runs: int = 3,
              replay: bool = False) -> list[list[RunMark] | None]:
    return read_case(case_out, [view], client=client, key=key, model=model, runs=runs, replay=replay)[view]
