#!/usr/bin/env python3
"""Phone-friendly HTML comparing calculated (CV) sectors with Gemini pass A and B sectors. A probe, not accuracy."""

import argparse
import csv
import html
import json
from pathlib import Path

import cv2 as cv

ROOT = Path(__file__).resolve().parents[1]
CROSSWALK = ROOT / "Other/redcap/sector_crosswalk.csv"
ZONES = {"AFS": "as", "PZa": "pza", "PZpl": "pzpl", "PZpm": "pzpm", "TZa": "tza", "TZp": "tzp", "CZ": "cz", "SV": "sv"}
SMALL = 30


def code_lookup():
    rows = list(csv.DictReader(CROSSWALK.open()))
    return {(r["zone"], r["level"], r["drawn_on_viewer"]): r["redcap_code"] for r in rows if r["drawn_on_viewer"] in ("left", "right")}


def gemini_codes(result, lookup):
    sure, maybe = set(), set()
    for mark in result["reading"]["marks"]:
        reading = mark["sectors"]
        for target, items in ((sure, reading["value"] or []), (maybe, reading["candidates"])):
            for s in items:
                if s["zone"] == "urethra":
                    target.add("urethra")
                    continue
                key = (ZONES.get(s["zone"]), s["level"], s["image_side"])
                target.add(lookup.get(key, f"{s['zone']}_{s['level']}_{s['image_side']}?"))
    return sure, maybe - sure


def cv_codes(regions):
    sure, maybe = set(), set()
    for region in regions["regions"]:
        if region["annotation_outside_organ"]:
            continue
        for c in region["sectors"]:
            (maybe if c["px"] < SMALL else sure).add(c["redcap_if_standard_orientation"])
    return sure, maybe - sure


def thumb(src, dst, width=560):
    image = cv.imread(str(src))
    if image.shape[1] > width:
        image = cv.resize(image, (width, round(image.shape[0] * width / image.shape[1])), interpolation=cv.INTER_AREA)
    cv.imwrite(str(dst), image, [cv.IMWRITE_JPEG_QUALITY, 80])
    return dst.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", type=Path, required=True, help="Gemini probe run folders")
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--handwriting", type=Path, default=ROOT / "Other/output/handwriting")
    parser.add_argument("--sectors", type=Path, default=ROOT / "Other/output/sectors")
    parser.add_argument("--output", type=Path, default=ROOT / "Other/output/sector-comparison")
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / "Other/output").resolve()):
        parser.error("Use an output directory under the git-ignored Other/output folder")
    args.output.mkdir(parents=True, exist_ok=True)
    lookup = code_lookup()
    cards, summary = [], []
    for run in args.runs:
        for view_dir in sorted((run / args.model).glob("scan_*")):
            scan, view = view_dir.name.rsplit("_", 1)
            if view not in ("base", "mid", "apex"):
                continue
            passes = {p: json.loads((view_dir / p / "result.json").read_text()) for p in ("A", "B")}
            regions = json.loads((args.sectors / scan / view / "regions.json").read_text())
            cv_sure, cv_maybe = cv_codes(regions)
            a_sure, a_maybe = gemini_codes(passes["A"], lookup)
            b_sure, b_maybe = gemini_codes(passes["B"], lookup)
            name = f"{scan}_{view}"
            original = thumb(args.handwriting / scan / view / "original.png", args.output / f"{name}_original.jpg")
            overlay = thumb(args.sectors / scan / view / "overlay.png", args.output / f"{name}_cv.jpg")
            every = sorted(cv_sure | cv_maybe | a_sure | a_maybe | b_sure | b_maybe)
            def cell(sure, maybe, code):
                return "<td class=y>✓</td>" if code in sure else "<td class=m>?</td>" if code in maybe else "<td></td>"
            rows = "".join(f"<tr class={'agree' if (c in cv_sure) == (c in a_sure) == (c in b_sure) else 'diff'}><th>{c}</th>"
                           f"{cell(cv_sure, cv_maybe, c)}{cell(a_sure, a_maybe, c)}{cell(b_sure, b_maybe, c)}</tr>" for c in every)
            region_lines = "".join(
                f"<li><b>{r['id']}</b> {r['kind'].replace('_', ' ')}{' (note/letter, outside organ)' if r['annotation_outside_organ'] else ''}"
                f"{', grown ' + str(r['grow_radius_px']) + ' px' if r['grow_radius_px'] else ''}: "
                + ", ".join(f"{c['redcap_if_standard_orientation']} {c['px']}px" for c in r["sectors"][:6])
                + "".join(f"<br><i>{html.escape(q)}</i>" for q in r["questions"]) + "</li>" for r in regions["regions"])
            def mark_lines(result):
                out = []
                for m in result["reading"]["marks"]:
                    text = m["handwriting"]["value"] if m["handwriting"]["status"] == "recorded" else ""
                    sectors = ", ".join(f"{s['zone']} {s['image_side']}" for s in (m["sectors"]["value"] or []))
                    out.append(f"<li><b>{m['id']}</b> {m['kind']}{' “' + html.escape(text) + '”' if text else ''}{': ' + sectors if sectors else ''}</li>")
                return "".join(out)
            same_b, same_a = cv_sure == b_sure, cv_sure == a_sure
            summary.append((name, same_a, same_b, a_sure == b_sure))
            gid = html.escape(name)
            cards.append(f"""
<section class=card id="{gid}">
  <h2>{scan.replace('scan_00', 'scan ')} · {view}</h2>
  <div class=tags><span class="{'ok' if same_b else 'bad'}">CV vs B {'same' if same_b else 'differ'}</span>
  <span class="{'ok' if same_a else 'bad'}">CV vs A {'same' if same_a else 'differ'}</span>
  <span class="{'ok' if a_sure == b_sure else 'bad'}">A vs B {'same' if a_sure == b_sure else 'differ'}</span></div>
  <figure><img src="{original}" alt="original"><figcaption>Original scan crop</figcaption></figure>
  <figure><img src="{overlay}" alt="cv"><figcaption>CV: filled = detected area, <span class=red>red</span> = gap the code bridged, <span class=orange>orange</span> = stroke not part of any loop, grey = note/letter</figcaption></figure>
  <table><tr><th>Sector (if viewer-left = patient right)</th><th>CV</th><th>A</th><th>B</th></tr>{rows}</table>
  <details><summary>Per-mark details</summary>
    <p><b>CV regions</b></p><ul>{region_lines or '<li>none</li>'}</ul>
    <p><b>Gemini A (original)</b></p><ul>{mark_lines(passes['A'])}</ul>
    <p><b>Gemini B (cleaned)</b></p><ul>{mark_lines(passes['B'])}</ul>
  </details>
  <div class=grade data-view="{gid}">
    <p>Which sector list is right?</p>
    {''.join(f'<button data-v="{v}">{v}</button>' for v in ('CV', 'A', 'B', 'all same', 'none'))}
    <p>Did CV find every circle, including gappy ones?</p>
    {''.join(f'<button data-q="loops" data-v="{v}">{v}</button>' for v in ('yes', 'missed one', 'invented one'))}
    <input placeholder="note (optional)">
  </div>
</section>""")
    n = len(summary)
    head = (f"<p class=lead>{n} axial views. CV and Gemini B give the same sector set on {sum(s[2] for s in summary)}/{n}, "
            f"CV and A on {sum(s[1] for s in summary)}/{n}, A and B on {sum(s[3] for s in summary)}/{n}. "
            "Same set is not proof that it's right. That's what your grading is for.</p>")
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{{font-family:var(--font-sans,system-ui);line-height:1.45;margin:0}}
.card{{border-top:1px solid var(--border,#ccc);padding:14px 0 18px}}
h1{{font-size:1.2rem;margin:4px 0}} h2{{font-size:1.05rem;margin:0 0 6px}}
img{{width:100%;height:auto;border-radius:8px;display:block}} figure{{margin:8px 0}} figcaption{{font-size:.8rem;opacity:.75}}
.red{{color:#e33;font-weight:700}} .orange{{color:#f90;font-weight:700}}
table{{border-collapse:collapse;width:100%;font-size:.85rem;margin-top:6px}} td,th{{padding:4px 6px;border-bottom:1px solid var(--border,#ddd);text-align:left}}
td{{text-align:center;width:38px}} td.y{{color:#2a2;font-weight:700}} td.m{{color:#d90}} tr.diff th{{color:#e55}}
.tags span{{display:inline-block;font-size:.75rem;padding:2px 8px;border-radius:99px;margin:0 4px 4px 0;border:1px solid}}
.ok{{color:#2a2}} .bad{{color:#e55}}
.grade button{{font:inherit;font-size:.85rem;padding:6px 10px;margin:3px 3px 3px 0;border-radius:8px;border:1px solid var(--border,#aaa);background:transparent;color:inherit}}
.grade button.on{{background:var(--primary,#36f);color:var(--primary-foreground,#fff)}}
.grade input{{width:100%;box-sizing:border-box;padding:7px;margin-top:6px;border-radius:8px;border:1px solid var(--border,#aaa);background:transparent;color:inherit;font:inherit}}
#copy{{position:sticky;bottom:8px;width:100%;padding:12px;font:inherit;font-weight:700;border-radius:10px;border:0;background:var(--primary,#36f);color:var(--primary-foreground,#fff)}}
details{{font-size:.85rem;margin-top:8px}} .lead{{font-size:.95rem}}
</style></head><body>
<h1>CV vs Gemini sectors, round 2</h1>{head}
<p style="font-size:.85rem;opacity:.8">✓ = in the list, ? = small contact or model candidate. Red rows = sources disagree. Tap your answers, then "Copy grades" and paste them back to me.</p>
{''.join(cards)}
<textarea id=out rows=8 style="display:none;width:100%;box-sizing:border-box;margin:8px 0;font:inherit;font-size:.8rem"></textarea>
<button id=copy>Copy grades</button>
<script>
document.querySelectorAll('.grade').forEach(g=>g.addEventListener('click',e=>{{const b=e.target.closest('button');if(!b)return;
const group=[...g.querySelectorAll('button')].filter(x=>(x.dataset.q||'')===(b.dataset.q||''));group.forEach(x=>x.classList.toggle('on',x===b));}}));
document.getElementById('copy').onclick=async()=>{{const lines=[...document.querySelectorAll('.grade')].map(g=>{{
const pick=q=>{{const b=[...g.querySelectorAll('button.on')].find(x=>(x.dataset.q||'')===q);return b?b.dataset.v:'-';}};
return g.dataset.view+': sectors='+pick('')+' loops='+pick('loops')+(g.querySelector('input').value?' note='+g.querySelector('input').value:'');}});
const text=lines.join('\\n');const box=document.getElementById('out');box.style.display='block';box.value=text;
try{{await navigator.clipboard.writeText(text);document.getElementById('copy').textContent='Copied. Paste it in the chat';}}
catch(err){{box.select();document.getElementById('copy').textContent='Select the text above and copy it';}}}};
</script></body></html>"""
    (args.output / "index.html").write_text(page)
    print(f"{n} views -> {args.output / 'index.html'}")
    for row in summary:
        print(*row)


if __name__ == "__main__":
    main()
