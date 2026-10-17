import numpy as np

from drawing_pipeline import polygon_sectors as ps
from drawing_pipeline.models import Mark, Sector
from drawing_pipeline.reference import regions_for


def region(view, zone, side):
    return next(r for r in regions_for(view) if r.zone == zone and r.image_side == side)


def shrunk(polygon, factor=0.6):
    centre = polygon.mean(axis=0)
    return np.round(centre + (polygon - centre) * factor).astype(int).tolist()


def bubble(view, polygon, named, kind="closed outline", closed=True):
    return Mark(id=f"{view}.m1", view=view, kind=kind, runs_found=3, polygon_ref=polygon, closed=closed,
                sectors_named=named)


def test_polygon_inside_one_sector_agrees():
    target = region("base", "pzpl", "left")
    mark = bubble("base", shrunk(target.polygon), [Sector(zone="pzpl", level="base", image_side="left")])
    shares, signals = ps.polygon_sectors(mark)
    assert [(s.zone, s.image_side) for s in shares][0] == ("pzpl", "left") and shares[0].share > 0.9
    assert signals == []


def test_named_sector_not_touched_and_omitted_sector():
    target = region("base", "pzpl", "left")
    mark = bubble("base", shrunk(target.polygon), [Sector(zone="tza", level="base", image_side="right")])
    _, signals = ps.polygon_sectors(mark)
    assert len(signals) == 1 and signals[0].kind == "named_vs_polygon"
    assert "tza base right" in signals[0].reason and "pzpl base left" in signals[0].reason


def test_only_omitted_shares_over_threshold_are_signalled():
    polygon = shrunk(region("base", "pzpl", "left").polygon, 0.9)
    shares, signals = ps.polygon_sectors(bubble("base", polygon, []))
    assert signals                                          # nothing named, big share omitted
    named = [Sector(zone=s.zone, level=s.level, image_side=s.image_side) for s in shares if s.share >= 0.15]
    assert ps.polygon_sectors(bubble("base", polygon, named))[1] == []


def test_longitudinal_and_non_bubbles():
    target = region("coronal", "prostate", "left")
    mark = bubble("coronal", shrunk(target.polygon), [Sector(zone="prostate", level=target.level,
                                                             image_side="left")])
    shares, signals = ps.polygon_sectors(mark)
    assert shares[0].level == target.level and signals == []
    text = Mark(id="base.m2", view="base", kind="text", runs_found=3, polygon_ref=shrunk(target.polygon),
                closed=False, sectors_named=[])
    assert ps.polygon_sectors(text.model_copy(update={"view": "coronal"}))[1] == []
    no_polygon = Mark(id="base.m3", view="base", kind="closed outline", runs_found=3, box_ref=[800, 400, 900, 500])
    assert ps.polygon_sectors(no_polygon) == ([], [])


def test_open_arc_uses_stroke_and_apply_fills_marks():
    target = region("base", "pzpl", "left")
    line = shrunk(target.polygon)[:3]
    arc = bubble("base", line, [], kind="open arc", closed=False)
    closed = bubble("base", shrunk(target.polygon), [Sector(zone="pzpl", level="base", image_side="left")])
    signals = ps.apply([arc, closed])
    assert arc.sectors_polygon and closed.sectors_polygon
    assert sum(s.px for s in arc.sectors_polygon) < sum(s.px for s in closed.sectors_polygon)
    assert [s.observations[0] for s in signals] == ["base.m1.sectors_named"]


def test_omitted_share_counts_the_whole_polygon():
    # A box mostly outside the gland: the corner in a sector is a large share of the in-sector pixels
    # but under 15% of the polygon, so omitting it raises nothing.
    target = region("base", "pzpl", "left")
    x0, y0 = target.polygon.min(axis=0)
    box = [[x0 - 200, y0 - 200], [x0 + 20, y0 - 200], [x0 + 20, y0 + 20], [x0 - 200, y0 + 20]]
    shares, signals = ps.polygon_sectors(bubble("base", [[int(x), int(y)] for x, y in box], []))
    assert sum(s.share for s in shares) > 0.99 and signals == []
