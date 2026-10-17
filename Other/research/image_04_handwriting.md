# Handwritten notes on the drawings

## Recommendation

Start with the offline Kraken `PP-OCRv6 small` line recognizer. Its 13.1 MB Apache-2.0 model includes Czech handwriting data and reports Czech results. The test material is medieval, not clinical. Its reported 45.72% word error rate is too high for unreviewed entry. Use it to suggest readings only, with a doctor confirming every value. [Model card](https://zenodo.org/records/21788405).

For a short probe, manually identify each note region, run the recognizer on each text line locally, and keep the raw output, model version, image region, and reviewed reading. Compare exact whole-note match and character error by note type. Keep units, punctuation, and uncertain characters.

Use Moravian Library's TuzkaOCR `handwritten` domain as the local comparator if its model licence permits the intended research use. Its pipeline is CPU-first and about 12 MB, but its weights are CC BY-NC-SA 4.0 and its public README gives no Czech handwriting accuracy score. If that licence does not fit, use manual transcription as the fallback. PaddleOCR's small Latin model can provide a second check for numbers and Latin text, but its Czech support is not evidence of Czech handwriting accuracy.

**Failure signal.** Skip model prefill if exact whole-note accuracy is below 95% on the adjudicated set, or if it changes any number, unit, side, or negation. This is a proposed gate, not a measured result. Keep doctor review even if the gate passes. Abstain on unreadable or conflicting notes.

**Time estimate.** 2 to 3 hours for a 40-sheet probe, assuming the model is already available. Allow about 1 hour to transcribe and locate the roughly 50 notes, 30 to 60 minutes for local inference and comparison, and 30 to 60 minutes for adjudication. Installation time and any runtime issues are not measured.

## Drawing inventory

I reviewed all 40 full-page scans visually. The panel locations and ink colours below are approximate. I did not crop images or use OCR. Counts are manual: about 50 size-like inscriptions or fragments, including uncertain readings; P/L side-label sets on 20 sheets, with a second faint or duplicate pair on 0002, 0013, 0017, and 0027; one separate `L` and one possible `P` on 0022; about 30 visible arrow annotations; three Czech text groups; and three exclamation marks. I count a double-headed arrow as one. Some arrow strokes touch the outlines. The three text groups are `ZDE ZÁNĚT!`, a second `ZÁNĚT`, and `Vlevo!`. The exclamation marks include the isolated `!` on sheet 0027.

| Sheet | View or location | Handwritten annotation | Ink |
|---|---|---|---|
| 0001 | Axial side labels; base/coronal margin | `P`, `L`; `11 mm`; one size note unreadable beside an arrow | Pale yellow; pink |
| 0002 | Axial and coronal side labels; coronal/sagittal and mid views; lower margin | Two `P/L` pairs; `18 mm`; `15 mm`; blue note partly readable as `max. val. 12 mm` | Pink and pale yellow; blue lower note |
| 0003 | Axial side labels; apex | `P`, `L`; `20 mm` with arrow | Pale yellow; pink |
| 0004 | Mid | `5 mm?` | Pink |
| 0005 | Coronal; mid | `20 mm`; `12 mm?` | Pink |
| 0006 | Mid | `14 mm` | Pink |
| 0007 | Side labels; base and mid; coronal | `P`, `L`; `ZDE ZÁNĚT!`; `ZÁNĚT`; `24 mm`; `30 mm` | Pale yellow side labels; graphite words; pink dimensions |
| 0008 | Side labels; mid | `P`, `L`; `11 mm` | Pale yellow; pink |
| 0009 | Coronal side labels; mid and lower right | `P`, `L`; `7m?` (unit stroke faint); `5x4x7 mm` | Red labels; pink; pale yellow |
| 0010 | Apex | `11 mm` with horizontal arrow | Pink |
| 0011 | Coronal; mid | `25 mm` with vertical arrow; small `11 mm?` | Pink |
| 0012 | Coronal/apex margins; apex | `P`, `L`; adjacent note unreadable | Red labels; pink note |
| 0013 | Coronal side labels; apex | Two `P/L` pairs, one faint; `10 mm` with arrow | Graphite and pale yellow labels; pink |
| 0014 | Mid | `22 mm` with double-headed arrow | Red |
| 0015 | Mid | `25 mm` with horizontal arrow | Pink |
| 0016 | Side labels; coronal | `P`, `L`; `40 mm` with vertical double-headed arrow | Pale yellow; pink |
| 0017 | Coronal and axial side labels; mid | Two `P/L` pairs, one faint; `14 mm` with diagonal arrows | Graphite; pale yellow |
| 0018 | Base; mid | `5 mm?`; `3 mm?` | Pink |
| 0019 | Side labels; mid and apex | `P`, `L`; `20 mm`; `12 mm`, each with an arrow | Pale yellow; pink |
| 0020 | Base/mid boundary; apex | `12 mm` with horizontal arrow; `23 mm` with vertical arrow | Pink |
| 0021 | Side labels; apex | `P`, `L`; `10 mm` | Pale yellow; pink |
| 0022 | Coronal and seminal-vesicle views; lower margin | Blue `L`; possible pale yellow `P`; lower glyph unreadable; `25 mm` with horizontal arrow | Blue; pale yellow; pink |
| 0023 | Coronal side labels; sagittal | `P`, `L`; `20 mm` with vertical arrow | Graphite; pink |
| 0024 | Side labels; sagittal; seminal-vesicle margin | `P`, `L`; size note partly unreadable, possibly `20 mm`, with vertical arrow; another note unreadable | Pale yellow; pink |
| 0025 | Coronal side labels; coronal margin; lower right | `P`, `L`; `30 mm` with vertical arrow; tiny lower glyph unreadable | Ochre/brown; pink or ochre |
| 0026 | Side labels; coronal | `P`, `L`; `Vlevo!` | Pale yellow; red |
| 0027 | Coronal side labels; sagittal and apex margins | Two `P/L` pairs; `!`; `cca 25 mm` with arrow; `16m?` (unit stroke uncertain) | Red and pale yellow labels; pink notes |
| 0028 | Coronal | `30 mm` with vertical arrow | Pink |
| 0029 | Apex | `15 mm` | Pink |
| 0030 | Base/mid boundary | `40 mm` with horizontal arrow | Pink |
| 0031 | Apex | Note unreadable; appears to include an arrow and a size | Pink |
| 0032 | Side labels; base | `P`, `L`; `20 mm` with vertical arrow | Pale yellow; pink |
| 0033 | Mid | `11 mm` with arrow | Pink |
| 0034 | Mid | `19 mm` with arrow | Pink |
| 0035 | Apex | `11 mm?` | Pink |
| 0036 | Side labels; coronal; lower margin | `P`, `L`; `60 mm` with vertical arrow; blue lower glyph unreadable, possibly `T` | Pale yellow; pink; blue |
| 0037 | Side labels; mid | `P`, `L`; `30 mm` with arrow | Pale yellow; pink |
| 0038 | Mid | `20 mm` with arrow | Pink |
| 0039 | Mid | `19 mm` with double-headed arrow | Pink |
| 0040 | Mid | `20 mm` with vertical arrow | Pink |

## Recognition options

| Option | Size and licence | Czech handwriting evidence | CPU fit and use |
|---|---|---|---|
| **Kraken 7.1 with PP-OCRv6 small** | 3.24M parameters; 13.1 MB weights; Apache-2.0. Kraken is the inference engine. | Czech data includes medieval corpora. The model card reports 922 held-out lines, 9.61% character error and 45.72% word error. Its random page split does not separate documents, so the score is in-domain and may be optimistic. | Small line recognizer. CPU use is plausible, but no local timing was measured. Best first offline probe. [Model card](https://zenodo.org/records/21788405), [Kraken inference docs](https://kraken.re/main/user_guide/inference.html). |
| **TuzkaOCR handwritten** | About 12 MB of pipeline model files. Code is Apache-2.0; model files are CC BY-NC-SA 4.0. | Explicit Czech handwriting domain. No public accuracy metric for modern clinical notes. | CPU-first ONNX pipeline with page layout and line recognition. Good local comparator, subject to the model licence. [Moravian Library repository](https://github.com/moravianlibrary/TuzkaOCR). |
| **PERO-OCR** | BSD-3-Clause software. Public package model set includes layout analysis and European printed OCR. | BUT documents a Czech newspaper model and a handwritten-text demo/API. The public local package does not document a downloadable Czech handwriting model. Demo terms and access need review. | Local installation is possible, but not a ready documented Czech handwriting checkpoint. Do not send these scans to the web demo. [PERO repository](https://github.com/DCGM/pero-ocr), [BUT data and demo listing](https://www.vut.cz/ai/vyzkum/data). |
| **PaddleOCR PP-OCRv5 Latin mobile** | 14 MB recognition model; PaddleOCR is Apache-2.0. | The official language list includes Czech. The Latin model documentation does not report Czech handwriting results. Separate PP-OCRv5 documentation mentions handwriting support for other model scenarios. | Small CPU model. Published CPU timing is 21.20 ms or 5.32 ms in the project's benchmark, not a measurement on this host. Useful as a numeric/Latin comparator. [Model list](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md), [language list](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md). |
| **TrOCR small / base handwritten** | The small card does not state weight size or licence. The base card lists 0.3B parameters and MIT. | The model cards say they are fine-tuned on IAM handwriting. That is English evidence, not Czech. The models take single text lines. | CPU inference is possible in principle, but the base is much larger than Kraken's small line model. Not a Czech candidate without adaptation and evaluation. [Small model card](https://huggingface.co/microsoft/trocr-small-handwritten), [base model card](https://huggingface.co/microsoft/trocr-base-handwritten). |
| **Qwen3.5-4B or similar local VLM** | 4B parameters; Apache-2.0. At 16-bit weights, roughly 8 GB before runtime memory. Quantization reduces weights but adds runtime overhead. | Model supports image input, but its card provides no Czech handwriting accuracy evidence. A VLM may guess text that is not present. | Possible on a capable CPU with quantization, likely slower than a line recognizer. Use only for a second opinion, never as the source of truth. [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-4B). |

PERO is the only listed option with a BUT handwritten-text demo, but its public local model is print-focused. eScriptorium is a transcription and review interface built around Kraken. It is not itself a Czech model. The Kraken model can be used directly for a smaller offline probe. [eScriptorium prediction docs](https://escriptorium-tutorial.readthedocs.io/en/latest/predict/).

## Cloud zero-retention options

These are conditional provider options, not accuracy recommendations. The existing [provider shortlist](zdr_provider_shortlist.md) has the detailed terms and sources. The current research sent no scans to a provider.

| Provider | Published condition | Fit for this task |
|---|---|---|
| OVHcloud AI Endpoints | EU service. The standard API contract excludes input/output storage and reuse. Batch is excluded. | Assess first if the exact vision model and its endpoint fit. Verify the hospital contract. [Product](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/), [contract](https://contract.eu.ovhapis.com/1.0/pdf/Conditions_particulieres_OVH_Stack-we.pdf). |
| Mistral | Approved paid organisations can enable ZDR for supported stateless APIs, including `/v1/ocr`. Files, Batch, Agents, Conversations, and Labs are excluded. | Good documented OCR endpoint candidate. Handwriting accuracy and exact model fit remain unverified. [ZDR guide](https://docs.mistral.ai/admin/monitor-comply/zero-data-retention). |
| Nebius Token Factory | Organisation-level ZDR setting. Public endpoints use dynamic global routing; dedicated endpoints can use a fixed EU region. | Candidate if a supported vision model and fixed region are confirmed. [Legal guide](https://docs.tokenfactory.nebius.com/legal/legal-quick-guide). |
| OpenAI API, Gemini on Vertex AI, Azure OpenAI / Foundry | ZDR or modified abuse monitoring requires provider approval and exact project, endpoint, region, and feature settings. | Conditional only. Check the selected image endpoint, caching, logging, exceptions, and contract. See the [provider shortlist](zdr_provider_shortlist.md). |
| Scaleway Generative APIs | Shared service policy allows request retention for up to two weeks in limited cases and its cache cannot be disabled. | Does not meet an unconditional zero-retention requirement. Its managed API differs from self-hosting on its GPU infrastructure. [Privacy policy](https://www.scaleway.com/en/docs/generative-apis/reference-content/data-privacy/). |

## Schema entry

This follows [STRUCTURE.md](../../data_schema/STRUCTURE.md).

- Keep report extraction and drawing extraction independent. Create the drawing's `diagram mark` subject separately from the text note. Add a note observation to the mark only when an arrow or clear placement supports that link. Record an uncertain link as inferred with low certainty, or leave the note unlinked if its mark is unclear.
- Use an image evidence anchor for the note's bounding box or polygon. Include the nearby arrow or mark when it supports the association. Record page coordinates and their origin, units, and axis directions. Keep panel context such as base, mid, apex, or sagittal view.
- For a readable inscription, preserve the original string as a `Text` value with basis `explicit`. Add a separate `Quantity` or `Dimensions` observation only when the number and unit are clear. If you standardize it, use basis `normalized` and keep the original wording, including `cca`, `16m`, or `5x4x7`. Do not infer axes from an ordered tuple.
- For text that exists but cannot be read reliably, use status `unreadable` and no value. Keep its image evidence. Do not use `not reported` for visible unreadable writing.
- Store arrow or outline geometry separately from a note's meaning. A handwritten size does not calibrate the drawing. Do not infer a lesion from a drawing mark alone.
- Keep `P/L` or `Vlevo` as drawing evidence. The report decides side. A disagreement raises a review issue.
- If the drawing says `7 mm` and the report says `5 mm`, keep both as separate observations with their own evidence and raise a review issue. Neither source overwrites the other. A doctor confirms the draft before export.

## Dated sources

Sources checked 2026-10-16. Model cards, official project repositories, technical documentation, and provider terms were used as primary sources.

- [PP-OCRv6 small model card](https://zenodo.org/records/21788405), published 2026-08-04. Size, Apache-2.0 licence, Czech data, and Czech error rates.
- [Kraken inference documentation](https://kraken.re/main/user_guide/inference.html). Line segmentation and recognition workflow.
- [TuzkaOCR repository](https://github.com/moravianlibrary/TuzkaOCR). CPU support, handwritten Czech domain, model size, and separate code/model licences.
- [PERO-OCR repository](https://github.com/DCGM/pero-ocr) and [BUT AI data page](https://www.vut.cz/ai/vyzkum/data). Public package models, project licence, and handwritten demo/API.
- [PaddleOCR model documentation](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md) and [Czech language list](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md).
- [Microsoft TrOCR small](https://huggingface.co/microsoft/trocr-small-handwritten) and [base handwritten model cards](https://huggingface.co/microsoft/trocr-base-handwritten), plus the [source repository](https://github.com/microsoft/unilm/tree/master/trocr).
- [Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B).
- [Mistral ZDR guide](https://docs.mistral.ai/admin/monitor-comply/zero-data-retention), [Nebius legal guide](https://docs.tokenfactory.nebius.com/legal/legal-quick-guide), [OVHcloud API product page](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/), and [Scaleway Generative APIs privacy policy](https://www.scaleway.com/en/docs/generative-apis/reference-content/data-privacy/).
- [Project zero-retention provider shortlist](zdr_provider_shortlist.md), checked 2026-10-16.
