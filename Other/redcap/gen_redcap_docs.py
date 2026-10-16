import csv, json, sys

ROOT = "/home/jindris/Projects/Rakathon26"
OUT = ROOT + "/Other/redcap"

# ---------- sector crosswalk ----------
sectors = json.load(open(f"{ROOT}/Other/reference/sectors.json"))["sectors"]
areas = json.load(open(OUT + "/redcap_areas.json"))  # code, label, x0,y0,x1,y1 in 513x631 frame


def bb(p):
    xs = [q[0] for q in p]
    ys = [q[1] for q in p]
    return min(xs), min(ys), max(xs), max(ys)


redcap_boxes = {a[0]: a[2:] for a in areas}
redcap_boxes["urethra"] = [405.1, 585.2, 423.1, 603.2]  # circle centre (414.1, 594.2) r 9, from the live form

ZONE = {
    "sv": "Seminal vesicle",
    "as": "Anterior fibromuscular stroma",
    "pza": "Peripheral zone, anterior",
    "pzpl": "Peripheral zone, posterolateral",
    "pzpm": "Peripheral zone, posteromedial",
    "tza": "Transition zone, anterior",
    "tzp": "Transition zone, posterior",
    "cz": "Central zone",
}
key_by_code = {}
for code, box in redcap_boxes.items():
    best = min(sectors, key=lambda k: sum(abs(u - v) for u, v in zip(bb(k["source_coordinates_px"]), box)))
    key_by_code[code] = (best["key"], best["name"], round(sum(abs(u - v) for u, v in zip(bb(best["source_coordinates_px"]), box)), 1))
rows = []
for code, (key, title, dist) in sorted(key_by_code.items(), key=lambda it: it[1][0]):
    if code == "urethra":
        zone, level, side = "urethra", "apex-to-base (single choice)", ""
        zname = "External urethral sphincter"
    else:
        zone, level, side = code.split("_")
        zname = ZONE[zone]
    rows.append(
        dict(
            redcap_code=code,
            import_column=f"sur_prostate_regions___{code}",
            ctsit_key=key,
            ctsit_title=title,
            zone=zone,
            zone_name=zname,
            level=level,
            side_code=side,
            patient_side={"rs": "right", "ls": "left", "": ""}[side],
            drawn_on_viewer=({"rs": "left", "ls": "right"}[side] if side else "centre"),
            bbox_distance_px=dist,
        )
    )
codes = [r["redcap_code"] for r in rows]
assert len(set(codes)) == 41, "crosswalk is not 1:1"
assert sorted(r["ctsit_key"] for r in rows) == list(range(1, 42))
with open(f"{OUT}/sector_crosswalk.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print("crosswalk rows", len(rows), "max bbox dist", max(r["bbox_distance_px"] for r in rows))

# ---------- field spec ----------
Y = "yes"
F = []


def add(inst, var, label, typ, req="", choices="", branch="", default="", src="", tier="", note=""):
    F.append(dict(instrument=inst, variable=var, label=label, type=typ, required=req,
                  choices=choices, branching=branch, default_annotation=default,
                  proposed_source=src, tier=tier, notes=note))


S = "surgery_c61"
add(S, "surgery_date", "Date of surgery", "text date_dmy (1900-01-01..today)", Y, src="doctor", tier=4,
    note="Not in any checked report. Import as YYYY-MM-DD.")
add(S, "surgery_type", "Type of surgery", "radio", Y, "1=Open surgery | 2=RALP", src="doctor", tier=4)
add(S, "total_number_lesion_surg", "Total number of operated lesions", "dropdown", Y,
    "1=1 | 2=2 | 3=3 | 4=4 | 5=5 | 6=6 | 7=Other", src="doctor (suggest from report)", tier=4,
    note="Specimen scope. Not the number of drawing marks.")
add(S, "total_number_lesion_surg_oth", "Total number of operated lesions (other)", "text integer 0..100", "",
    branch="[total_number_lesion_surg]='7'", default="@PLACEHOLDER", src="doctor", tier=4)
add(S, "lymphadenectomy", "Lymphadenectomy", "radio", Y, "1=Performed | 2=Not performed", src="doctor", tier=4,
    note="Not in any checked report. Drives the node fields.")
add(S, "surgeon_query", "Surgeon query", "sql autocomplete", "", src="doctor", tier=4,
    note="Value list is a server-side SQL query; raw values not inspected.")
add(S, "surgeon_other", "Surgeon other", "text", "", branch="[surgeon_query]='Other'", src="doctor", tier=4)
add(S, "pathologist_query", "Pathologist query", "sql autocomplete", "", src="doctor or report signature (unverified)", tier=4)
add(S, "pathologist_other", "Pathologist other", "text", "", branch="[pathologist_query]='Other'", src="doctor", tier=4)
add(S, "surgery_text", "Histological finding", "notes (free text)", "", src="report text (microscopic finding)", tier=3,
    note="Only free-text field in the two surgery instruments. Patient-linked text.")
add(S, "pt_surg", "pT", "dropdown", "",
    "1=pT0 | 2=pT1a | 3=pT1b | 4=pT1c | 5=pT2a | 6=pT2b | 7=pT2c | 8=pT3a | 9=pT3b | 10=pT4 | 11=pTX",
    src="report classification line", tier=3, note="Optional in REDCap.")
add(S, "pn_surg", "pN", "dropdown", "", "1=pN0 | 2=pN1 | 3=pNX", default="@DEFAULT='1'", src="report or doctor", tier=3,
    note="Default pN0 applies in the web form only, not on import.")
add(S, "pm_surg", "pM", "dropdown", "", "1=pM0 | 2=pM1a | 3=pM1b | 4=pM1c | 5=pMX", default="@DEFAULT='5'",
    src="report or doctor", tier=3, note="Default pMX applies in the web form only.")
add(S, "node_no_surgery", "Number of lymph nodes", "text integer 0..20", Y, branch="[lymphadenectomy]='1'",
    src="report or doctor", tier=3, note="Required only when lymphadenectomy = Performed.")
add(S, "node_positive_no_surgery", "Number of positive lymph nodes", "text integer 0..[node_no_surgery]", Y,
    branch="[lymphadenectomy]='1'", src="report or doctor", tier=3)
add(S, "classify_r_surg", "R- classification (resection margin)", "dropdown", Y,
    "1=R0 No residual tumor | 2=R1 Microscopic residual tumor | 3=R2 Macroscopic residual tumor | 4=RX Cannot be assessed",
    src="report classification line", tier=3)
add(S, "classify_l_surg", "L-invasion", "dropdown", Y,
    "1=L0 No lymphatic invasion | 2=L1 Lymphatic invasion present | 3=LX Cannot be evaluated",
    src="report classification line", tier=3)
add(S, "vascular_inv", "Vascular invasion", "dropdown", Y,
    "1=V0 No venous invasion | 2=V1 Microscopic venous invasion | 3=V2 Macroscopic venous invasion | 4=VX Cannot be evaluated",
    src="report classification line", tier=3)
add(S, "isup", "Grade group, ISUP", "dropdown", "", "1 | 2 | 3 | 4 | 5", src="report classification line", tier=3,
    note="Specimen scope. The lesion instrument has no grade-group field.")
add(S, "histol_post_surg", "Definitive histology (ICD-O)", "dropdown", Y,
    "1=Carcinoma/Epithelial tumor | 2=Neuroendocrine tumor | 3=Sarcoma / mesenchymal tumor | 4=Hematolymphoid tumor | 5=Metastasis | 6=Other malignant tumors",
    default="@DEFAULT='1'", src="report", tier=3)
add(S, "histol_post_surg_specify", "Definitive postoperational histology (ICD-O) - specification",
    "text, ontology MKN-O 3.2 (CZ)", "", default="@DEFAULT='81403 Adenokarcinom, NS'", src="report", tier=3,
    note="Stored value format (code only or code + label) not verified.")
add(S, "surgery_c61_complete", "Form status", "dropdown", "", "0=Incomplete | 1=Unverified | 2=Complete", src="workflow", tier=5,
    note="Suggest 1 (Unverified) for machine-drafted rows until a doctor confirms.")

L = "surgery_c61_resected_lesion"
add(L, "all_sgm___1", "All segments affected", "checkbox", "", "1=All segments affected",
    default="@IF clears it when a subset is chosen", src="drawing", tier=1,
    note="Web-form shortcut that checks 40 sectors (not urethra). On import write the sectors explicitly.")
add(L, "sur_prostate_regions___<code>", "Prostate regions (41 columns)", "checkbox, hidden, shown as image map", "",
    "see sector_crosswalk.csv", default="@HIDDEN; @CUSTOM_IMAGEMAP", src="drawing + report side", tier=1,
    note="1 = sector affected, 0 = not. One lesion instance holds one set of sectors.")
add(L, "hist_type_sur", "Type of histology", "dropdown", Y,
    "1=Benign | 2=Carcinoma | 3=Neuroendocrine tumor | 4=Sarcoma | 5=Haematolymphoid tumor | 6=Metastasis | 7=Other malignant tumors",
    default="@DEFAULT='2'", src="report", tier=2,
    note="'Benign' exists: open question whether non-tumour marks such as inflammation get an instance.")
add(L, "lesion_x_mm", "X-dimension of the lesion [mm]", "text number 0..100", "", src="report", tier=2,
    note="Axes are not defined in the form; the report often does not name them either.")
add(L, "lesion_y_mm", "Y-dimension of the lesion [mm]", "text number 0..100", "", src="report", tier=2)
add(L, "lesion_z_mm", "Z-dimension of the lesion [mm]", "text number 0..100", "", src="report", tier=2)
add(L, "extracaps_ext", "Extraprostatic extension", "dropdown", Y, "1=Yes | 2=Uncertain | 3=No | 4=Not specified",
    src="report", tier=2, note="Required. 'Not specified' is the only way to say not reported.")
add(L, "perineural_inv_sur", "Perineural invasion", "dropdown", Y, "1=Yes | 2=Uncertain | 3=No | 4=Not specified",
    src="report", tier=2)
add(L, "gleason_prim_grade", "Gleason primary score", "dropdown", "", "1 | 2 | 3 | 4 | 5", src="report", tier=2)
add(L, "gleason_prim_perc", "Gleason primary score (%)", "text number 0..100", "", src="report", tier=2)
add(L, "gleason_sec_grade", "Gleason secondary score", "dropdown", "", "1 | 2 | 3 | 4 | 5", src="report", tier=2)
add(L, "gleason_sec_perc", "Gleason secondary score (%)", "text number 0..100", "", src="report", tier=2)
add(L, "gleason_tert_grade", "Gleason tertiary score", "dropdown", "", "1 | 2 | 3 | 4 | 5", src="report", tier=2)
add(L, "gleason_tert_perc", "Gleason tertiary score (%)", "text number 0..100", "", src="report", tier=2)
add(L, "sgm_affected", "Segments affected (calc)", "calc, hidden", "", src="derived", tier=5,
    note="sum of 40 sector checkboxes + ((all_sgm+1)*100). Not in the import template.")
add(L, "surgery_c61_resected_lesion_complete", "Form status", "dropdown", "", "0=Incomplete | 1=Unverified | 2=Complete",
    src="workflow", tier=5)

P = "patients_personal_data"
add(P, "record_id", "Record ID", "text, identifier", "", src="REDCap", tier=0,
    note="Format seen: CMP- plus 7 digits. How new IDs are issued was not checked.")
add(P, "name", "Name", "text, identifier", Y, src="report header (production)", tier=0)
add(P, "surname", "Surname", "text, identifier", Y, src="report header (production)", tier=0)
add(P, "birth_id", "Birth certificate number (rodne cislo)", "text, identifier, @CHARLIMIT=10", Y,
    src="report header (production)", tier=0, note="Format without the slash. dob_* fields are computed from it.")
add(P, "subject_id", "Patient ID (CLADE IS)", "text, identifier", "", src="hospital", tier=0,
    note="Probably the code shown in brackets next to the record ID (not confirmed).")

with open(f"{OUT}/surgery_fields.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(F[0]))
    w.writeheader()
    w.writerows(F)
print("fields", len(F))

# ---------- example import (synthetic, no patient data) ----------
sector_cols = [f"sur_prostate_regions___{c}" for c in codes]
head = ["record_id", "redcap_repeat_instrument", "redcap_repeat_instance",
        "surgery_date", "surgery_type", "total_number_lesion_surg", "lymphadenectomy",
        "pt_surg", "classify_r_surg", "classify_l_surg", "vascular_inv", "isup",
        "histol_post_surg", "surgery_c61_complete",
        "hist_type_sur", "lesion_x_mm", "lesion_y_mm", "lesion_z_mm", "extracaps_ext", "perineural_inv_sur",
        "gleason_prim_grade", "gleason_prim_perc", "gleason_sec_grade", "gleason_sec_perc",
        "surgery_c61_resected_lesion_complete"] + sector_cols


def row(**kw):
    r = {h: "" for h in head}
    r.update(kw)
    return [r[h] for h in head]


on = lambda *cs: {f"sur_prostate_regions___{c}": "1" for c in cs}
off = {c: "0" for c in sector_cols}
r1 = row(record_id="TEST-0001", surgery_date="2026-01-15", surgery_type="2", total_number_lesion_surg="2",
         lymphadenectomy="2", pt_surg="8", classify_r_surg="1", classify_l_surg="1", vascular_inv="1", isup="2",
         histol_post_surg="1", surgery_c61_complete="1")
base = {c: "0" for c in sector_cols}
l1 = dict(base)
l1.update(on("pzpl_apex_rs", "pzpl_mid_rs", "pzpl_base_rs"))
l2 = dict(base)
l2.update(on("pza_mid_rs"))
r2 = row(record_id="TEST-0001", redcap_repeat_instrument="surgery_c61_resected_lesion", redcap_repeat_instance="1",
         hist_type_sur="2", lesion_x_mm="12", lesion_y_mm="14", lesion_z_mm="9", extracaps_ext="4",
         perineural_inv_sur="4", gleason_prim_grade="3", gleason_prim_perc="90", gleason_sec_grade="4",
         gleason_sec_perc="10", surgery_c61_resected_lesion_complete="1", **l1)
r3 = row(record_id="TEST-0001", redcap_repeat_instrument="surgery_c61_resected_lesion", redcap_repeat_instance="2",
         hist_type_sur="2", lesion_x_mm="3", extracaps_ext="4", perineural_inv_sur="4",
         surgery_c61_resected_lesion_complete="1", **l2)
with open(f"{OUT}/example_import.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(head)
    w.writerows([r1, r2, r3])
print("example cols", len(head))
