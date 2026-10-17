# ZDR APIs and self-hosted inference for ProstaPaper

Checked 2026-10-16. Recommendation: assess OVHcloud AI Endpoints and Mistral's EU API first. For self-hosting, compare Scaleway and OVHcloud EU GPU instances. Nebius is another documented ZDR option, with dedicated endpoints when a fixed EU region is required. These are candidates for evaluation, not approved hospital deployments or accuracy winners.

The requirement is no retention or provider reuse of inference content, including future benchmark material. Hospital storage of source documents and reviewed REDCap entries is separate. This research submitted no patient content, rented no GPU and inspected no customer account.

## EU-based API candidates

- **OVHcloud AI Endpoints.** Its product page says the service runs in the EU, does not use customer data for training and retains only billing necessities. More concretely, the current Public Cloud contract, Appendix 10 sections 2 and 5, excludes storage, backups and reuse of inputs and outputs for the standard service. **Batch is expressly excluded.** This is a strong candidate for the requested policy, subject to the actual hospital contract and supported model. [Product](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/), [contract, pages 52 and 53](https://contract.eu.ovhapis.com/1.0/pdf/Conditions_particulieres_OVH_Stack-we.pdf).
- **Mistral.** ZDR is available by approval on paid plans for supported stateless endpoints, including chat completions and OCR. Stored Files, Agents, Conversations and Batch files are excluded. The regional EU endpoint is `api.eu.mistral.ai` for supported models. Avoid Labs/Preview models whose separate terms can permit training despite other preferences. [ZDR guide](https://docs.mistral.ai/admin/monitor-comply/zero-data-retention), [regional inference](https://mistral.ai/cloud/inference/), [special model terms](https://legal.mistral.ai/terms/commercial-terms-of-service/).
- **Nebius Token Factory.** The contracting entity is Nebius B.V. in the Netherlands. Its legal guide documents an organisation-level ZDR account switch, no retention beyond request processing and no training/improvement when enabled. Public endpoints have dynamic Global routing. A dedicated endpoint offers a fixed chosen region, including EU configurations. The guide expressly permits health/special-category data subject to the customer's lawful basis and obligations. [Legal guide, sections 4, 5 and 10](https://docs.tokenfactory.nebius.com/legal/legal-quick-guide), [terms](https://docs.tokenfactory.nebius.com/legal/terms-of-service).

## US-provider services with European inference options

- **OpenAI API.** Approved ZDR organisations can use eligible endpoints with limitations. European processing requires the appropriate regional project and contractual controls; image support requires additional approval. Check caching, image exceptions and the chosen model rather than treating the ZDR organisation switch as a blanket guarantee. [Official data controls](https://developers.openai.com/api/docs/guides/your-data).
- **Gemini on Google Cloud / Vertex AI.** Google publishes a route to ZDR involving the applicable abuse-logging exemption, disabled content logging/storage and disabled caching. Some advanced models/features cannot meet ZDR; the current Frontier Models terms also require content retention for designated models. Select a supported EU regional deployment and verify all features. This is distinct from the Gemini Developer API terms. [ZDR configuration](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention), [service terms, sections 20 and 34](https://cloud.google.com/terms/service-terms).
- **Azure OpenAI / Microsoft Foundry.** Microsoft offers approved modified abuse monitoring that omits the content storage and human review used for that monitoring. Its documentation explains how to verify `ContentLogging=false`. Use an appropriate regional or EU DataZone deployment, rather than Global, for EU inference. Stateful features and previews require separate checks. [Data handling and regions](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy), [approval requirements](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/abuse-monitoring).

An EU processing region and an EU-based provider are different properties. European inference does not by itself establish that every support, metadata or subprocessor operation remains in the EU.

## A material exception

**Scaleway Generative APIs** advertise ZDR by default, but their detailed policy permits retaining full HTTP request content for up to two weeks to investigate certain failures or misuse. Automatic ephemeral caching cannot be disabled on the shared service. Therefore do not mark the standard shared API as meeting an unconditional zero-retention requirement. This finding concerns its managed API, not running our own server on Scaleway GPU infrastructure. [Detailed privacy policy](https://www.scaleway.com/en/docs/generative-apis/reference-content/data-privacy/).

## Running a model on a rented server

Yes. MOÚ can rent GPU infrastructure and operate a downloadable model there. With ordinary inference software, the model developer does not need to receive the hospital's requests. MOÚ controls its serving application's logging, caching, temporary files and network access. The infrastructure host's DPA, administrator access, storage and backups still need assessment; self-hosting is not proof of zero infrastructure retention.

Scaleway, OVHcloud and Runpod are compared in the companion [EU GPU hosting note](eu_gpu_hosts_zdr.md), including official regional and model-card links. Runpod has EU locations but is a US-based provider; a location label alone does not settle the contractual region commitment.

Open-weight vision models such as Qwen3-VL and selected Mistral Small models are self-hosting candidates. Check the exact release's licence and runtime. No accuracy, GPU capacity, throughput or price was measured for our scans in this research.

## What remains to verify

For the shortlisted service: actual model and vision support, customer-account ZDR state, retention exceptions and caches, EU endpoint configuration, no-reuse terms, DPA/subprocessors and hospital acceptance. For self-hosting: live GPU availability, exact zone and host terms, software retention behaviour and model accuracy on the supplied scans. No vendor approval or availability outcome is assumed.
