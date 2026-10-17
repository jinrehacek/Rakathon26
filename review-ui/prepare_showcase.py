"""Copy one existing artificial scan pair into the ignored, local-only UI showcase."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def source_identity(dictionary: Path, case_id: str) -> dict:
    entries = json.loads(dictionary.read_text())
    if not isinstance(entries, dict):
        raise ValueError("Identity dictionary must be an object keyed by original ID.")
    matches = [
        (original_id, entry) for original_id, entry in entries.items()
        if isinstance(entry, dict) and entry.get("case_id") == case_id
    ]
    if len(matches) != 1:
        raise ValueError("Identity dictionary must contain exactly one match for this source case.")
    original_id, entry = matches[0]
    sources = entry.get("sources")
    if not original_id.strip() or not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("Identity mapping needs a nonempty ID and both paired sources.")
    evidence = []
    for role in ("report", "drawing"):
        matched = [source for source in sources if isinstance(source, dict) and source.get("role") == role]
        if len(matched) != 1 or matched[0].get("id") != original_id or matched[0].get("confident") is not True:
            raise ValueError("Report and drawing IDs must agree confidently before restoring identity.")
        source = matched[0]
        candidates = source.get("candidates", [])
        anchors = [
            candidate for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("id") == original_id
            and candidate.get("basis") == "explicit" and candidate.get("quote") == original_id
            and isinstance(candidate.get("box"), list) and len(candidate["box"]) == 4
            and all(isinstance(value, int) and value >= 0 for value in candidate["box"])
        ] if isinstance(candidates, list) else []
        if not anchors or not isinstance(source.get("sha256"), str) or len(source["sha256"]) != 64:
            raise ValueError("Restored identity requires explicit source quotations, boxes and hashes.")
        evidence.append({
            "source": role, "sha256": source["sha256"],
            "quotation": anchors[0]["quote"], "box": anchors[0]["box"],
            "coordinateFrame": "original source scan before preprocessing",
        })
    return {"originalId": original_id, "sourceCaseId": case_id, "basis": "explicit", "evidence": evidence}


def prepare(pair: Path, analysis: Path, report_text: Path, output: Path, *, dictionary: Path | None = None) -> dict:
    pair = pair.resolve()
    manifest = json.loads((pair.parent / "manifest.json").read_text())
    expected = {role: f"{pair.name}/{role}.jpg" for role in ("report", "drawing")}
    if manifest.get("cases", {}).get(pair.name) != expected:
        raise ValueError("Select a paired case directory listed in its batch manifest.")
    if manifest.get("data_scope") != "artificial":
        raise ValueError("This showcase accepts artificial hackathon data only.")
    raw = json.loads(analysis.read_text())
    legacy = raw.get("mode") == "fixture" and isinstance(raw.get("response"), dict)
    prefilled = (
        raw.get("mode") == "synthetic"
        and raw.get("schema_version") == "doctor-review-showcase-v1"
        and isinstance(raw.get("lesions"), list)
        and bool(raw["lesions"])
    )
    if not legacy and not prefilled:
        raise ValueError("The showcase requires a supported, explicitly synthetic analysis fixture.")
    identity = source_identity(dictionary, pair.name) if dictionary is not None else None
    text = report_text.read_bytes()
    expected_hash = raw.get("report_sha256") if prefilled else raw.get("for_text_sha256")
    if hashlib.sha256(text).hexdigest() != expected_hash:
        raise ValueError("Fixture report text does not match its analysis hash.")
    for role in expected:
        source = pair / f"{role}.jpg"
        if source.is_symlink() or not source.is_file() or not source.read_bytes().startswith(b"\xff\xd8\xff"):
            raise ValueError("Both paired sources must be regular JPEG files.")
    ignored = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", str(output) + "/"],
        capture_output=True, check=False,
    )
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", str(output)],
        capture_output=True, check=False,
    )
    if ignored.returncode or tracked.returncode or tracked.stdout or output.is_symlink():
        raise ValueError("Local showcase data must be ignored, untracked and not symlinked.")
    output.mkdir(mode=0o700, exist_ok=True)
    config = {
        "mode": "showcase",
        "caseId": f"showcase-{pair.name}",
        "sourceCaseId": pair.name,
        "sourceBinding": "showcase-unlinked",
        "analysisUrl": ".local-data/analysis.json",
        "reportTextUrl": ".local-data/analysis-report.txt",
        "sources": {},
    }
    if identity is not None:
        config["sourceIdentity"] = identity
    if legacy:
        config["demoAssignments"] = {
            "focus-a": ["pzpl_base_ls", "pzpl_mid_ls"],
            "focus-b": ["pza_apex_rs"],
        }
    for role in expected:
        target = output / f"{role}.jpg"
        if target.is_symlink():
            raise ValueError("Local showcase targets must not be symlinks.")
        shutil.copyfile(pair / f"{role}.jpg", target)
        target.chmod(0o600)
        config["sources"][role] = {
            "url": f".local-data/{role}.jpg",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
    for name, data in (("analysis.json", analysis.read_bytes()), ("analysis-report.txt", text)):
        target = output / name
        if target.is_symlink():
            raise ValueError("Local showcase targets must not be symlinks.")
        target.write_bytes(data)
        target.chmod(0o600)
    target = output / "case.json"
    if target.is_symlink():
        raise ValueError("Local showcase targets must not be symlinks.")
    target.write_text(json.dumps(config, indent=2) + "\n")
    target.chmod(0o600)
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", type=Path, required=True, help="A case folder with report.jpg and drawing.jpg.")
    parser.add_argument("--analysis", type=Path, default=HERE / "fixtures/prefilled-analysis.json")
    parser.add_argument("--report-text", type=Path, default=HERE / "fixtures/prefilled-report.txt")
    parser.add_argument("--dictionary", type=Path, default=ROOT / "preprocess/.preprocess-private/dictionary.json",
                        help="Local preprocessing ID dictionary; only this case's identity is copied.")
    parser.add_argument("--showcase", action="store_true", required=True,
                        help="Acknowledge that the fixture predictions are unrelated to these scans.")
    args = parser.parse_args()
    try:
        prepare(args.pair, args.analysis, args.report_text, HERE / ".local-data", dictionary=args.dictionary)
        print("Local Rakathon scan showcase prepared. Predictions are illustrative, not scan-derived.")
        print("Reload http://127.0.0.1:8766/")
    except ValueError as error:
        print(str(error) if not isinstance(error, json.JSONDecodeError) else "Invalid local JSON input.",
              file=sys.stderr)
        sys.exit(2)
    except OSError:
        print("Cannot read or prepare the local showcase files.", file=sys.stderr)
        sys.exit(2)
