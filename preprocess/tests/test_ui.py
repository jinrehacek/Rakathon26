import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from PIL import Image


spec = importlib.util.spec_from_file_location("local_preprocess_ui", Path(__file__).resolve().parents[1] / "ui.py")
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def jpeg() -> bytes:
    with Image.new("RGB", (160, 220), (255, 255, 190)) as image, BytesIO() as output:
        image.save(output, format="JPEG")
        return output.getvalue()


class UiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

        def storage(path):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)

        self.guard = patch.object(ui, "guarded_folder", side_effect=storage)
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.app = ui.App(self.root)

    def batch(self):
        folder = self.app.private / "ui-synthetic"
        folder.mkdir()
        bundle = self.root / ".preprocess-exports" / "batch-synthetic"
        bundle.mkdir(parents=True)
        sources = {}
        for role in ("report", "drawing"):
            original, clean = folder / f"{role}.jpg", bundle / f"{role}.jpg"
            original.write_bytes(jpeg())
            clean.write_bytes(jpeg())
            sources[role] = {
                "originalPath": str(original), "redactedPath": str(clean),
                "sourceSha256": ui.digest(original), "redactedSha256": ui.digest(clean),
                "rotation": 0,
                "originalUrl": f"/api/image/ui-synthetic/case-synthetic/{role}/original",
                "redactedUrl": f"/api/image/ui-synthetic/case-synthetic/{role}/redacted",
            }
        batch = {
            "id": "ui-synthetic", "createdAt": "synthetic", "inputFolder": str(folder),
            "inputs": [], "bundle": str(bundle), "inputCount": 2, "pairs": 1,
            "excluded": [], "issueCounts": {},
            "cases": [{
                "id": "case-synthetic", "originalId": "SYNTHETIC-PRINTED-ID",
                "decision": "pending", "note": "",
                "checks": {"pairing": False, "redaction": False, "quality": False}, "sources": sources,
            }],
        }
        self.app.data["batches"] = [batch]
        return batch

    def decision(self, **extra):
        return {
            "batchId": "ui-synthetic", "caseId": "case-synthetic", "decision": "approved",
            "note": "", "checks": {"pairing": True, "redaction": True, "quality": True}, **extra,
        }

    def test_approval_requires_all_checks_and_hold_requires_reason(self):
        batch = self.batch()
        with self.assertRaises(ui.InputError):
            self.app.decide(self.decision(checks={"pairing": True, "redaction": False, "quality": True}))
        with self.assertRaises(ui.InputError):
            self.app.decide(self.decision(decision="held"))
        with self.assertRaises(ui.InputError):
            self.app.decide(self.decision(checks={"pairing": 1, "redaction": True, "quality": True}))
        self.assertEqual(batch["cases"][0]["decision"], "pending")
        self.app.decide(self.decision(decision="held", note="Synthetic redaction requires another check."))
        self.assertEqual(batch["cases"][0]["decision"], "held")
        self.app.decide(self.decision())
        self.assertEqual(batch["cases"][0]["decision"], "approved")
        restored = ui.App(self.root)
        self.assertEqual(restored.data["batches"][0]["cases"][0]["decision"], "approved")

    def test_approval_write_failure_does_not_create_success_in_memory(self):
        batch = self.batch()
        with patch.object(ui.pipeline, "write_json", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.app.decide(self.decision())
        self.assertEqual(batch["cases"][0]["decision"], "pending")

    def test_release_pending_cases_without_fabricated_review_or_private_association(self):
        batch = self.batch()
        other = {**batch["cases"][0], "id": "held-case", "decision": "held", "note": "Synthetic hold."}
        batch["cases"].append(other)
        target = self.app.release(batch["id"])
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(set(archive.namelist()), {
                "manifest.json", "case-synthetic/report.jpg", "case-synthetic/drawing.jpg",
            })
            manifest = archive.read("manifest.json").decode()
            self.assertNotIn("SYNTHETIC-PRINTED-ID", manifest)
            self.assertNotIn(str(self.root), manifest)
            self.assertNotIn("held-case", manifest)
            data = json.loads(manifest)
            self.assertEqual(data["review_status"], "not_reviewed")
            self.assertEqual(data["case_review"]["case-synthetic"]["status"], "not_reviewed")
            for role in ("report", "drawing"):
                self.assertEqual(data["output_sha256"]["case-synthetic"][role],
                                 hashlib.sha256(archive.read(f"case-synthetic/{role}.jpg")).hexdigest())
        self.assertEqual(batch["cases"][0]["decision"], "pending")
        self.assertEqual(batch["cases"][1]["decision"], "held")

    def test_optional_review_statuses_and_all_held_batches(self):
        batch = self.batch()
        self.app.decide(self.decision())
        with zipfile.ZipFile(self.app.release(batch["id"])) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json"))["review_status"], "human_reviewed")
        other = {**batch["cases"][0], "id": "unreviewed-case", "decision": "pending",
                 "checks": {"pairing": False, "redaction": False, "quality": False}}
        batch["cases"].append(other)
        with zipfile.ZipFile(self.app.release(batch["id"])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["review_status"], "partially_reviewed")
            self.assertEqual(len(manifest["cases"]), 2)
            self.assertEqual(manifest["case_review"]["unreviewed-case"]["status"], "not_reviewed")
        for case in batch["cases"]:
            case["decision"] = "held"
        with self.assertRaises(ui.InputError):
            self.app.release(batch["id"])

    def test_changed_image_blocks_approval_and_release(self):
        batch = self.batch()
        self.app.decide(self.decision())
        source = batch["cases"][0]["sources"]["report"]
        Path(source["originalPath"]).write_bytes(b"synthetic changed input")
        with self.assertRaises(ui.InputError):
            self.app.decide(self.decision())
        with self.assertRaises(ui.InputError):
            self.app.release(batch["id"])
        self.app.decide(self.decision(decision="held", note="Synthetic source changed; reprocess before release."))
        self.assertEqual(batch["cases"][0]["decision"], "held")

    def test_private_paths_are_not_returned_in_browser_state(self):
        self.batch()
        state = self.app.snapshot()
        self.assertNotIn(str(self.root), json.dumps(state))
        self.assertNotIn("originalPath", json.dumps(state))
        self.assertEqual(state["batches"][0]["cases"][0]["originalId"], "SYNTHETIC-PRINTED-ID")
        state["batches"][0]["cases"][0]["decision"] = "approved"
        self.assertEqual(self.app.data["batches"][0]["cases"][0]["decision"], "pending")

    def test_image_path_escapes_and_symlinks_are_rejected(self):
        batch = self.batch()
        outside = self.root / "outside.jpg"
        outside.write_bytes(jpeg())
        with self.assertRaises(ui.InputError):
            self.app.source_path(batch, {"originalPath": str(outside)}, "original")
        link = Path(batch["inputFolder"]) / "link.jpg"
        link.symlink_to(outside)
        with self.assertRaises(ui.InputError):
            self.app.source_path(batch, {"originalPath": str(link)}, "original")

    def test_upload_accepts_only_valid_jpegs(self):
        for files in ([], [("fake.jpg", b"not jpeg")], [("image.png", jpeg())]):
            with self.subTest(files=len(files)), self.assertRaises(ui.InputError):
                self.app.start(files)
        self.assertFalse(self.app.busy)

    def test_real_pipeline_and_ui_keep_stable_id_and_original_bytes(self):
        data = jpeg()
        original_hash = hashlib.sha256(data).hexdigest()
        git_result = type("Result", (), {"returncode": 0, "stdout": b""})()
        observations = [
            {"id": "Rakathon900001", "role": role, "rotation": 0, "confident": True,
             "candidates": [{"id": "Rakathon900001", "box": [10, 180, 100, 200]}]}
            for role in ("report", "drawing")
        ]
        with patch.object(ui.pipeline, "HERE", self.root), \
                patch.object(ui.pipeline.subprocess, "run", return_value=git_result), \
                patch.object(ui.pipeline.shutil, "which", return_value="/synthetic/tesseract"):
            case_ids = []
            for _ in range(2):
                with patch.object(ui.pipeline, "analyze", side_effect=observations):
                    self.app.start([("source-a.jpg", data), ("source-b.jpg", data)])
                    self.app.worker.join(timeout=5)
                self.assertFalse(self.app.busy)
                self.assertIsNone(self.app.error)
                batch = self.app.data["batches"][0]
                case = batch["cases"][0]
                case_ids.append(case["id"])
                self.assertEqual(case["originalId"], "Rakathon900001")
                self.assertEqual(case["decision"], "pending")
                self.assertEqual(batch["excluded"], [])
                for source in case["sources"].values():
                    self.assertEqual(ui.digest(Path(source["originalPath"])), original_hash)
            self.assertEqual(case_ids[0], case_ids[1])

    def test_no_pairs_are_held_but_ocr_failure_is_explicit(self):
        with patch.object(ui.pipeline, "run", side_effect=ui.pipeline.NoPairsError({"unpaired_or_ambiguous_id": 1})):
            self.app.start([("synthetic.jpg", jpeg())])
            self.app.worker.join(timeout=5)
        batch = self.app.data["batches"][0]
        self.assertIsNone(self.app.error)
        self.assertEqual(batch["pairs"], 0)
        self.assertEqual(len(batch["excluded"]), 1)
        with self.assertRaises(ui.InputError):
            self.app.release(batch["id"])
        with patch.object(ui.pipeline, "run", side_effect=RuntimeError("synthetic OCR failure")):
            self.app.start([("synthetic.jpg", jpeg())])
            self.app.worker.join(timeout=5)
        self.assertIsNotNone(self.app.error)
        self.assertEqual(len(self.app.data["batches"]), 1)

    def test_busy_batch_refuses_edits_and_second_upload(self):
        self.batch()
        self.app.busy = True
        with self.assertRaises(ui.BusyError):
            self.app.start([("synthetic.jpg", jpeg())])
        with self.assertRaises(ui.BusyError):
            self.app.decide(self.decision())
        with self.assertRaises(ui.BusyError):
            self.app.release("ui-synthetic")

    def test_multipart_requires_explicit_artificial_data_acknowledgment(self):
        body = (
            b"--synthetic\r\nContent-Disposition: form-data; name=\"files\"; filename=\"synthetic.jpg\"\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg() + b"\r\n"
        )
        final = b"--synthetic--\r\n"
        content_type = "multipart/form-data; boundary=synthetic"
        with self.assertRaises(ui.InputError):
            ui.upload_parts(content_type, body + final)
        ack = b"--synthetic\r\nContent-Disposition: form-data; name=\"artificial_data\"\r\n\r\nyes\r\n"
        files = ui.upload_parts(content_type, body + ack + final)
        self.assertEqual(files, [("synthetic.jpg", jpeg())])

    def test_http_guards_and_state_and_decision(self):
        self.batch()
        server = ui.make_server(self.app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/api/state", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(len(json.load(response)["batches"]), 1)
        payload = json.dumps(self.decision()).encode()
        for origin in (None, "https://untrusted.example"):
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            with self.assertRaises(HTTPError) as rejected:
                urlopen(Request(base + "/api/decision", data=payload, headers=headers), timeout=5)
            self.assertEqual(rejected.exception.code, 403)
        with urlopen(Request(base + "/api/decision", data=payload, headers={
            "Content-Type": "application/json", "Origin": base,
        }), timeout=5) as response:
            self.assertEqual(json.load(response), {"saved": True})
        with self.assertRaises(HTTPError) as rejected:
            urlopen(Request(base + "/api/state", headers={"Host": "untrusted.example"}), timeout=5)
        self.assertEqual(rejected.exception.code, 403)
