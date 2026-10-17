"""Loopback-only upload and human review for the artificial-data JPG MVP."""

import argparse
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from functools import partial
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from uuid import uuid4
import warnings
import zipfile

from PIL import Image, UnidentifiedImageError


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("jpg_pipeline", HERE / "preprocess.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
MAX_UPLOAD = 128 * 1024 * 1024
MAX_FILE = 25 * 1024 * 1024
MAX_FILES = 150


class InputError(ValueError):
    pass


class BusyError(RuntimeError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded_folder(path: Path) -> None:
    ignored = subprocess.run(
        ["git", "-C", str(HERE), "check-ignore", "-q", str(path) + "/"],
        capture_output=True, check=False,
    )
    tracked = subprocess.run(
        ["git", "-C", str(HERE), "ls-files", "--", str(path)],
        capture_output=True, check=False,
    )
    if ignored.returncode or tracked.returncode or tracked.stdout or path.is_symlink():
        raise RuntimeError("Local UI storage must be ignored, untracked and not symlinked.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


class App:
    def __init__(self, root: Path = HERE):
        self.root = root.resolve()
        self.private = self.root / ".preprocess-private" / "ui"
        guarded_folder(self.private)
        self.path = self.private / "state.json"
        if self.path.is_symlink():
            raise RuntimeError("UI state must not be a symlink.")
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"batches": []}
        self.lock = threading.RLock()
        self.busy = False
        self.progress = ""
        self.error = None
        self.worker = None

    def snapshot(self) -> dict:
        with self.lock:
            batches = json.loads(json.dumps(self.data["batches"]))
            for batch in batches:
                batch.pop("inputFolder", None)
                batch.pop("bundle", None)
                batch.pop("inputs", None)
                for case in batch["cases"]:
                    for source in case["sources"].values():
                        for field in ("originalPath", "redactedPath", "sourceSha256", "redactedSha256"):
                            source.pop(field, None)
            return {"busy": self.busy, "progress": self.progress, "error": self.error, "batches": batches}

    def start(self, files: list[tuple[str, bytes]]) -> None:
        with self.lock:
            if self.busy:
                raise BusyError("A batch is already processing. Wait for it to finish.")
            if not 1 <= len(files) <= MAX_FILES:
                raise InputError(f"Choose between 1 and {MAX_FILES} JPG files.")
            for name, content in files:
                if Path(name).suffix.lower() not in {".jpg", ".jpeg"} or not 0 < len(content) <= MAX_FILE:
                    raise InputError("Only nonempty JPG/JPEG files up to 25 MB each are supported.")
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", Image.DecompressionBombWarning)
                        with Image.open(BytesIO(content)) as image:
                            if image.format != "JPEG" or image.width * image.height > 40_000_000:
                                raise InputError("Use JPEG images no larger than 40 megapixels.")
                            image.verify()
                except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                    raise InputError("An uploaded file is not a readable JPEG. Nothing was processed.") from None
            batch_id = "ui-" + str(uuid4())
            folder = self.private / batch_id
            folder.mkdir(mode=0o700)
            inputs = []
            for name, content in files:
                identifier = str(uuid4())
                target = folder / f"{identifier}.jpg"
                target.write_bytes(content)
                target.chmod(0o600)
                inputs.append({"id": identifier, "name": Path(name.replace("\\", "/")).name, "path": str(target)})
            self.busy = True
            self.error = None
            self.progress = f"Running local OCR on {len(files)} JPGs. Larger batches can take several minutes."
            self.worker = threading.Thread(target=self.process, args=(batch_id, folder, inputs), daemon=True)
            self.worker.start()

    def process(self, batch_id: str, folder: Path, inputs: list[dict]) -> None:
        try:
            try:
                result = pipeline.run(folder)
            except pipeline.NoPairsError as error:
                result = {"pairs": 0, "issues": error.issues, "bundle": None}
            batch = self.collect(batch_id, folder, inputs, result)
            with self.lock:
                self.data["batches"].insert(0, batch)
                try:
                    pipeline.write_json(self.path, self.data)
                except OSError:
                    self.data["batches"].remove(batch)
                    raise
                self.progress = f"Finished: {batch['pairs']} pairs; {len(batch['excluded'])} inputs held."
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            with self.lock:
                self.error = "Preprocessing failed. Uploaded originals remain local. Check Tesseract and private diagnostics; do not release this batch."
                self.progress = "Processing failed."
        finally:
            with self.lock:
                self.busy = False

    def collect(self, batch_id: str, folder: Path, inputs: list[dict], result: dict) -> dict:
        batch = {
            "id": batch_id, "createdAt": datetime.now(timezone.utc).isoformat(),
            "inputCount": len(inputs), "pairs": result["pairs"], "issueCounts": result["issues"],
            "inputFolder": str(folder), "inputs": inputs, "bundle": result["bundle"], "cases": [], "excluded": [],
        }
        used = set()
        if result["bundle"]:
            bundle = Path(result["bundle"]).resolve()
            manifest = json.loads((bundle / "manifest.json").read_text())
            mapping = json.loads((self.root / ".preprocess-private" / "dictionary.json").read_text())
            for case_id, paths in manifest["cases"].items():
                matches = [(name, entry) for name, entry in mapping.items() if entry["case_id"] == case_id]
                if len(matches) != 1:
                    raise ValueError("Ambiguous private case association.")
                original_id, entry = matches[0]
                case = {
                    "id": case_id, "originalId": original_id, "decision": "pending", "note": "",
                    "checks": {"pairing": False, "redaction": False, "quality": False}, "sources": {},
                }
                for role in ("report", "drawing"):
                    candidates = [item for item in entry["sources"] if item["role"] == role]
                    if len(candidates) != 1:
                        raise ValueError("Expected exactly one source for each document role.")
                    source = candidates[0]
                    original = Path(source["source"]).resolve()
                    cleaned = (bundle / paths[role]).resolve()
                    if original not in {Path(item["path"]) for item in inputs} or not cleaned.is_relative_to(bundle):
                        raise ValueError("Sources do not belong to the uploaded batch.")
                    if digest(original) != source["sha256"]:
                        raise ValueError("Original changed during processing.")
                    used.add(str(original))
                    case["sources"][role] = {
                        "originalPath": str(original), "redactedPath": str(cleaned),
                        "sourceSha256": source["sha256"], "redactedSha256": digest(cleaned),
                        "rotation": source["rotation"],
                        "originalUrl": f"/api/image/{batch_id}/{case_id}/{role}/original",
                        "redactedUrl": f"/api/image/{batch_id}/{case_id}/{role}/redacted",
                    }
                batch["cases"].append(case)
        for item in inputs:
            if item["path"] not in used:
                batch["excluded"].append({
                    "id": item["id"], "name": item["name"],
                    "reason": "Not confidently paired. ID, role, duplicate/conflict or OCR quality needs local review.",
                    "originalUrl": f"/api/input/{batch_id}/{item['id']}",
                })
        return batch

    def batch(self, identifier: str) -> dict:
        matches = [batch for batch in self.data["batches"] if batch["id"] == identifier]
        if len(matches) != 1:
            raise InputError("Unknown batch.")
        return matches[0]

    def source_path(self, batch: dict, source: dict, kind: str) -> Path:
        path = Path(source[f"{kind}Path"])
        base = Path(batch["inputFolder"]) if kind == "original" else Path(batch["bundle"])
        if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()) or not path.is_file():
            raise InputError("Image is missing or outside this batch.")
        return path

    def decide(self, request: dict) -> None:
        with self.lock:
            if self.busy:
                raise BusyError("Wait until processing has finished.")
            batch = self.batch(request.get("batchId"))
            case = next((case for case in batch["cases"] if case["id"] == request.get("caseId")), None)
            decision, checks, note = request.get("decision"), request.get("checks"), request.get("note")
            if not case or decision not in {"approved", "held"} or not isinstance(note, str) or len(note) > 4000:
                raise InputError("Choose an existing case and a valid review decision.")
            if not isinstance(checks, dict) or set(checks) != {"pairing", "redaction", "quality"} or any(type(value) is not bool for value in checks.values()):
                raise InputError("All three review checks must be explicit yes/no values.")
            if decision == "approved" and not all(checks.values()):
                raise InputError("Verify pairing, identifier coverage and image quality before approval.")
            if decision == "held" and not note.strip():
                raise InputError("Explain why this case is held.")
            if decision == "approved":
                self.verify(batch, case)
            previous = dict(case)
            case.update(decision=decision, checks=checks, note=note.strip(), reviewedAt=datetime.now(timezone.utc).isoformat())
            try:
                pipeline.write_json(self.path, self.data)
            except OSError:
                case.clear()
                case.update(previous)
                raise

    def verify(self, batch: dict, case: dict) -> None:
        for source in case["sources"].values():
            for kind, hash_field in (("original", "sourceSha256"), ("redacted", "redactedSha256")):
                if digest(self.source_path(batch, source, kind)) != source[hash_field]:
                    raise InputError("An image changed after processing. Reprocess and review it before release.")

    def release(self, identifier: str) -> Path:
        with self.lock:
            if self.busy:
                raise BusyError("Wait until processing has finished.")
            batch = self.batch(identifier)
            cases = [case for case in batch["cases"] if case["decision"] in {"pending", "approved"}]
            if not cases:
                raise InputError("No confident, unheld pairs to download.")
            for case in cases:
                if case["decision"] == "approved" and not all(case["checks"].values()):
                    raise InputError("An approved case has incomplete review checks.")
                self.verify(batch, case)
            target = self.private / f"release-{identifier}.zip"
            if target.is_symlink():
                raise InputError("Release destination must not be a symlink.")
            reviewed = sum(case["decision"] == "approved" for case in cases)
            status = "human_reviewed" if reviewed == len(cases) else "partially_reviewed" if reviewed else "not_reviewed"
            manifest = {
                "schema_version": "preprocess-handoff-v1", "data_scope": "artificial", "review_status": status,
                "privacy_note": "Pseudonymized Rakathon-ID masking only; neither OCR nor optional human review guarantees complete de-identification.",
                "cases": {case["id"]: {role: f"{case['id']}/{role}.jpg" for role in ("report", "drawing")} for case in cases},
                "case_review": {
                    case["id"]: {"status": "human_reviewed" if case["decision"] == "approved" else "not_reviewed"}
                    for case in cases
                },
                "output_sha256": {
                    case["id"]: {role: source["redactedSha256"] for role, source in case["sources"].items()}
                    for case in cases
                },
            }
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
                target.chmod(0o600)
                for case in cases:
                    for role, source in case["sources"].items():
                        archive.write(self.source_path(batch, source, "redacted"), manifest["cases"][case["id"]][role])
                archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            return target


def upload_parts(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    if not content_type.startswith("multipart/form-data;") or "\r" in content_type or "\n" in content_type:
        raise InputError("Upload JPGs using the file picker.")
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    if not message.is_multipart() or message.defects:
        raise InputError("Invalid multipart upload.")
    files, confirmed = [], False
    for part in message.iter_parts():
        field = part.get_param("name", header="content-disposition")
        content = part.get_payload(decode=True)
        if field == "artificial_data" and content == b"yes":
            confirmed = True
        elif field == "files" and part.get_filename() and isinstance(content, bytes):
            files.append((part.get_filename(), content))
        else:
            raise InputError("Unexpected upload field.")
    if not confirmed:
        raise InputError("Confirm these are artificial hackathon scans, not production records.")
    return files


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, app: App, **kwargs):
        self.app = app
        super().__init__(*args, **kwargs)

    def log_message(self, *_args) -> None:
        # URLs can contain private case identifiers; do not log request paths.
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def respond(self, status: int, value: dict) -> None:
        content = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def trusted(self, mutation: bool = False) -> bool:
        host = f"127.0.0.1:{self.server.server_port}"
        return self.headers.get("Host") == host and (
            not mutation or self.headers.get("Origin") == f"http://{host}"
        )

    def send_file(self, path: Path, content_type: str, download: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        with path.open("rb") as stream:
            while content := stream.read(64 * 1024):
                self.wfile.write(content)

    def do_GET(self) -> None:
        if not self.trusted():
            self.respond(403, {"error": "Use the local 127.0.0.1 address."})
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/state":
                self.respond(200, self.app.snapshot())
            elif path in {"/", "/app.js", "/style.css"}:
                name, mime = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                }[path]
                self.send_file(HERE / "web" / name, mime)
            elif path.startswith("/api/image/"):
                _, _, _, batch_id, case_id, role, kind = path.split("/")
                if role not in {"report", "drawing"} or kind not in {"original", "redacted"}:
                    raise InputError("Unknown image.")
                with self.app.lock:
                    batch = self.app.batch(batch_id)
                    case = next((case for case in batch["cases"] if case["id"] == case_id), None)
                    if not case:
                        raise InputError("Unknown case.")
                    self.send_file(self.app.source_path(batch, case["sources"][role], kind), "image/jpeg")
            elif path.startswith("/api/input/"):
                _, _, _, batch_id, input_id = path.split("/")
                batch = self.app.batch(batch_id)
                item = next((item for item in batch["inputs"] if item["id"] == input_id), None)
                if not item:
                    raise InputError("Unknown input.")
                self.send_file(self.app.source_path(batch, {"originalPath": item["path"]}, "original"), "image/jpeg")
            elif path.startswith("/api/release/"):
                identifier = path.removeprefix("/api/release/")
                self.send_file(self.app.release(identifier), "application/zip", "ready-pairs.zip")
            else:
                self.respond(404, {"error": "Not found."})
        except BusyError as error:
            self.respond(409, {"error": str(error)})
        except InputError as error:
            self.respond(400, {"error": str(error)})
        except (OSError, ValueError, KeyError):
            self.respond(500, {"error": "Cannot read local batch data. Reprocess or check private storage locally."})

    def do_POST(self) -> None:
        if not self.trusted(mutation=True):
            self.respond(403, {"error": "Only same-origin local requests are allowed."})
            return
        try:
            path = urlsplit(self.path).path
            if path not in {"/api/upload", "/api/decision"}:
                self.respond(404, {"error": "Not found."})
                return
            length = int(self.headers.get("Content-Length", "0"))
            limit = MAX_UPLOAD if path == "/api/upload" else 16 * 1024
            if not 0 < length <= limit:
                self.respond(413, {"error": "Upload too large (128 MB batch limit) or empty request."})
                return
            content = self.rfile.read(length)
            if len(content) != length:
                raise InputError("Upload interrupted.")
            content_type = self.headers.get("Content-Type", "")
            if path == "/api/upload":
                self.app.start(upload_parts(content_type, content))
                self.respond(202, {"accepted": True})
            else:
                if content_type.split(";")[0] != "application/json":
                    raise InputError("Review decisions must be JSON.")
                request = json.loads(content)
                if not isinstance(request, dict):
                    raise InputError("Invalid review decision.")
                self.app.decide(request)
                self.respond(200, {"saved": True})
        except BusyError as error:
            self.respond(409, {"error": str(error)})
        except InputError as error:
            self.respond(400, {"error": str(error)})
        except (ValueError, UnicodeError):
            self.respond(400, {"error": "Malformed request."})
        except OSError:
            self.respond(500, {"error": "Cannot save local data. No approval or release is guaranteed; check disk/storage."})


def make_server(app: App, port: int = 8767) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, app=app))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    try:
        server = make_server(App(), args.port)
        print(f"Local preprocessing UI: http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
    except (OSError, ValueError, RuntimeError):
        print("Cannot start the preprocessing UI. Check ignored storage and whether the port is already in use.", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        server.server_close()
