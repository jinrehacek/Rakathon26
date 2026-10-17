import numpy as np

from drawing_pipeline.merge import merge_runs
from drawing_pipeline.models import RunMark, Sector
from drawing_pipeline.reference import VIEWS

PZPL = Sector(zone="pzpl", level="base", image_side="left")
CZ = Sector(zone="cz", level="base", image_side="left")


def square(run, local_id, x, y, size=60, kind="closed outline", sectors=(PZPL,)):
    polygon = [[x, y], [x + size, y], [x + size, y + size], [x, y + size]]
    return RunMark(run=run, local_id=local_id, kind=kind, polygon_crop=polygon, closed=True,
                   box_crop=[x, y, x + size, y + size], sectors=list(sectors))


def letter(run, local_id, x, y, size=20, text="P"):
    return RunMark(run=run, local_id=local_id, kind="side letter", box_crop=[x, y, x + size, y + size], text=text)


def arc(run, local_id, dy=0):
    polygon = [[x, 300 + dy + 20 * np.sin(x / 30)] for x in range(100, 300, 10)]
    return RunMark(run=run, local_id=local_id, kind="open arc", polygon_crop=polygon, closed=False,
                   box_crop=[100, 280 + dy, 290, 320 + dy])


def test_three_runs_merge_with_stable_ids():
    runs = [[square(1, "m1", 300, 100), letter(1, "m2", 50, 40)],
            [letter(2, "m1", 51, 41), square(2, "m2", 302, 101)],
            [square(3, "m5", 299, 99), letter(3, "m3", 50, 42)]]
    marks, signals = merge_runs("base", runs)
    assert signals == []
    assert [m.id for m in marks] == ["base.m1", "base.m2"]
    first, second = marks
    assert first.kind == "side letter" and first.text == "P" and first.polygon_ref is None
    assert first.run_local_ids == ["m2", "m1", "m3"] and first.runs_found == 3
    assert second.kind == "closed outline" and second.closed and second.run_local_ids == ["m1", "m2", "m5"]
    ox, oy = VIEWS["base"].origin
    assert second.polygon_ref[0][0] - ox in (299, 300, 302) and second.box_ref[1] - oy in (99, 100, 101)
    assert len(second.sectors_named_by_run) == 3 and second.sectors_named == [PZPL]
    assert second.basis == "inferred"
    assert merge_runs("base", runs)[0] == marks


def test_partial_runs_and_failed_run():
    runs = [[square(1, "m1", 300, 100), square(1, "m2", 100, 300)],
            None,
            [square(3, "m1", 301, 100)]]
    marks, signals = merge_runs("base", runs)
    by_id = {m.id: m for m in marks}
    lonely = next(m for m in marks if m.runs_found == 1)
    assert lonely.run_local_ids == ["m2", None, None]
    assert next(m for m in marks if m.runs_found == 2).run_local_ids == ["m1", None, "m1"]
    assert [(s.kind, s.observations, s.suggestion) for s in signals] == [
        ("run_instability", [lonely.id], "would flag")]
    assert "1 of 2" in signals[0].reason and set(by_id) == {"base.m1", "base.m2"}


def test_two_of_three_is_info_only_and_sector_instability():
    runs = [[square(1, "m1", 300, 100, sectors=[PZPL, CZ])],
            [square(2, "m1", 300, 100)],
            [square(3, "m1", 200, 300)]]
    marks, signals = merge_runs("base", runs)
    stable = next(m for m in marks if m.runs_found == 2)
    assert stable.sectors_named == [PZPL, CZ] and stable.sectors_named_by_run == [[PZPL, CZ], [PZPL]]
    found = {(tuple(s.observations), s.suggestion) for s in signals}
    assert ((stable.id,), "info only") in found
    assert ((f"{stable.id}.sectors_named",), "would flag") in found     # CZ named in 1 of 2
    assert len(signals) == 3


def test_one_mark_per_run():
    # Two overlapping marks in run 1 must not both join the same run-2 mark.
    runs = [[square(1, "m1", 300, 100), square(1, "m2", 305, 100)], [square(2, "m1", 302, 100)], []]
    marks, _ = merge_runs("base", runs)
    assert len(marks) == 2
    assert sorted(m.runs_found for m in marks) == [1, 2]


def test_kind_majority_and_text():
    runs = [[square(1, "m1", 300, 100, kind="small circle")],
            [square(2, "m1", 300, 100, kind="closed outline")],
            [square(3, "m1", 300, 100, kind="closed outline")]]
    marks, _ = merge_runs("base", runs)
    assert marks[0].kind == "closed outline"
    texts = [[RunMark(run=k, local_id="m1", kind="text", box_crop=[100, 100, 200, 130], text=t)]
             for k, t in enumerate(["cca 25mm", "cca 25mm", "cca 26mm"], 1)]
    marks, _ = merge_runs("base", texts)
    assert marks[0].text == "cca 25mm" and marks[0].basis == "explicit"


def test_jittered_thin_marks_chain_at_two_px():
    # Passes only through single-link chaining: the +2 and -2 arcs are 4 px apart (IoU about 0.32).
    # Arcs split at a 3 px offset and 20 px letter boxes at a 4 px diagonal shift; see the merge report.
    arcs = merge_runs("base", [[arc(1, "m1", 0)], [arc(2, "m1", 2)], [arc(3, "m1", -2)]])[0]
    letters = merge_runs("base", [[letter(1, "m1", 50, 40)], [letter(2, "m1", 53, 41)], [letter(3, "m1", 50, 37)]])[0]
    assert [m.runs_found for m in arcs] == [3]
    assert [m.runs_found for m in letters] == [3]


def test_all_runs_failed():
    assert merge_runs("base", [None, None, None]) == ([], [])


def test_thin_arcs_and_letters_match_despite_a_few_px_of_jitter():
    runs = [[arc(1, "m1", dy=0), letter(1, "m2", 50, 40)],
            [arc(2, "m1", dy=4), letter(2, "m2", 54, 44)],
            [arc(3, "m1", dy=-4), letter(3, "m2", 46, 36)]]
    marks, signals = merge_runs("base", runs)
    assert [m.runs_found for m in marks] == [3, 3]
    assert not [s for s in signals if s.kind == "run_instability"]
    assert next(m for m in marks if m.kind == "side letter").basis == "explicit"


def test_minority_letter_reading_loses_to_the_majority():
    # Identical boxes tie on geometry, so run 1 wins it; its P must not outvote L, L.
    runs = [[letter(k, "m1", 50, 40, text=t)] for k, t in enumerate(["P", "L", "L"], 1)]
    marks, signals = merge_runs("base", runs)
    assert marks[0].text == "L"
    assert [(s.kind, s.observations, s.suggestion) for s in signals] == [
        ("run_instability", ["base.m1.text"], "info only")]
    assert "'P', 'L', 'L'" in signals[0].reason


def test_text_differing_only_in_case_and_spacing_agrees():
    runs = [[RunMark(run=k, local_id="m1", kind="text", box_crop=[100, 100, 200, 130], text=t)]
            for k, t in enumerate(["cca 25mm", "CCA 25 mm", "cca 25mm"], 1)]
    marks, signals = merge_runs("base", runs)
    assert marks[0].text == "cca 25mm" and signals == []
