# Vision-language model role and shortlist

Research date: 2026-10-16. This is a paper shortlist, not a benchmark. No model was run and no scan was sent. Existing provider and GPU-host research is in [zdr_provider_shortlist.md](zdr_provider_shortlist.md) and [eu_gpu_hosts_zdr.md](eu_gpu_hosts_zdr.md).

## Recommendation

**Hackathon shortlist, unvalidated:** (1) Gemini 3.8 Flash for low cost and documented box/polygon output; (2) Claude Sonnet 5.5 for image reading plus constrained JSON; (3) Qwen3-VL Plus for low price and visual sector reading. Qwen's exact hosted model is not covered by Alibaba's published ZDR list. Use it only where the data route is authorized. If scans must stay local, first probe MiniCPM-V 4.5, Gemma 4 E4B, and Qwen3-VL 4B on the hackathon host. CPU speed is unknown.

**Production shortlist with documented ZDR paths:** (1) Claude Sonnet 5.5 on the direct stateless Messages API with approved ZDR; (2) GPT-6.1 Sol on an approved OpenAI API organization with image-input ZDR approval, store=false, and EU residency; (3) Gemini 3.8 Flash on Vertex AI with the abuse-logging exception, caching disabled, and model/feature eligibility confirmed. These are conditional routes, not hospital approvals. Do not use Gemini 4 Argon: Google's terms put it in the Frontier Models class with up to 30-day content retention. Alibaba's ZDR model list does not cover Qwen3-VL. [3, 4, 7, 10, 16]

Keep the VLM downstream of computer vision. CV proposes mark candidates and computes geometry, masks, and overlap with the 41 sectors. The VLM labels each supplied candidate, reads legible text, names visible sector labels as a cross-check, and reports disagreement. It does not make or edit geometry, determine side, or decide that a mark is a lesion. Keep report subjects separate from drawing marks until the matching step. [Project schema, project pipeline]

## Cloud models

Prices below are estimates per request with one image, not the complete three-image prompt. The page is 2400 x 3500 pixels. The axial crop is 900 x 900. Each request adds 600 text input tokens and 300 output tokens for JSON. The proposed original-plus-mask view and crop add their own image charges. Prices exclude cache discounts, tools, retries, taxes, and OpenAI/Google regional uplifts unless stated. They are not quotes. Image tokenization differs by provider.

| Exact model ID | Image handling, grounding, JSON | Approx. price: sheet / crop | ZDR and no-training position |
|---|---|---:|---|
| gemini-3.8-flash | Inline image or Files API. Native box_2d and polygon mask output use normalized 0-1000 coordinates. JSON Schema response format is supported. Ignore generated geometry in this pipeline. [1] | $0.0030 / $0.0026 on Vertex EU. Uses documented 258-token tiles and 10% EU price uplift. [2] | Vertex ZDR route requires the abuse-logging exception and cache controls. Avoid Files and other stateful features. Google Cloud says customer data is not used to train without permission. Confirm this model and call path in the MOÚ account. [3, 4] |
| gemini-4-argon | Image input and structured JSON. Gemini documents native box_2d and polygon masks for its multimodal models. The concrete schema example is 3.8 Flash, not Argon. [1] | $0.0080 / $0.0069 at the introductory Vertex EU rate, valid through 2026-11-30. Then about $0.0161 / $0.0138. [2] | **Not eligible.** Google designates Argon a Frontier Model. Its terms allow up to 30 days of prompt/output retention, overriding the general Vertex ZDR route. [4] |
| claude-opus-5-5 | Inline image or image URL in Messages. No native box or mask response. Coordinates can be requested as text. Structured Outputs supports JSON Schema. Its schema cache can persist up to 24 hours, so keep schemas static and PHI-free. [5, 6, 7] | $0.0147 / $0.0128. Standard image tier assumption. | ZDR requires account approval. Use stateless Messages and inline images. Opus 5.5 is not listed among the covered models. No training by default; feedback opt-in is separate. [7] |
| claude-sonnet-5-5 | Same image and JSON options as Opus. No native grounding endpoint. Keep the schema static and PHI-free; the schema cache can persist up to 24 hours. [5, 6, 7] | $0.0073 / $0.0064. | Same ZDR conditions. This is the preferred Claude production candidate by cost. [7] |
| claude-haiku-5-5 | Same image and JSON options as Opus. No native grounding endpoint. Keep the schema static and PHI-free; the schema cache can persist up to 24 hours. [5, 6, 7] | $0.00037 / $0.00032. | Same ZDR conditions. Low price does not establish adequate accuracy. [7] |
| gpt-6.1-sol | Image URL or base64 image input. No native box/mask output found. Structured Outputs supports constrained JSON. [8, 9] | About $0.010 / $0.0062 using Astra's documented high-detail sizing and multiplier as a proxy. Excludes regional uplift. | API inputs are not used for training by default. ZDR needs organization approval. Image input has an additional approval condition. Confirm EU residency and endpoint eligibility. [10] |
| gpt-6-astra | Same image and JSON interface as Sol. No native grounding endpoint found. [8, 9] | About $0.051 / $0.031 at high detail. Excludes regional uplift. | Same ZDR and image-input conditions as Sol. [10] |
| gpt-6-luna | Same image and JSON interface as Sol. No native grounding endpoint found. [8, 9] | About $0.00051 / $0.00031 using Astra's documented high-detail sizing and multiplier as a proxy. Excludes regional uplift. | Same ZDR and image-input conditions as Sol. [10] |
| perceptron-mk1.5 | Accepts images. Typed perception output includes points, boxes, polygons, clips, and tracks. SDK supports structured values and normalized coordinates. [11] | **Not found.** Published token rates are $0.15/M input and $1.50/M output, but image token accounting is unpublished. | **Not found.** No primary-source ZDR or no-training terms located. Not a production candidate. |
| moondream3.1-9B-A2B Cloud | Image API supports query, detection, points, and segmentation paths. Responses are structured JSON. [12] | About $0.0009 / $0.0008 under the assumed 1,500 / 1,000 image tokens. Actual image usage is provider-reported. The product page says $0.30/M input and $1/M output; its generic docs page lists $2.50/M output. Confirm price before use. [13] | Moondream's cloud announcement says it does not train on customer data and does not persist data after returning responses. A formal ZDR commitment for the synchronous API was not found. Batch results are retained for seven days. Confirm the current service terms before production use. [14] |
| qwen3-vl-flash-2026-01-22 | Image URL or base64. JSON output is supported in non-thinking mode. Qwen can emit normalized 0-1000 boxes and points in its own token format. It has no verified arbitrary polygon mask endpoint. [15] | About $0.00028 / $0.00019 on the Frankfurt route. | Model Studio says no training without separate consent. Standard prompts/responses may be retained for up to 30 days. Its ZDR list does not name qwen3-vl; ZDR does not cover an unlisted model. Not production eligible. [16] |
| qwen3-vl-plus-2025-12-19 | Same image, box/point, and JSON options as Flash. [15] | About $0.0011 / $0.00076 on the Frankfurt route. | Same retention and training position as Qwen3-VL Flash. Not production eligible. [16] |
| Other hosted Qwen vision IDs | **Not found** as additional hosted vision IDs with all requested price, JSON, grounding, and ZDR details. | Not found. | Do not assume Qwen3-VL inherits the separate qwen-flash ZDR listing. [16] |

### Cost assumptions

- Gemini uses the documented crop-unit formula: a 2400 x 3500 page is about six 258-token tiles; a 900 x 900 crop is about four. Gemini EU figures add 10% to public model rates. Argon intro rates change after 2026-11-30. [2]
- OpenAI uses high-detail 32-pixel patches after resizing. Astra allows up to 2,500 patches and uses a 1.2 multiplier, so the full page is estimated at the patch cap and the crop at about 1,010 image tokens. The Sol and Luna image-sizing rules are not listed separately in the guide. Their estimates use the Astra rule as a proxy. Rates are $2/$10 per million tokens for Sol, $10/$50 for Astra, and $0.10/$0.50 for Luna. [8, 9]
- Claude uses the standard image tier. The image budget is 1,568 tokens for the page and about 1,089 for the crop. High-resolution options may cost more on supported models. Rates are $4/$20, $2/$10, and $0.10/$0.50 per million tokens for Opus, Sonnet, and Haiku. [5]
- Qwen estimates use its published pixel-to-token formula, Frankfurt standard prices, 600 text-input tokens, and 300 output tokens. The default image pixel cap is applied to the full page. [15]
- Moondream does not publish a fixed image-token formula. The estimate assumes 1,500 image tokens for the sheet and 1,000 for the crop. It is a planning value only. [13]
- Perceptron does not publish image tokenization. Price per sheet and crop is therefore not calculable from current public rates. [11]

## Local open weights

RAM estimates assume 4-bit weights unless noted. They are estimates, not measured host runs. Feasibility assumes CPU-only inference within an 8 vCPU / 15 GB RAM budget. Runtime, KV cache, image size, and concurrent processes reduce available memory. CPU speed is not established for any row.

| Family and sizes | Runtime and 15 GB CPU feasibility | Grounding output |
|---|---|---|
| Qwen3-VL: 2B, 4B, 8B, 32B, 30B-A3B, 235B-A22B | Transformers, vLLM, and SGLang. 2B/4B quantized models should fit. 8B may fit with limited headroom. 30B and larger do not fit in 15 GB at 4-bit. CPU generation speed unmeasured. [17] | Can emit point/box tokens with normalized 0-1000 coordinates. JSON is prompt/runtime constrained. No polygon mask guarantee. |
| Moondream 3.1 9B-A2B | Photon targets NVIDIA Ampere+ or Apple Silicon. The published weights are about 10.5 GB. Not a practical fit with runtime and KV cache in 15 GB CPU RAM. [18] | Native point, bounding-box, and SVG-path segmentation tasks. |
| Gemma 4: E2B, E4B, 12B, 26B-A4B, 31B | LiteRT-LM, llama.cpp, Transformers, and vLLM. Official Q4 memory figures are 2.9, 4.5, 6.7, 14.4, and 17.5 GB. E2B/E4B/12B are the practical CPU candidates. [19] | No dedicated grounding protocol found. Request labels and JSON only. |
| GLM-V: GLM-4.6V-Flash 9B; GLM-4.1V 9B; hosted 106B | Official Transformers/vLLM paths. A 9B Q4 weight set is roughly 5-6 GB before vision encoder and KV cache. Memory may fit, but a reliable 8-vCPU CPU path and speed were not established. [20] | No verified native box/polygon schema. Prompted JSON or textual coordinates only. |
| InternVL3.5: 1.06B, 2.35B, 4.73B, 8.53B, 15.12B, 21B-A4B, 30.85B-A3B, 38.4B, 240.7B-A28B | Transformers, vLLM, and LMDeploy. Small 1B-4.7B variants are the best fit. 8.5B Q4 may fit with little headroom. 15B+ is not a practical 15 GB CPU choice. No CPU throughput benchmark found. [21] | No dedicated structured grounding endpoint verified. Use prompted JSON only. |
| MiniCPM-V 4.5 8B | Transformers and llama.cpp. The official CPU guide gives an 8 GB memory configuration. A quantized build is a plausible 15 GB CPU candidate, but expect unmeasured slow generation. [22] | General VQA. No native box or mask output confirmed. Use candidate IDs and prompted JSON. |
| Molmo2 4B/8B, Molmo-O 7B, MolmoPoint 8B | Transformers and vLLM. A Q4 4B/7B/8B model is a plausible memory fit. CPU speed and high-resolution memory use are unmeasured. [23] | MolmoPoint returns point locations. It is not a polygon or mask substitute. Other Molmo models can answer pointing tasks; use only as a proposal. |

**Local shortlist:** MiniCPM-V 4.5 is the clearest CPU-runtime candidate. Gemma 4 E4B is the easiest small-weight option. Qwen3-VL 4B is the best grounding-oriented small model. None has measured accuracy or throughput on this host.

## Prompting evidence and failure limits

- **Set-of-Mark overlays:** The SoM paper reports GPT-4V referring-expression comprehension at 86.4% REC and 75.6% segmentation mIoU with numbered masks, versus 25.7% direct coordinate grounding in its comparison. A later study found plain markers ineffective for some models and tasks. Use numbered candidates as a probe, not a guarantee. [24, 25]
- **Crop and zoom:** CropVLM reports SmolVLM benchmark averages increasing from 28.45 to 38.13 at 512 px, 44.55 to 50.89 at 1024 px, and 50.16 to 52.64 at 2048 px. Full image plus crop beat crop-only. Pass the whole page and a high-resolution axial crop. [26]
- **CV mask beside the original:** No controlled result was found for this exact pairing on medical drawings. Show the original beside a clearly labelled CV mask to make disagreement inspectable. Do not show only the mask. This is our design choice, not a proven gain. [24]
- **Self-consistency:** SCoOP reports hallucination-detection AUROC 0.866 on ScienceQA, versus 0.732-0.757 for its baselines. This is multi-VLM pooling, not a medical drawing study. As a cheap review signal, compare three independent calls or three views and flag any disagreement. Do not average their sector IDs or treat verbal confidence as calibrated. [27]
- **Constrained JSON:** Gemini, OpenAI, and Claude offer schema-constrained output. JSONSchemaBench tested six constrained-decoding systems over 10,000 schemas. Syntax control improves parseability; it does not establish that an image claim is correct. [6, 8, 28]
- **Thin lines:** In a line-intersection task at 0.005 canvas width, four tested VLMs scored 45.00%, 67.55%, 45.22%, and 75.83%. This is direct evidence against trusting hairline geometry. Faint handwritten strokes need separate validation; no matching quantitative study was found. [29]
- **Counting and spatial relations:** UniBench evaluates 59 VLMs and finds counting remains a broad weakness. On VSR, human accuracy exceeds 95%, while the reported leading model is around 70%. What’sUp found 56% for fine-tuned BLIP against 99% for humans. Sector naming must be reviewed against CV and the overlay. [30, 31, 32]
- **Fine detail:** Last Visible Pixel reports perception saturation around 12 pixels, while counting, ordering, and spatial reasoning still fail at larger sizes. Preserve original resolution for crops and do not infer precision from a fluent answer. [33]

## Proposed prompt

> You inspect one radiology drawing view. Candidate mark IDs come from the computer-vision stage. The input shows the original view, a numbered 41-sector overlay, and the CV mask beside the original. Label each supplied candidate as lesion_outline, arrow_or_size_line, text, non_tumour_note, other, or uncertain. Transcribe only text you can read. For each candidate, name sector labels that appear to touch it by reading the numbered overlay. Treat your sector list as a visual cross-check, not as geometry. Compare your reading with the supplied CV sector list and report disagreements.
>
> Do not add candidates. Do not decide whether a lesion or tumour exists. Do not infer side, patient orientation, diagnosis, size, or physical scale. Do not create, change, or describe coordinates, contours, or mask geometry. Do not let a drawing mark overwrite report text. If you cannot read or decide, use unreadable or needs review. Cite the supplied evidence IDs. Return only the required JSON.

Pass the page, one axial crop, and the side-by-side original/mask view. Use high-resolution crop input for faint text. Candidate IDs should be drawn by CV, not generated from model geometry. Keep the numbered sector labels large enough to read.

## Proposed JSON shape

Use the project's schema terms. Every observation cites evidence. The model proposal stays separate from accepted extraction. Geometry remains in the CV record and is not copied into this JSON.

~~~json
{
  "view_id": "axial-01",
  "candidate_marks": [
    {
      "candidate_mark_id": "cv-mark-07",
      "subject_kind": "diagram_mark",
      "identification_basis": "proposed",
      "observations": [
        {
          "property": "mark_type",
          "status": "recorded",
          "basis": "inferred",
          "value": "lesion_outline",
          "evidence_ids": ["original-view-01", "cv-mask-07"],
          "certainty": {
            "extraction_certainty": "high",
            "interpretation_certainty": "medium",
            "explanation": "The outline is visible, but its type is uncertain."
          },
          "review_status": "needs review"
        },
        {
          "property": "transcribed_text",
          "status": "unreadable",
          "basis": "explicit",
          "evidence_ids": ["axial-crop-01"],
          "certainty": {
            "extraction_certainty": "low",
            "interpretation_certainty": "unassessed",
            "explanation": "Text is present but cannot be read."
          },
          "review_status": "needs review"
        },
        {
          "property": "sectors_touched",
          "status": "recorded",
          "basis": "inferred",
          "value": ["12", "13"],
          "evidence_ids": ["numbered-overlay-01", "cv-mask-07"],
          "certainty": {
            "extraction_certainty": "high",
            "interpretation_certainty": "medium",
            "explanation": "The displayed sector labels are legible, but contact is uncertain."
          },
          "review_status": "needs review"
        }
      ],
      "cv_cross_check": {
        "cv_sector_ids": ["12"],
        "vlm_sector_ids": ["12", "13"],
        "agreement": false
      },
      "issues": ["sector_disagreement"]
    }
  ]
}
~~~

The proposed keys are not database keys from the conceptual schema. Map them to its subjects, observations, evidence, and views. Certainty records extraction and interpretation separately, with an explanation. Use the schema's status, basis, certainty, and review-status terms. Use not reported with no value when a property is not mentioned. Use absent only for an explicit negative. A model proposal should remain needs review; certainty is qualitative and not calibrated. [Project schema]

## Sources

Sources checked on 2026-10-16. Product claims link to vendor documentation or model cards. Research claims link to papers.

1. [Gemini image understanding, object detection, segmentation, and JSON](https://ai.google.dev/gemini-api/docs/image-understanding); [Gemini model list](https://ai.google.dev/gemini-api/docs/models)
2. [Google Vertex AI generative AI pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing); [Gemini 3.8 Flash on Vertex](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash); [Google Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
3. [Vertex AI zero data retention](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention)
4. [Google Cloud service terms, Frontier Models](https://cloud.google.com/terms/service-terms)
5. [Claude model overview and pricing](https://platform.claude.com/docs/en/models/opus-5-5/overview); [Claude vision and image token limits](https://platform.claude.com/docs/en/build-with-claude/vision)
6. [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
7. [Claude API data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention); [Claude training policy](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training)
8. [OpenAI model catalog](https://developers.openai.com/api/docs/models); [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol); [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra); [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
9. [OpenAI image input and patch calculation](https://developers.openai.com/api/docs/guides/images-vision); [OpenAI API pricing](https://platform.openai.com/pricing)
10. [OpenAI API data controls and ZDR](https://developers.openai.com/api/docs/guides/your-data)
11. [Perceptron Mk1.5 announcement](https://www.perceptron.inc/blog/introducing-perceptron-mk1-5); [official SDK](https://github.com/perceptron-ai-inc/perceptron)
12. [Moondream API docs](https://docs.moondream.ai/api/); [segmentation API](https://docs.moondream.ai/skills/segment/); [Moondream 3.1 model card](https://huggingface.co/moondream/moondream3.1-9B-A2B)
13. [Moondream 3.1 pricing](https://moondream.ai/pricing); [generic Moondream API pricing](https://docs.moondream.ai/pricing/)
14. [Moondream Cloud announcement and data statement](https://moondream.ai/blog/announcing-moondream-cloud); [Moondream Batch API retention](https://docs.moondream.ai/batch/); [Moondream terms](https://moondream.ai/terms)
15. [Alibaba Model Studio vision API](https://www.alibabacloud.com/help/en/model-studio/vision-model); [Qwen API input and JSON guide](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions); [Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
16. [Alibaba Model Studio retention policy, updated 2026-10-11](https://www.alibabacloud.com/help/en/model-studio/data-retention-policy); [Model Studio FAQ](https://www.alibabacloud.com/help/en/model-studio/faq-about-alibaba-cloud-model-studio)
17. [Qwen3-VL official repository](https://github.com/QwenLM/Qwen3-VL); [Qwen3-VL model collection](https://huggingface.co/collections/Qwen/qwen3-vl)
18. [Moondream 3.1 local model card](https://huggingface.co/moondream/moondream3.1-9B-A2B); [Moondream local runtime docs](https://docs.moondream.ai/)
19. [Gemma 4 model and memory guide](https://ai.google.dev/gemma/docs/core); [Gemma runtime guide](https://ai.google.dev/gemma/docs/run)
20. [GLM-V official repository](https://github.com/zai-org/GLM-V)
21. [InternVL3.5 technical report and model sizes](https://internvl.github.io/blog/2025-08-26-InternVL-3.5/); [InternVL3.5 8B model card](https://huggingface.co/OpenGVLab/InternVL3_5-8B)
22. [MiniCPM-V 4.5 official CPU and runtime guide](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/minicpm_v4dot5_en.md); [MiniCPM-V model card](https://huggingface.co/openbmb/MiniCPM-V-4_5)
23. [Molmo2 official repository and model cards](https://github.com/allenai/molmo2)
24. [Set-of-Mark Prompting](https://arxiv.org/abs/2310.11441)
25. [Contrastive Region Guidance](https://contrastive-region-guidance.github.io/)
26. [CropVLM](https://arxiv.org/abs/2511.19820)
27. [SCoOP uncertainty evaluation](https://arxiv.org/abs/2603.23853)
28. [JSONSchemaBench](https://arxiv.org/abs/2501.10868)
29. [Vision-Language Models Are Blind](https://openaccess.thecvf.com/content/ACCV2024/html/Rahmanzadehgervi_Vision-Language_Models_Are_Blind_ACCV_2024_paper.html)
30. [UniBench](https://arxiv.org/abs/2408.04810)
31. [Visual Spatial Reasoning benchmark](https://transacl.org/index.php/tacl/article/view/4275)
32. [What'sUp spatial relations benchmark](https://arxiv.org/abs/2310.19785)
33. [The Last Visible Pixel](https://arxiv.org/abs/2606.07861)

Local alignment sources: [TASK.md](../../TASK.md), [AGENTS.md](../../AGENTS.md), [data_schema/STRUCTURE.md](../../data_schema/STRUCTURE.md), and [IMAGE_PIPELINE.md](../IMAGE_PIPELINE.md).
