# ProstaPaper

Rakathon 2026, MOÚ Brno, 24 hours.

For each radical prostatectomy the pathologist leaves a typed Czech report and a hand-annotated PI-RADS v2.1 drawing. Someone retypes both into the COMPARE registry (REDCap 17.3.7, project 64). We draft that record from the two scans, and a doctor confirms or fixes it.

## Goal

Transfer existing pathology findings into structured registry fields for future research. The output is a draft for a doctor to review before export. It does not diagnose a patient, recommend treatment or guide clinical care.

Use existing models for extraction. Training and fine-tuning are outside the hackathon scope.

## Inputs

The paired report and drawing scans are in `Other/`, which is not git-ignored.

### Report

The report covers the microscopic finding, the conclusion ("Závěr") and a classification line with pT, L, V, R and grade group. Surgery date, surgery type and lymphadenectomy were missing from every report checked, so the doctor has to enter them.

### Drawing

- Same printed template on every sheet. Coronal and sagittal views on the left. Seminal vesicles, then axial Base, Mid and Apex on the right, with zone labels and dashed sector lines.
- Ink colour has no fixed meaning: red, pink, faint yellow, pencil, often mixed.
- Marks: closed outlines, open arcs, small circles, size arrows, handwritten sizes and notes, P/L letters. Some marks are not tumour, for example "zánět" (inflammation).
- Side comes from the report. In axial views patient right is on the viewer's left on all 5 sheets checked. The coronal view is sometimes mirrored.
- Text and drawing can disagree, for example front versus back. The doctor resolves it.
- Report and drawing are the two sides of one sheet. Red marks showing through on report scans are the drawing's ink.

## Target fields

Two instruments: `surgery_c61`, one per surgery, and the repeating `surgery_c61_resected_lesion`, one per focus. The drawing feeds `sur_prostate_regions`, a 41-choice sector checkbox per lesion. Everything else comes from the text.

## Hackathon deliverable

1. Extract findings from each report and drawing using the concepts in `data_schema/STRUCTURE.md`, retaining source evidence, uncertainty and missing information.
2. Match report findings to drawing marks without losing either source's observations or conflicts.
3. Present both scans, the draft record, a clickable sector map and a queue of uncertainties and conflicts for doctor review.
4. Export the reviewed record as a REDCap import CSV.

## Production requirements

Confirmed by the user on 2026-10-16:

- The current hackathon samples are fully anonymised and supplied without usage restrictions. Production will use identifiable hospital reports.
- The result must remain associated with the patient, and the REDCap record must include rodné číslo.
- MOÚ will operate the production service and own its hosting and API accounts. We supply the software.
- Zero retention of patient content by an external model API provider is mandatory. The data are also intended for future model benchmarking, so benchmark material must be protected against provider retention and reuse. The hospital still stores source records and identified REDCap entries.
- Provider reuse of submitted cases, prompts or outputs for model training or improvement must be prohibited. Verify this separately from retention controls for the selected service, model and features.
- Hosting and processing locations should minimise hospital approval and compliance work. An EEA-only restriction has not been selected.

Production architecture, hosting, the model provider, processing locations, the exact scope and configuration of zero retention, and approval of the specific deployment remain open.
