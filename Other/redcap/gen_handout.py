import csv, html
OUT="/home/jindris/Projects/Rakathon26/Other/redcap"
cw=list(csv.DictReader(open(f"{OUT}/sector_crosswalk.csv")))
by={r["redcap_code"]:r for r in cw}
zones=[("sv","SV seminal vesicle"),("as","AS anterior fibromuscular"),("pza","PZa"),("pzpl","PZpl"),("pzpm","PZpm"),("tza","TZa"),("tzp","TZp"),("cz","CZ")]
def cell(z,l,s):
    c=f"{z}_{l}_{s}"
    return f'<td class="{ "on" if c in by else "off"}">{c if c in by else ""}</td>'
grid=""
for l in ("base","mid","apex"):
    grid+=f'<tr class="lv"><th colspan="3">{l.upper()}</th></tr>'
    grid+='<tr><th>zone</th><th>patient RIGHT (rs)<br><small>viewer left</small></th><th>patient LEFT (ls)<br><small>viewer right</small></th></tr>'
    for z,n in zones:
        if f"{z}_{l}_rs" in by:
            grid+=f"<tr><th>{html.escape(n)}</th>{cell(z,l,'rs')}{cell(z,l,'ls')}</tr>"
page=f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>COMPARE REDCap handout</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#1b1f23}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:22px 0 6px;border-bottom:2px solid #1f4e79;padding-bottom:2px}}
table{{border-collapse:collapse;width:100%;margin:6px 0}} th,td{{border:1px solid #c9d1d9;padding:3px 7px;text-align:left;vertical-align:top}}
th{{background:#f1f4f8}} tr.lv th{{background:#1f4e79;color:#fff}} td.on{{font-family:ui-monospace,monospace;font-size:12px;background:#fff7e0}} td.off{{background:#eee}}
code{{background:#f1f4f8;padding:0 3px;border-radius:3px}} .warn{{background:#fdecea;border:1px solid #e0a8a2;padding:6px 10px}} .cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
small{{color:#57606a}} @media print{{body{{margin:0}}}}
</style>
<h1>COMPARE registry (REDCap project 64): what we write</h1>
<small>redcap.mou.cz, REDCap 17.3.7, status Development. Read 2026-10-17. Full report: REDCAP.md. Do not publish: contains the project's choice list.</small>
<h2>Priority</h2>
<table><tr><th>Tier</th><th>What</th><th>Source</th></tr>
<tr><td>1</td><td><b>Segments</b>: <code>sur_prostate_regions___*</code> (41 checkboxes per lesion)</td><td>Drawing for position, report for side</td></tr>
<tr><td>2</td><td>Lesion: histology type, x/y/z mm, EPE, PNI, Gleason patterns and %</td><td>Report</td></tr>
<tr><td>3</td><td>Specimen: pT, pN, pM, R, L, V, ISUP, ICD-O histology, node counts, <code>surgery_text</code></td><td>Report classification line</td></tr>
<tr><td>4</td><td>Date of surgery, type, lymphadenectomy, lesion count, surgeon, pathologist</td><td><b>Doctor</b> (not in reports)</td></tr></table>
<h2>Instruments</h2>
<p><code>surgery_c61</code>: one per surgery, <b>not</b> repeating. <code>surgery_c61_resected_lesion</code>: <b>repeating</b>, one per focus. No free-text note per lesion, no per-lesion grade group or margin.</p>
<h2>Sector codes (41 = 16 base + 12 mid + 12 apex + urethra)</h2>
<div class="warn">Import column = <code>sur_prostate_regions___&lt;code&gt;</code>. Write all 41 columns (1 or 0). Leave <code>all_sgm___1</code> at 0. <code>urethra</code> is a single code, no side. Anterior fibromuscular stroma is <b>as</b>, not afs.</div>
<table>{grid}<tr class="lv"><th colspan="3">+ urethra</th></tr></table>
<p><small>rs = patient right = viewer's left on the axial views, as on our sheets. Coronal and sagittal views carry no sector codes. Report text decides the side.</small></p>
<div class="cols"><div>
<h2>Lesion required fields</h2>
<table><tr><th>Field</th><th>Codes</th></tr>
<tr><td><code>hist_type_sur</code></td><td>1 Benign, 2 Carcinoma, 3 Neuroendocrine, 4 Sarcoma, 5 Haematolymphoid, 6 Metastasis, 7 Other</td></tr>
<tr><td><code>extracaps_ext</code></td><td>1 Yes, 2 Uncertain, 3 No, 4 Not specified</td></tr>
<tr><td><code>perineural_inv_sur</code></td><td>1 Yes, 2 Uncertain, 3 No, 4 Not specified</td></tr></table>
<p>Optional: <code>lesion_x/y/z_mm</code> (0 to 100), <code>gleason_prim|sec|tert_grade</code> (1 to 5) and <code>_perc</code> (0 to 100).</p>
</div><div>
<h2>Surgery required fields</h2>
<table><tr><th>Field</th><th>Codes</th></tr>
<tr><td><code>surgery_date</code></td><td>YYYY-MM-DD</td></tr>
<tr><td><code>surgery_type</code></td><td>1 Open, 2 RALP</td></tr>
<tr><td><code>total_number_lesion_surg</code></td><td>1 to 6, 7 Other (+ <code>_oth</code>)</td></tr>
<tr><td><code>lymphadenectomy</code></td><td>1 Performed, 2 Not performed</td></tr>
<tr><td><code>classify_r_surg</code></td><td>1 R0, 2 R1, 3 R2, 4 RX</td></tr>
<tr><td><code>classify_l_surg</code></td><td>1 L0, 2 L1, 3 LX</td></tr>
<tr><td><code>vascular_inv</code></td><td>1 V0, 2 V1, 3 V2, 4 VX</td></tr>
<tr><td><code>histol_post_surg</code></td><td>1 Carcinoma/epithelial, 2 NET, 3 Sarcoma, 4 Hematolymphoid, 5 Metastasis, 6 Other</td></tr>
<tr><td><code>node_no_surgery</code>, <code>node_positive_no_surgery</code></td><td>integers, required only if lymphadenectomy = 1</td></tr></table>
</div></div>
<p>pT: 1 pT0, 2 pT1a, 3 pT1b, 4 pT1c, 5 pT2a, 6 pT2b, 7 pT2c, 8 pT3a, 9 pT3b, 10 pT4, 11 pTX. pN: 1 pN0, 2 pN1, 3 pNX. pM: 1 pM0, 2 pM1a, 3 pM1b, 4 pM1c, 5 pMX. ISUP 1 to 5.</p>
<h2>Import rules</h2>
<ul>
<li>One row per instance. Surgery row: repeat columns blank. Lesion row: <code>redcap_repeat_instrument=surgery_c61_resected_lesion</code>, <code>redcap_repeat_instance=n</code>.</li>
<li>Raw codes, not labels. Checkbox cells 1 or 0. Dates YYYY-MM-DD.</li>
<li><code>new</code> as instance number <b>adds</b> lesions again on every re-import. Use explicit numbers when re-running.</li>
<li>Blank cells do not clear existing values (default). Use the data comparison table before saving.</li>
<li>Mark machine drafts form status 1 (Unverified), not 2.</li>
<li>Token for the API stays in the environment, never in Git.</li>
</ul>
<h2>Open with the doctor</h2>
<ul><li>Do benign marks (zánět) get a lesion instance with Benign?</li><li>One instance per focus or per side?</li><li>Axes of x/y/z.</li><li>Where per-focus grade group goes (no field).</li></ul>
</html>"""
open(f"{OUT}/handout.html","w").write(page)
print(len(page))
