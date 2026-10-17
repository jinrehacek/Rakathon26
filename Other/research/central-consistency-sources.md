# Sources for the central consistency checks

Checked 2026-10-17 before `central/checks.py` was written. This note records the source and edition behind each check, and what could not be verified. It contains no case text and no patient data.

## Rules

| Rule id | Failure | Severity | Source | Edition |
| --- | --- | --- | --- | --- |
| `isup-grade-group` | Reported grade group differs from the group mapped from reported Gleason patterns | question | ISUP 2014 consensus; AJCC 8th edition grade groups | ISUP 2014; AJCC 8th |
| `pt2c-both-lobes` | pT2c with every located lesion and candidate on one side | info | AJCC 7th edition pT2c; NCI SEER\*RSA TNM v1.4 | AJCC 7th |
| `pt2ab-one-lobe` | pT2a or pT2b with lesions on both sides | info | AJCC 7th edition pT2a and pT2b; NCI SEER\*RSA TNM v1.4 | AJCC 7th |
| `pt3a-epe` | pT3a with extraprostatic extension recorded absent in every focus | info | AJCC 8th edition pT3a | AJCC 8th |
| `pt3b-seminal-vesicles` | pT3b with seminal vesicle invasion recorded absent | info | AJCC 8th edition pT3b | AJCC 8th |

## Grade group

The ISUP 2014 consensus created five grade groups and kept the Gleason score alongside them. The abstract records the 90% consensus and gives `Gleason score 3+3=6 (Grade Group 1)` as an example. The article is Epstein JI, Egevad L, Amin MB, Delahunt B, Srigley JR, Humphrey PA, Grading Committee, *The 2014 International Society of Urological Pathology (ISUP) Consensus Conference on Gleason Grading of Prostatic Carcinoma*, Am J Surg Pathol 2016;40(2):244-252, DOI [10.1097/PAS.0000000000000530](https://doi.org/10.1097/PAS.0000000000000530), [PubMed 26492179](https://pubmed.ncbi.nlm.nih.gov/26492179/).

The exact score-to-group mapping used by the check comes from the AJCC 8th edition presentation, page 7, [Prostate Staging, AJCC TNM Staging 8th Edition](https://www.facs.org/media/wjajnumr/ajcc-prostate-staging.pdf):

| Grade group | Gleason |
| --- | --- |
| 1 | 6 or less |
| 2 | 3+4=7 |
| 3 | 4+3=7 |
| 4 | 8 |
| 5 | 9 or 10 |

The check only compares values the report recorded. It does not infer a grade group when Gleason is missing, and it does not raise a failure when either value is `not reported`, `unreadable`, `not assessed`, `not applicable` or outside the table. Total 7 with a pattern pair other than 3+4 or 4+3 is left alone because the table does not define it. The check runs separately at focus scope and specimen scope. A focus grade group is never compared with the specimen Gleason.

## pT categories

AJCC 8th edition removed the pT2 substages. Page 4 of the AJCC presentation says that after radical prostatectomy, organ-confined disease is pT2 without pT2a, pT2b or pT2c subdivisions. Page 6 notes that the 7th edition used those three pT2 groups, while the 8th edition uses pT2 for all organ-confined post-surgical cases. The same page places extraprostatic extension, on one or both sides, in pT3a, and seminal vesicle invasion in pT3b.

REDCap project 64 still offers pT2a, pT2b and pT2c as separate choices. `Other/redcap/REDCAP.md` section 5 records the live choice list. The central checks therefore read a legacy pT2 substage when a report carries one, using the AJCC 7th edition side definitions. The NCI SEER\*RSA TNM v1.4 page reproduces those categories, [Pathologic T, TNM Data v1.4](https://staging.seer.cancer.gov/tnm/input/1.4/prostate/path_t/):

- pT2a: tumour involves one-half of one lobe or less.
- pT2b: tumour involves more than one-half of one lobe, but not both lobes.
- pT2c: tumour involves both lobes.

The check does nothing for a bare `pT2` without a substage. It does not compare clinical cT with pathology, and it does not compare the pT side rule with the drawing when a lesion or candidate has no known side.

## The COMPARE TNM document

`Other/redcap/REDCAP.md` section 5 says the Surgery C61 page carries `COMPARE_TNM_klasifikace.pdf` as an inline help attachment. The Codebook text only shows `(Attachment: COMPARE_TNM_klasifikace.pdf, Display format: Link)` at the TNM fields, with no file URL. The repository has no copy of the PDF. I did not log in to REDCap, read a token or open a patient record. A web search found no public copy.

The registry-specific pT coding is therefore unverified. The pT checks follow the published AJCC categories and stay at severity `info`, as `Other/CENTRAL-SPEC.md` requires. They never change a pT value. A registry guide that maps pT2a/b/c differently would need a source change and a new rule edition.

## Conservative reading

A failed check is a review prompt, not a corrected value. The implementation reads the supplied computation copy, including reviewer overrides that carry `review_decision`. It treats any unknown side, unassessed invasion property or unrecognised code as a reason not to raise a failure. The checks use these scopes:

- Grade group: each focus and the specimen, independently.
- pT2c: every lesion and drawing candidate with a location must have a known side before the one-side rule can fail.
- pT2a and pT2b: lesions only, because the rule is about where lesions sit. Candidate ink does not widen the check.
- pT3a: focus-level `extraprostatic_extension`. A specimen-level statement is not copied to a focus.
- pT3b: the specimen's `seminal_vesicle_invasion`. A present value in any focus does not substitute for it.

Sector sides come from the selected `in` sectors only. A `maybe` contact is unticked and does not make a lesion bilateral.

## Not verified

- The registry's own `COMPARE_TNM_klasifikace.pdf`.
- Whether the registry wants legacy pT2 substages from AJCC 7th or would rather drop them under AJCC 8th.
- Pathologist review of these rules. No pathologist has checked the implementation.
