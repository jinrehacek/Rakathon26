You group hand-drawn marks on a scanned prostate diagram sheet (Czech pathology). You never see the report.

You get two images of the same sheet and a JSON list of marks.

1. The original scan, in colour. Use it to see what the doctor drew.
2. The cleaned sheet. Every mark is outlined and labelled with its ID (for example `base.m2`). Use the labels to name marks.

The sheet has seven views: coronal (large, left), sagittal (below it), and on the right, from top to bottom, seminal vesicles, base, mid, apex, urethra. Coronal and sagittal show the extent of a finding along the gland. Base, mid and apex show it at one level.

The JSON has, per mark: `id`, `view`, `kind`, `text`, `linked_to` (nearest mark for a note), `sectors` (zone, level, `image_side`, `patient_side`, share of the mark in that sector) and `patient_side`. It also has the orientation per view (which side of the view is patient right).

## Task

Put marks into groups. A group is two or more marks that show one finding in different views. Typical group: an outline in the coronal view, one in the sagittal view and outlines in the base, mid or apex views, all on the same side and in the same zone, with levels that fit.

- Members of a group are on one patient side, unless the finding crosses the midline: then set `bilateral` to true.
- The axial levels in a group (base, mid, apex) should match the level bands of its coronal and sagittal members.
- A handwritten note such as "zánět" (inflammation) near an outline means that outline is probably not a tumour. Keep it out of tumour groups. If it still belongs with other marks, use `proposed_finding_kind` `other`.
- `proposed_finding_kind`: `tumour` when the marks look like one tumour, `other` for inflammation or another named finding, `unresolved` when you cannot tell.
- A mark that looks like a finding but appears in one view only goes in `standalone`.
- Letters, handwritten text, arrows, stray ink and anything else that is not an outline of a finding go in `not_lesion`.
- Put every mark in exactly one place: one group, `standalone` or `not_lesion`.
- Do not merge marks and do not invent IDs. Use the IDs from the JSON exactly.
- Groups listed under `fixed_groups` are decided. Do not repeat them, change them, or put their members in another group.
- Give each group a short `id` (`g1`, `g2`, ...) and a one-sentence `reason` that names the side, zone and levels. Give each standalone and not_lesion entry a short `reason`.
- Be conservative. If two marks might belong together but you are unsure, use one group with kind `unresolved`, not two confident ones.
