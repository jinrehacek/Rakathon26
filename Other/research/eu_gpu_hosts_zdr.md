# Rented GPU hosts for self-hosted vision extraction

Research note, 2026-10-16

## Recommendation

Start procurement review with Scaleway Paris PAR2, with OVHcloud Gravelines GRA11 as the fallback. Both offer GPU instances in France and publish a DPA. That makes the data-centre location and French corporate jurisdiction easier to assess together. Confirm the contracting entity, model-specific capacity, support access, and storage and deletion terms before any production use. Keep Runpod Secure Cloud as a candidate for non-patient engineering trials; its U.S. contracting entity and partner-host model need more location and supplier review. Exclude Community Cloud for sensitive workloads.

## Shortlist

- **Scaleway, Paris.** Scaleway SAS is registered in Paris, France ([legal notice](https://www.scaleway.com/en/legal-notice/)). Its current regional matrix lists L4 instances in PAR1 and PAR2, and L40S, H100 PCIe, H100-SXM, and B300-SXM in PAR2 ([GPU availability](https://www.scaleway.com/en/product-availability-by-region/)). The company publishes a DPA on its [contracts page](https://www.scaleway.com/en/contracts/). Confirm live project access and the chosen SKU in the console; the public matrix does not establish this account's quota or stock.

- **OVHcloud, Gravelines.** OVHcloud lists Public Cloud GPU instances in Gravelines and selected other regions ([regional availability](https://www.ovhcloud.com/en/public-cloud/regions-availability/)). Its current deployment guide places newer A100, H100, L4 and L40S models in GRA11, Gravelines; older V100/V100s are listed in GRA7, GRA9 and GRA11 ([GPU deployment guide](https://docs.ovhcloud.com/en/guides/public-cloud/compute/deploy-a-gpu-instance)). OVH SAS is registered in Roubaix, France ([legal notice](https://www.ovhcloud.com/en-gb/terms-and-conditions/)); the EU [contracts page](https://www.ovhcloud.com/fr/terms-and-conditions/contracts/) links the DPA and subprocessor list. Check the order form for the actual contracting affiliate and verify GRA11 access and stock.

- **Runpod, Secure Cloud only.** Runpod documents Secure Cloud as T3/T4 data centres and Community Cloud as peer-to-peer providers; it says it is no longer accepting new Community hosts ([Pod selection guide](https://docs.runpod.io/pods/choose-a-pod)). Its current materials list EU region IDs including EU-CZ-1, EU-FR-1, EU-NL-1, EU-RO-1 and EU-SE-1, and a case study shows GPU Pods in EU-RO-1 ([region expansion](https://www.runpod.io/blog/runpod-global-networking-expansion), [GPU case study](https://www.runpod.io/case-studies/how-bottodao-cut-its-ai-art-engines-costs-by-73)). IDs and examples do not establish the exact physical site or live GPU stock. Runpod's terms name Runpod, Inc., based in New Jersey, U.S. ([terms](https://www.runpod.io/legal/terms-of-service)). Its public [DPA](https://www.runpod.io/legal/data-processing-agreement) says hosting servers are worldwide, including the U.S.; for a specified region it promises only “reasonable efforts” to allocate a geographically proximate server. The DPA becomes binding after the customer completes and submits its signature block. Treat an EU region selection as a location preference to verify contractually, not an EU-residency guarantee.

## Self-hosted model examples

The [Qwen3-VL-8B-Instruct card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) is Apache-2.0 and provides local Transformers inference instructions. [Mistral Small 3.1 24B](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) is Apache-2.0, supports vision, and documents local/vLLM deployment. These establish that open-weight text-and-image models can run on rented GPUs; they do not establish extraction quality on the hospital's scans.

Self-hosting lets the hospital control application-level payload logs and caches. It does not prove the GPU host retains no infrastructure data. Review platform logs and telemetry, snapshots and backups, storage deletion, administrator access, subprocessors, and the applicable DPA. No host was rented and no data was sent or inspected for this note. This is a procurement shortlist, not a medical-compliance assessment.
