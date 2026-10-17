import hashlib
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
    def words(self, identifier="Rakathon731", confidence=95, *, mid=True):
        labels = ["Base", "Apex"] + (["Mid"] if mid else [])
        return [
            {"text": text, "confidence": 95, "box": (10, 20 + index * 30, 70, 40 + index * 30), "line": (1, 1, index)}
            for index, text in enumerate(labels)
        ] + [{"text": identifier, "confidence": confidence, "box": (10, 500, 110, 520), "line": (2, 1, 1)}]

    def test_analyze_retries_layout_when_sparse_ocr_misses_mid(self):
        def recognize(image, psm):
            if image.width == 400:
                return self.words(mid=psm == 6)
            return []

        with Image.new("RGB", (400, 600), "white") as image, patch.object(mvp, "ocr", side_effect=recognize):
            result = mvp.analyze(image)
        self.assertEqual(result["role"], "drawing")
        self.assertTrue(result["confident"])
        self.assertEqual(result["rotation"], 0)

    def test_analyze_recrops_a_damaged_ocr_prefix_without_fuzzy_matching_ids(self):
        def recognize(image, psm):
            if image.width == 400:
                return self.words(identifier="Rakath0n731", confidence=40)
            if image.height < 200 and image.width < 1000:
                return [{"text": "Rakathon731", "confidence": 85, "box": (20, 20, 220, 60), "line": (1, 1, 1)}]
            return []

        with Image.new("RGB", (400, 600), "white") as image, patch.object(mvp, "ocr", side_effect=recognize):
            result = mvp.analyze(image)
        self.assertTrue(result["confident"])
        self.assertEqual(result["id"], "Rakathon731")
        self.assertTrue(result["candidates"])
        self.assertTrue(all(candidate["quote"] == "Rakathon731" for candidate in result["candidates"]))
        self.assertTrue(all(0 <= candidate["box"][0] < candidate["box"][2] <= 400 and
                            0 <= candidate["box"][1] < candidate["box"][3] <= 600
                            for candidate in result["candidates"]))

    def test_low_confidence_id_retries_before_returning(self):
        def recognize(image, psm):
            if image.width == 400:
                return self.words(confidence=59)
            if image.width == 3200:
                return [{"text": "Rakathon731", "confidence": 82, "box": (80, 400, 880, 560), "line": (1, 1, 1)}]
            return []

        with Image.new("RGB", (400, 600), "white") as image, patch.object(mvp, "ocr", side_effect=recognize):
            result = mvp.analyze(image)
        self.assertTrue(result["confident"])
        self.assertEqual(result["id"], "Rakathon731")

    def test_read_region_maps_crop_coordinates_back_to_upright_image(self):
        recognized = [{"text": "Rakathon731", "confidence": 95, "box": (20, 10, 200, 100), "line": (1, 1, 1)}]
        with Image.new("RGB", (400, 600), "white") as image, patch.object(mvp, "ocr", return_value=recognized):
            words = mvp.read_region(image, (20, 200, 200, 300), 360, 7)
        self.assertEqual(words[0]["box"], (30, 205, 120, 250))

    def test_unreadable_prefix_is_not_repaired_into_a_guessed_identifier(self):
        def recognize(image, psm):
            return self.words(identifier="Rakath0n731", confidence=40) if image.width == 400 else []

        with Image.new("RGB", (400, 600), "white") as image, patch.object(mvp, "ocr", side_effect=recognize):
            result = mvp.analyze(image)
        self.assertFalse(result["confident"])
        self.assertIsNone(result["id"])
        self.assertEqual(result["candidates"], [])

    def test_conflicting_identifiers_remain_held(self):
        def recognize(image, psm):
            if image.width == 400:
                return self.words(identifier="Rakathon731")
            return [{"text": "Rakathon732", "confidence": 95, "box": (80, 400, 880, 560), "line": (1, 1, 1)}]

        with Image.new("RGB", (400, 600), "white") as image, patch.object(mvp, "ocr", side_effect=recognize):
            result = mvp.analyze(image)
        self.assertFalse(result["confident"])
        self.assertIsNone(result["id"])
        self.assertEqual({candidate["id"] for candidate in result["candidates"]}, {"Rakathon731", "Rakathon732"})

    def test_retries_do_not_lower_confidence_threshold(self):
        def recognize(image, psm):
            if image.width == 400:
                return self.words(confidence=69)
            return [{"text": "Rakathon731", "confidence": 69, "box": (10, 20, 100, 40), "line": (1, 1, 1)}]

        with Image.new("RGB", (400, 600), "white") as image, patch.object(mvp, "ocr", side_effect=recognize):
            result = mvp.analyze(image)
        self.assertFalse(result["confident"])
        self.assertEqual(result["id"], "Rakathon731")

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
                    self.assertEqual(manifest["schema_version"], "preprocess-handoff-v1")
                    for case_id, paths in manifest["cases"].items():
                        for role, relative in paths.items():
                            self.assertEqual(manifest["output_sha256"][case_id][role],
                                             hashlib.sha256((Path(summary["bundle"]) / relative).read_bytes()).hexdigest())
                    manifests.append(manifest)
                self.assertEqual(manifests[0]["cases"], manifests[1]["cases"])
                self.assertIn("Rakathon731", json.loads(
                    (root / ".preprocess-private" / "dictionary.json").read_text()
                ))
