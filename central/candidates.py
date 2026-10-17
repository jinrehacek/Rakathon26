"""Build drawing candidates without treating ink as a tumour diagnosis."""
from __future__ import annotations

import csv
from pathlib import Path

from .rules import DEFAULT_CROSSWALK, SECTOR_NAMED_RUNS_MIN, SECTOR_SHARE_MIN, ZONE_TABLE


def crosswalk_rows(path: Path | None = None) -> list[dict]:
    with (path or DEFAULT_CROSSWALK).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def mark_index(drawing: dict) -> dict[str, dict]:
    return {mark["id"]: mark for mark in drawing["marks"]}


def sector_code(sector: dict, rows: list[dict]) -> str | None:
    if sector.get("redcap"):
        return sector["redcap"]
    return next((row["redcap_code"] for row in rows
                 if row["zone"] == sector.get("zone")
                 and row["level"] == sector.get("level")
                 and row["patient_side"] == sector.get("patient_side")), None)


def _sector_key(sector: dict) -> tuple:
    return sector.get("zone"), sector.get("level"), sector.get("image_side")


def sector_sets(mark: dict, rows: list[dict]) -> tuple[set[str], set[str]]:
    """A sector is in when Gemini named it in enough runs and, if the mark has a polygon,
    the polygon puts enough of its in-sector area there. Every other contact is maybe."""
    runs = [{_sector_key(s) for s in run} for run in mark.get("sectors_named_by_run", [])]
    named = {code for sector in mark.get("sectors_named", [])
             if sum(_sector_key(sector) in run for run in runs) >= SECTOR_NAMED_RUNS_MIN
             and (code := sector_code(sector, rows))}
    if mark.get("polygon_ref") or mark.get("sectors_polygon"):
        selected = named & {code for sector in mark.get("sectors_polygon", [])
                            if sector["share"] >= SECTOR_SHARE_MIN and (code := sector_code(sector, rows))}
    else:  # a mark too small to trace has no polygon; its named sectors decide
        selected = named
    contacts = {code for source in ("sectors_named", "sectors_polygon", "sectors_cv")
                for sector in mark.get(source, [])
                if (code := sector_code(sector, rows))}
    return selected, contacts - selected


def build_candidates(drawing: dict, crosswalk_path: Path | None = None) -> list[dict]:
    """Consume a validated drawing-1 dictionary. IDs follow group then standalone order."""
    rows = crosswalk_rows(crosswalk_path)
    marks = mark_index(drawing)
    views = {view["id"]: view for view in drawing["views"]}
    excluded = {item["mark"] for item in drawing["not_lesion"]}
    sources = [("group:" + group["id"], group["members"]) for group in drawing["groups"]]
    sources.extend(("standalone:" + item["mark"], [item["mark"]])
                   for item in drawing["standalone"])
    candidates = []
    for source, members in sources:
        members = [member for member in members if member not in excluded]
        if not members:
            continue
        inside, maybe, sides, levels, zones, aps, exact_zones = (set() for _ in range(7))
        contributing_views = set()
        supports = []
        for member in members:
            mark = marks[member]
            view = views[mark["view"]]
            selected, possible = sector_sets(mark, rows)
            # Longitudinal bands provide level evidence, never axial sector checkboxes.
            axial = view["view_type"] in {"axial", "cross-sectional", "cross_sectional"} or view["id"] in {"base", "mid", "apex"}
            if axial:
                inside.update(selected)
                maybe.update(possible)
            for source_name in ("sectors_named", "sectors_polygon", "sectors_cv"):
                for sector in mark.get(source_name, []):
                    levels.add(sector["level"])
                    code = sector_code(sector, rows)
                    if axial and code in selected and source_name != "sectors_cv":
                        side = sector.get("patient_side")
                        if side in {"right", "left", "midline"}:
                            sides.add(side)
                            contributing_views.add(view["id"])
                        elif side == "bilateral":
                            sides.update({"right", "left"})
                            contributing_views.add(view["id"])
                        zone, ap = ZONE_TABLE.get(sector["zone"], (None, None))
                        if zone:
                            zones.add(zone)
                            exact_zones.add(sector["zone"])
                        if ap:
                            aps.add(ap)
            supports.append(member)
        candidate = {
            "id": f"c{len(candidates) + 1}", "source": source, "marks": members,
            "standalone": source.startswith("standalone:"),
            "depends_on": [source] if source.startswith("group:") else [],
            "sectors_in": sorted(inside), "sectors_maybe": sorted(maybe - inside),
            "sides": sorted(sides), "side_basis": "explicit" if contributing_views and all(
                views[view]["orientation"].get("basis") == "explicit" for view in contributing_views
            ) else "inferred",
            "levels": sorted(levels - {"unknown", "unspecified"}), "zones": sorted(zones),
            "exact_zones": sorted(exact_zones),
            "anteroposterior": sorted(aps), "sector_count": len(inside),
            "supports": supports,
        }
        candidates.append(candidate)
    return candidates
