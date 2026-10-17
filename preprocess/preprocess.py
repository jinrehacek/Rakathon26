"""JPG-only artificial-data MVP: local OCR, pairing, black masks, and JPG output."""

import argparse
from collections import Counter, defaultdict
import csv
from difflib import SequenceMatcher
import hashlib
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

from PIL import Image, ImageOps


HERE = Path(__file__).resolve().parent
ID_PATTERN = re.compile(r"(?<!\w)rakathon\s*([0-9]+)(?!\w)", re.IGNORECASE)


class NoPairsError(RuntimeError):
    def __init__(self, issues: dict):
        self.issues = issues
        super().__init__("No confident pairs found; see the private last-run.json locally.")


def ocr(image: Image.Image, psm: int) -> list[dict]:
    with BytesIO() as buffer:
        image.save(buffer, format="PNG")
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", str(psm), "tsv"],
            input=buffer.getvalue(), capture_output=True, timeout=45, check=False,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    if result.returncode:
        raise RuntimeError("Local Tesseract failed; check installation/language data.")
    rows = csv.DictReader(StringIO(result.stdout.decode()), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [
        {
            "text": row["text"], "confidence": float(row["conf"]),
            "box": (
                int(row["left"]), int(row["top"]),
                int(row["left"]) + int(row["width"]),
                int(row["top"]) + int(row["height"]),
            ),
            "line": tuple(row[key] for key in ("block_num", "par_num", "line_num")),
        }
        for row in rows if row["level"] == "5" and row["text"].strip()
    ]


def identify(words: list[dict]) -> list[dict]:
    found = []
    for index, word in enumerate(words):
        members = [word]
        text = word["text"]
        if text.casefold() == "rakathon" and index + 1 < len(words):
            following = words[index + 1]
            gap = following["box"][0] - word["box"][2]
            if (
                following["line"] == word["line"]
                and 0 <= gap <= word["box"][3] - word["box"][1]
                and re.fullmatch(r"[0-9]+", following["text"])
            ):
                members.append(following)
                text += following["text"]
        match = ID_PATTERN.fullmatch(text.strip(".,:;()[]"))
        if match:
            found.append({
                "id": "Rakathon" + match[1],
                "quote": " ".join(member["text"] for member in members),
                "basis": "explicit",
                "confidence": min(member["confidence"] for member in members),
                "box": (
                    min(member["box"][0] for member in members),
                    min(member["box"][1] for member in members),
                    max(member["box"][2] for member in members),
                    max(member["box"][3] for member in members),
                ),
            })
    return found


def role(words: list[dict]) -> str | None:
    labels = {
        word["text"].casefold().strip(".,:;")
        for word in words if word["confidence"] >= 45
    }
    drawing = {"base", "mid", "apex"} <= labels or bool(labels & {"pi-rads", "pirads"})
    report = bool(labels & {"závěr", "zaver", "mikroskopicky", "mikroskopie"})
    if drawing:
        return "drawing"
    return "report" if report else None


def read_region(image: Image.Image, box: tuple, width: int, psm: int) -> list[dict]:
    with image.crop(box) as crop:
        height = max(1, round(crop.height * width / crop.width))
        with crop.resize((width, height)) as scaled:
            words = ocr(scaled, psm)
        for word in words:
            left, top, right, bottom = word["box"]
            word["box"] = (
                box[0] + round(left * crop.width / width),
                box[1] + round(top * crop.height / height),
                box[0] + round(right * crop.width / width),
                box[1] + round(bottom * crop.height / height),
            )
    return words


def focused_identifiers(image: Image.Image, words: list[dict]) -> list[dict]:
    anchors = []
    for word in words:
        letters = re.sub("[^a-z]", "", word["text"].casefold())
        similarity = SequenceMatcher(None, letters, "rakathon").ratio()
        if similarity >= .7:
            anchors.append((similarity, word["box"]))
    candidates, seen = [], set()
    for _, (left, top, right, bottom) in sorted(anchors, reverse=True):
        height = bottom - top
        box = (
            max(0, left - height), max(0, top - height // 2),
            min(image.width, right + height * 5), min(image.height, bottom + height // 2),
        )
        if height <= 0 or box in seen or box[2] <= box[0] or box[3] <= box[1]:
            continue
        seen.add(box)
        for factor in (2, 3):
            for psm in (7, 6):
                # Similarity only locates a crop. The accepted ID must be read
                # literally by OCR; never repair letters/digits or guess an ID.
                found = identify(read_region(image, box, (box[2] - box[0]) * factor, psm))
                for candidate in found:
                    candidate["method"] = f"focused_line_{factor}x_psm{psm}"
                candidates.extend(found)
        if len(seen) >= 6:
            break
    return candidates


def analyze(image: Image.Image) -> dict:
    best = {"id": None, "role": None, "candidates": [], "confident": False, "rotation": 0}
    for angle in (0, 90, 180, 270):
        with image.rotate(-angle, expand=True) as upright:
            page = (0, 0, upright.width, upright.height)
            band = (0, upright.height * 3 // 4, upright.width, upright.height)
            words = read_region(upright, page, min(upright.width, 2200), 11)
            kinds = {role(words)} - {None}
            bottom = read_region(upright, band, max(upright.width, 2600), 6)
            candidates = identify(words) + identify(bottom)
            words.extend(bottom)

            def ready() -> bool:
                return len(kinds) == 1 and len({item["id"] for item in candidates}) == 1 and any(
                    item["confidence"] >= 70 for item in candidates
                )

            if not ready() and len({item["id"] for item in candidates}) <= 1:
                dense = read_region(upright, page, min(upright.width, 2200), 6)
                kinds.update({role(dense)} - {None})
                candidates.extend(identify(dense))
                words.extend(dense)
                if not ready():
                    enlarged = read_region(upright, band, max(upright.width, 3200), 6)
                    candidates.extend(identify(enlarged))
                    words.extend(enlarged)
                if not ready() and len(kinds) == 1:
                    candidates.extend(focused_identifiers(upright, words))
            values = {candidate["id"] for candidate in candidates}
            result = {
                "role": next(iter(kinds)) if len(kinds) == 1 else None, "rotation": angle,
                "candidates": candidates, "id": next(iter(values)) if len(values) == 1 else None,
                "confident": ready(), "coordinate_frame": "upright_scan_after_exif_and_rotation",
            }
            if result["role"] and candidates:
                return result
            if candidates and not best["candidates"]:
                best = result
    return best


def load(path: Path) -> Image.Image:
    with Image.open(path) as source:
        if source.getexif().get(274, 1) not in (1, 3, 6, 8):
            raise ValueError("Mirrored EXIF orientation is not supported.")
        with ImageOps.exif_transpose(source) as oriented:
            return oriented.convert("RGB")


def redacted(image: Image.Image, boxes: list[tuple]) -> Image.Image:
    result = Image.new("RGB", image.size)
    result.paste(image)
    for left, top, right, bottom in boxes:
        result.paste("black", (
            max(0, left - 12), max(0, top - 12),
            min(image.width, right + 12), min(image.height, bottom + 12),
        ))
    return result


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    temporary.replace(path)


def run(folder: Path) -> dict:
    if not folder.is_dir():
        raise ValueError("Input must be a local JPG folder.")
    if not shutil.which("tesseract"):
        raise RuntimeError("Install local Tesseract before running this script.")
    private = HERE / ".preprocess-private"
    exports = HERE / ".preprocess-exports"
    for directory in (private, exports):
        ignored = subprocess.run(
            ["git", "-C", str(HERE), "check-ignore", "-q", str(directory) + "/"],
            capture_output=True, check=False,
        )
        tracked = subprocess.run(
            ["git", "-C", str(HERE), "ls-files", "--", str(directory)],
            capture_output=True, check=False,
        )
        if ignored.returncode or tracked.returncode or tracked.stdout or directory.is_symlink():
            raise RuntimeError("Private/output folders must be ignored and untracked.")
        directory.mkdir(mode=0o700, exist_ok=True)
    mapping_file = private / "dictionary.json"
    mapping = json.loads(mapping_file.read_text()) if mapping_file.exists() else {}
    batch = exports / f"batch-{uuid4()}"
    groups = defaultdict(list)
    issues = Counter()
    records = []
    inputs = sorted(path for path in folder.rglob("*") if path.suffix.lower() in {".jpg", ".jpeg"})
    if not inputs:
        raise ValueError("No JPG inputs found.")
    for index, path in enumerate(inputs, 1):
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with load(path) as image:
                record = analyze(image)
            record.update(source=str(path.resolve()), sha256=digest)
            records.append(record)
            # Conflicting/weak occurrences must still prevent duplicate pairing.
            for identifier in {item["id"] for item in record["candidates"]}:
                groups[identifier].append(record)
            if not record["confident"]:
                issues["unreadable_or_uncertain_id"] += 1
        except (OSError, ValueError, subprocess.TimeoutExpired):
            issues["unreadable_or_ocr_timeout"] += 1
        print(f"Read {index}/{len(inputs)} JPGs", file=sys.stderr, flush=True)
    manifest = {
        "schema_version": "preprocess-handoff-v1",
        "review_status": "not_reviewed", "data_scope": "artificial", "cases": {}, "output_sha256": {},
    }
    try:
        batch.mkdir(mode=0o700)
        for identifier, members in groups.items():
            if (
                len(members) != 2 or {member["role"] for member in members} != {"report", "drawing"}
                or not all(member["confident"] and member["id"] == identifier for member in members)
            ):
                issues["unpaired_or_ambiguous_id"] += 1
                continue
            case_id = mapping.get(identifier, {}).get("case_id", str(uuid4()))
            case_folder = batch / case_id
            if any(hashlib.sha256(Path(member["source"]).read_bytes()).hexdigest() != member["sha256"]
                   for member in members):
                issues["source_changed"] += 1
                continue
            case_folder.mkdir(mode=0o700)
            for member in members:
                with load(Path(member["source"])) as original:
                    with original.rotate(-member["rotation"], expand=True) as upright:
                        with redacted(upright, [item["box"] for item in member["candidates"]]) as output:
                            output.save(case_folder / f"{member['role']}.jpg",
                                        quality=95, subsampling=0, exif=b"", icc_profile=None)
            mapping[identifier] = {"case_id": case_id, "sources": members}
            manifest["cases"][case_id] = {
                "report": f"{case_id}/report.jpg", "drawing": f"{case_id}/drawing.jpg",
            }
            manifest["output_sha256"][case_id] = {
                role: hashlib.sha256((case_folder / f"{role}.jpg").read_bytes()).hexdigest()
                for role in ("report", "drawing")
            }
        write_json(mapping_file, mapping)
        write_json(private / "last-run.json", {"files": records, "issues": dict(issues)})
        if not manifest["cases"]:
            batch.rmdir()
            raise NoPairsError(dict(issues))
        write_json(batch / "manifest.json", manifest)
    except (OSError, ValueError, RuntimeError):
        if batch.exists():
            shutil.rmtree(batch)
        raise
    return {"pairs": len(manifest["cases"]), "issues": dict(issues), "bundle": str(batch)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--artificial-data", action="store_true", required=True,
                        help="This unreviewed MVP is for artificial hackathon scans only.")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.folder), sort_keys=True))
    except (OSError, ValueError, RuntimeError) as error:
        # Source filenames/OCR text may occur in library exceptions: never echo them.
        print("Preprocessing failed. Check local inputs, Tesseract, and private diagnostics.",
              file=sys.stderr)
        sys.exit(2)
