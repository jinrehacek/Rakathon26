"""Copy a pinned, already-computed assessment into the ignored review web root.

Local file copies only. No extraction, model calls, or preprocessing runs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def prepare(paths, output, source_root, label):
    output = output.resolve()
    repo = Path(__file__).resolve().parents[1]
    if not output.is_relative_to(repo / "review-ui/.local-data"):
        raise ValueError("Output must stay under review-ui/.local-data.")
    subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(output) + "/"], check=True)
    entries = []
    for path in paths:
        raw = json.loads(path.read_bytes())
        if raw.get("schema_version") != "combined-1":
            raise ValueError("Expected combined-1.")
        case_id = raw["case_id"]
        if not case_id or Path(case_id).name != case_id or case_id in {".", ".."}:
            raise ValueError("Unsafe case ID.")
        files = {"combined.json": path.read_bytes()}
        for role in ("report", "drawing"):
            pin = raw["inputs"][role]
            input_path = Path(pin["path"])
            if not input_path.is_absolute():
                input_path = source_root / input_path
            data = input_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != pin["sha256"]:
                raise ValueError("Pinned extraction hash differs.")
            files[role + ".json"] = data
            extracted = json.loads(data)
            source = extracted["document"] if role == "report" else extracted["extraction"]
            scan = Path(source["source_path"])
            if not scan.is_absolute():
                scan = source_root / scan
            scan_bytes = scan.read_bytes()
            if hashlib.sha256(scan_bytes).hexdigest() != source["source_sha256"]:
                raise ValueError("Pinned scan hash differs.")
            files[role + ".jpg"] = scan_bytes
        target = output / case_id
        if target.exists():
            raise ValueError("Choose a new output folder; prepared cases are never overwritten.")
        target.mkdir(parents=True, mode=0o700)
        for name, data in files.items():
            (target / name).write_bytes(data)
            (target / name).chmod(0o600)
        base = "/" + target.relative_to(repo / "review-ui").as_posix()
        config = {"mode": "combined", "sourceBinding": "pinned-combined", "caseId": case_id, "label": label,
                  "analysisUrl": base + "/combined.json", "reportUrl": base + "/report.json", "drawingUrl": base + "/drawing.json"}
        config_path = target / "case.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        config_path.chmod(0o600)
        entries.append({"url": base + "/case.json", "label": f"{case_id[:8]} · {label}"})
    index = output / "cases.json"
    index.write_text(json.dumps(entries, indent=2) + "\n")
    index.chmod(0o600)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("combined", nargs="+", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / ".local-data/combined")
    parser.add_argument("--label", required=True, help="Origin and limitations shown to the reviewer, e.g. manual report reference + extracted drawing.")
    args = parser.parse_args()
    print(prepare(args.combined, args.output, args.source_root.resolve(), args.label))
