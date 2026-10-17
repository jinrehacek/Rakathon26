from drawing_pipeline.models import Mark
from drawing_pipeline.notes import link_notes


def mark(mark_id, kind, box, text=None, polygon=None):
    return Mark(id=mark_id, view=mark_id.split(".")[0], kind=kind, runs_found=3, text=text, box_ref=box,
                polygon_ref=polygon, closed=polygon is not None)


def test_text_links_to_nearest_non_text_mark():
    marks = [
        mark("base.m1", "closed outline", [800, 400, 900, 500]),
        mark("base.m2", "closed outline", [1200, 600, 1300, 700]),
        mark("base.m3", "text", [1210, 720, 1290, 750], text="zánět"),
        mark("base.m4", "side letter", [1215, 710, 1225, 720], text="L"),
    ]
    signals = link_notes(marks)
    note = marks[2]
    assert note.linked_to.mark == "base.m2" and note.linked_to.basis.value == "inferred"
    assert note.basis.value == "explicit" and note.certainty.extraction.value == "low"
    assert [(s.kind, s.observations, s.suggestion) for s in signals] == [("low_trust_note", ["base.m3"], "text is probably right")]
    assert marks[3].linked_to is None and marks[3].certainty.extraction.value == "unassessed"
    assert marks[0].linked_to is None


def test_other_kind_with_text_counts_and_polygon_distance_is_used():
    outline = mark("mid.m1", "closed outline", None, polygon=[[800, 1000], [900, 1000], [900, 1100], [800, 1100]])
    far = mark("mid.m2", "closed outline", [1200, 1000, 1250, 1050])
    arrow = mark("mid.m3", "arrow", [905, 1040, 960, 1060], text="cca 25mm")
    signals = link_notes([outline, far, arrow])
    assert arrow.linked_to.mark == "mid.m1" and len(signals) == 1
    assert outline.certainty.extraction.value == "unassessed"


def test_non_letter_side_letter_text_is_a_note_and_empty_view_has_no_link():
    lone = mark("apex.m1", "text", [900, 1300, 950, 1330], text="vlevo?")
    odd = mark("apex.m2", "side letter", [900, 1400, 920, 1420], text="X")
    signals = link_notes([lone, odd])
    assert lone.linked_to is None and odd.certainty.extraction.value == "low" and len(signals) == 2
