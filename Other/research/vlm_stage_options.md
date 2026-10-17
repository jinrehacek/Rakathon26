# VLM stage options

Checked against official documentation on 2026-10-16. Planning research only. No model inference, scan upload, account changes or accuracy test ran. Read TASK.md, AGENTS.md, STRUCTURE.md, the image implementation plan and the earlier provider notes. Existing dirty and untracked work was left in place.

## Recommendation for the hackathon

Start the anonymous-scan probe with `gemini-3.1-flash-lite`, the lowest-priced generally offered stable Gemini vision model verified here. Compare a few difficult panels with `gemini-3.8-flash` before deciding that Lite is sufficient. `gemini-3.5-flash-lite` is Google's newer recommended Lite model for new projects, and is another sensible first choice if using the current Cloud deployment path. This is a proposed probe order, not a claim about accuracy or a selected production provider. [Gemini catalog](https://ai.google.dev/gemini-api/docs/models)

Keep model selection, provider route, image resolution and prompts configurable. The same model family through the Gemini Developer API and through Google Cloud has different retention terms. Test the same original and processed crops when comparing models. Otherwise a better crop can be mistaken for a better model.

## Exact Gemini candidates

All three accept images and support JSON Schema output. The exact stable IDs are shown below. Avoid `latest` aliases and obsolete preview IDs when recording an experiment. Google limits access to the cheaper legacy 2.5 models to established users, so they are not a dependable starting point for a new project. [3.1 Lite model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [3.5 Lite model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [3.8 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [catalog](https://ai.google.dev/gemini-api/docs/models)

| Stable API ID | Proposed use | Developer API Standard input / output USD per million tokens |
| --- | --- | --- |
| `gemini-3.1-flash-lite` | Lowest-cost initial probe | $0.25 / $1.50 |
| `gemini-3.5-flash-lite` | Newer Lite alternative | $0.30 / $2.50 |
| `gemini-3.8-flash` | Stronger comparison or escalation | $0.75 / $3.75 through 2026-12-31, then $1.50 / $7.50 |

These are published token rates, not case prices. Output includes thinking tokens. Crops, two passes, JSON length and retries change the total. They are not Cloud regional quotes. Do not use discounted Contributor pricing for protected benchmark material, since that tier permits product improvement use. [Pricing](https://ai.google.dev/gemini-api/docs/pricing)

Use schema-constrained JSON rather than asking for prose and parsing it afterwards. Gemini's documented configuration uses `response_mime_type: application/json` and `response_json_schema`. This constrains format, not the truth of sector assignments. [3.1 Lite example](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)

## Crop and resolution settings

Gemini 3 supports media resolution per input image. Published approximate image budgets are 280 tokens at `low`, 560 at `medium`, 1,120 at `high`, and 2,240 at per-item `ultra_high`. This is a model input budget, not the scan's stored resolution. Google recommends `high` for most image analysis. [Media resolution](https://ai.google.dev/gemini-api/docs/media-resolution)

For our probe, use `high` on each detailed panel and retain sufficient context to see its label and adjacent notes. If faint contact remains unreadable, try a tighter native-resolution crop or `ultra_high` before concluding that a larger model is needed. Keep the original scan in colour. These are proposed settings for our drawings, not measured improvements.

Use inline image bytes for the planned stateless route. Gemini supports inline images as well as uploaded Files. Files are stored resources with deletion and optional expiration metadata; do not treat a Files upload as equivalent to inline input. Inline input alone does not remove provider abuse logs or caches. [Image input](https://ai.google.dev/gemini-api/docs/image-understanding), [Files API](https://ai.google.dev/api/files)

## Gemini Developer API data handling

Under the general unpaid-service terms, Google may use inputs and outputs for improvement and human review. The terms expressly apply paid-service data-use provisions to EEA, Swiss and UK users even on unpaid quota. Paid API access requires an active billing-linked project and prohibits product improvement reuse of prompts and outputs. It still permits limited content logging for policy enforcement and legal disclosures, with transient storage or caching across Google's facilities. Paid therefore does not establish zero retention. Account geography and applicable terms were not inspected. [API terms](https://ai.google.dev/gemini-api/terms)

For the supplied anonymous hackathon material, the Developer API is a practical probe route once the user authorizes the concrete run. It is not established as satisfying TASK.md's production or protected-benchmark retention requirement. An anonymised sample can still be unsuitable for a particular provider route if the user wants to preserve it as a private benchmark.

## Google Cloud production candidate

Google now documents the former Vertex AI path under Gemini Enterprise Agent Platform. It prohibits training or fine-tuning with customer data without permission. Its ZDR route needs the applicable abuse-logging exemption, disabled request/response logging, and cache controls. Implicit caching includes memory and durable storage; disable both for our strict retention requirement. Avoid explicit caches, grounding and stored interactions. Interactions defaults to `store=true`; use stateless GenerateContent, or explicitly `store=false` if Interactions is selected. No hospital configuration or exemption was verified. [Cloud ZDR guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention)

For ordinary Google models under online Cloud terms, suspicious prompts can be retained for up to 90 days. Cloud Master Agreement customers are exempt from that prompt logging by default. Designated Frontier models have separate retention rules. The current abuse guide lists Gemini 4 Argon Cyber Permissive in that category, so the earlier note's blanket exclusion of all Argon use is too broad. A different definition of provider "ZDR" may permit customer-environment retention; our stated requirement still needs explicit contract confirmation. [Abuse monitoring](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/abuse-monitoring), [service terms section 34](https://cloud.google.com/terms/service-terms)

The current Cloud pages list both `gemini-3.5-flash-lite` and `gemini-3.8-flash` as GA with `eu` multi-region model availability, ML processing and Standard PayGo support. Do not assume a specific `europe-west*` endpoint from older model documentation. The 3.1 Lite Cloud region and account availability were not verified in this refresh. [Cloud 3.5 Lite](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite), [Cloud 3.8 Flash](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash)

## Non-Google fallback

`claude-sonnet-5-5` is a practical comparison model. Its published base price is $2 input and $10 output per million tokens. `claude-haiku-5-5` is the smaller option with published pricing from $0.10 input and $0.50 output. Both accept images and support constrained JSON via `output_config.format` or SDK parsing helpers. These are fallback candidates, not accuracy winners. [Model catalog](https://platform.claude.com/docs/en/models/overview), [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

Send inline base64 images to stateless Messages. Current Claude 4.7-and-later image processing supports up to a 2,576-pixel long edge and 4,784 visual tokens before downscaling. Its coordinate outputs remain approximate. [Vision guide](https://platform.claude.com/docs/en/build-with-claude/vision)

Anthropic requires organization-specific ZDR enablement. Messages is eligible; Files and Batch are excluded. Structured outputs retains only the JSON schema for up to 24 hours after last use, so keep schemas static and free of patient data. Sonnet and Haiku 5.5 are not on the current mandatory-retention Covered Models list. However, even ZDR permits legal retention and retaining safety-flagged inputs and outputs for up to two years. This is a conditional ZDR route, not an unconditional match for our requirement. [Retention and feature eligibility](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)

Commercial API inputs and outputs are not used for training by default. Feedback and explicit opt-ins change that; do not submit cases through feedback channels. [Training policy](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training)

## Decisions still needed

- Whether the first probe uses lowest-cost 3.1 Lite or newer 3.5 Lite, and whether the same selected model performs both independent image passes.
- Whether anonymised probe cases may be retained by the provider, or must also be preserved as private benchmarks.
- Whether stronger-model escalation is automatic, bounded, and allowed to leave unresolved issues.
- For production, MOÚ's exact provider contract, ZDR state, caching and log configuration, chosen model/features, region, and acceptance of any residual exceptions. None was established here.

The earlier image-model research also proposed passing only CV candidates and forbidding new marks. That conflicts with the agreed original-image pass in the implementation plan. The original pass must be allowed to find marks that CV missed. Keep report matching after independent drawing extraction under STRUCTURE.md.
