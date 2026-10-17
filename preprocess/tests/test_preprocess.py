import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


spec = importlib.util.spec_from_file_location(
    "jpg_mvp", Path(__file__).resolve().parents[1] / "preprocess.py"
)
mvp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mvp)

review_spec = importlib.util.spec_from_file_location(
    "jpg_review", Path(__file__).resolve().parents[1] / "review.py"
)
review = importlib.util.module_from_spec(review_spec)
review_spec.loader.exec_module(review)


class MvpTests(unittest.TestCase):
    def test_private_comparison_links_and_back_matching(self):
        import json

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            batch, private = root / "batch", root / "private"
            batch.mkdir()
            private.mkdir()
            sources, paths = [], {}
            for role in ("report", "drawing"):
                original, redacted = root / f"original-{role}.jpg", batch / f"{role}.jpg"
                original.touch()
                redacted.touch()
                sources.append({"role": role, "source": str(original), "rotation": 0})
                paths[role] = redacted.name
            (batch / "manifest.json").write_text(json.dumps({"cases": {"case-123": paths}}))
            (private / "dictionary.json").write_text(json.dumps({
                "synthetic<&>": {"case_id": "case-123", "sources": sources},
            }))
            manifest_before = (batch / "manifest.json").read_bytes()
            output, count = review.build_review(batch, private)
            html = output.read_text()
            self.assertEqual(count, 1)
            self.assertEqual(output.parent, private)
            self.assertIn("synthetic&lt;&amp;&gt;", html)
            self.assertIn("case-123", html)
            self.assertIn((root / "original-report.jpg").as_uri(), html)
            self.assertIn((batch / "drawing.jpg").as_uri(), html)
            self.assertNotIn("<script", html)
            self.assertEqual((batch / "manifest.json").read_bytes(), manifest_before)

    def test_ids_preserve_digits_and_carry_coordinates(self):
        words = [
            {"text": "rAkAtHoN01", "confidence": 95, "box": (10, 20, 100, 40), "line": (1, 1, 1)},
        ]
        result = mvp.identify(words)
        self.assertEqual(result[0]["id"], "Rakathon01")
        self.assertEqual(result[0]["box"], (10, 20, 100, 40))

    def test_drawing_role_uses_template_labels(self):
        words = [{"text": label, "confidence": 95} for label in ("Base", "Mid", "Apex")]
        self.assertEqual(mvp.role(words), "drawing")

    def test_masks_replace_pixels_without_changing_original_or_faint_colour(self):
        with Image.new("RGB", (100, 100), (255, 255, 190)) as image:
            image.info["comment"] = "synthetic private metadata"
            with mvp.redacted(image, [(20, 20, 40, 40)]) as masked:
                self.assertEqual(masked.getpixel((30, 30)), (0, 0, 0))
                self.assertEqual(masked.getpixel((80, 80)), (255, 255, 190))
                self.assertFalse(masked.info)
            self.assertEqual(image.getpixel((30, 30)), (255, 255, 190))

    def test_pair_output_and_stable_private_dictionary(self):
        import json

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "inputs"
            batch.mkdir()
            for name in ("a.jpg", "b.jpg"):
                with Image.new("RGB", (100, 140), "white") as image:
                    image.save(batch / name)
            results = [
                {"id": "Rakathon731", "role": role, "rotation": 0, "confident": True,
                 "candidates": [{"id": "Rakathon731", "box": (10, 100, 70, 120)}]}
                for role in ("report", "drawing")
            ]
            git_result = type("Result", (), {"returncode": 0, "stdout": b""})()
            with patch.object(mvp, "HERE", root), \
                    patch.object(mvp.subprocess, "run", return_value=git_result), \
                    patch.object(mvp.shutil, "which", return_value="/local/tesseract"):
                manifests = []
                for _ in range(2):
                    with patch.object(mvp, "analyze", side_effect=results):
                        summary = mvp.run(batch)
                    manifest = json.loads((Path(summary["bundle"]) / "manifest.json").read_text())
                    self.assertEqual(summary["pairs"], 1)
                    self.assertNotIn("Rakathon731", json.dumps(manifest))
                    manifests.append(manifest)
                self.assertEqual(manifests[0]["cases"], manifests[1]["cases"])
                self.assertIn("Rakathon731", json.loads(
                    (root / ".preprocess-private" / "dictionary.json").read_text()
                ))
