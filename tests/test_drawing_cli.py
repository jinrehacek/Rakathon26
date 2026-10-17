import pytest

from drawing_pipeline import cli


def test_a_view_with_no_usable_reading_fails_the_case(tmp_path):
    cli.require_readings({"base": [None, [], None]}, tmp_path)  # one run found nothing: fine
    with pytest.raises(RuntimeError, match="mid"):
        cli.require_readings({"base": [[]], "mid": [None, None, None]}, tmp_path)


def test_relative_output_is_resolved(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_grade", lambda args: seen.setdefault("output", args.output) and 0)
    cli.main(["grade", "--case", "x", "--round", "1", "--output", "Other/output/custom"])
    assert seen["output"].is_absolute()
    assert seen["output"].relative_to(cli.ROOT)
