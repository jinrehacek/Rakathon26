# Central matching and assessment

`central` implements steps 3 and 4 in [CENTRAL-SPEC.md](../Other/CENTRAL-SPEC.md). It reads a complete `report-2` extraction and a `drawing-1` output, then writes a reviewable `combined-1` draft. It does not generate report extractions or export CSV.

Run from the repository root with its Python environment:

```sh
.venv/bin/python -m central <preprocess-case-id>
```

Inputs are `Other/output/report/<case>/report.json` and `Other/output/drawing/<case>/drawing.json`. The source paths must identify the same preprocessing case. Each run pins the resolved files and their SHA-256 hashes, writes a new folder under `Other/output/combined/<case>/`, and atomically updates the relative `latest` link. Existing runs remain inspectable.

The drawing contract is copied into this package, with its upstream revision recorded in the file. Central does not import the drawing pipeline. Report generation remains a separate task; the existing report extractor still writes its original contract.

## Two readings

The rules search all allowed focus-to-candidate assignments. Sector selection uses central's `rules-1` threshold, not the drawing extractor's thresholds or its mark-level REDCap list. Unmatched ink raises a question. A drawing-backed lesion proposal requires a report statement supporting lesion count or multifocality.

The second reading uses Gemini 3.8 Flash. Set `GEMINI_API_KEY` or `GOOGLE_API_KEY` in the process environment. It receives JSON with geometry, pixel counts and image data removed. It receives no scans. External processing must be authorized for the particular data; the hackathon approval in the spec does not authorize production records.

If the key is in the repository's existing `.env` file, load it with:

```sh
uv run --no-project --env-file .env .venv/bin/python -m central <case>
```

An unavailable or invalid LLM response leaves the rules draft and adds `llm_missing`. For an offline run:

```sh
.venv/bin/python -m central <case> --no-llm
```

Confidence is qualitative. Two models reading the same inputs do not provide independent source confirmation. Text-only fields retain their source certainty and a `single source` tag.

## Doctor decisions

Save a `decisions-1` file at `Other/output/combined/<case>/decisions.json`, then run the same command. Central carries forward decisions from the previous run and appends new IDs. Use a new decision ID for a later correction. Example:

```json
{
  "schema_version": "decisions-1",
  "decisions": [
    {
      "id": "review-1",
      "kind": "assign_mark",
      "target": {"focus": "focus-a", "mark": "mid.m1"},
      "value": null,
      "reviewer": "reviewer-id",
      "timestamp": "2026-10-17T12:00:00Z",
      "reason": "The mark belongs to focus A."
    }
  ]
}
```

Supported operations:

| Kind | Target | Value |
| --- | --- | --- |
| `assign_mark` | `focus`, `mark` | null |
| `reject_membership` | `focus`, `mark` | null |
| `reject_group` | `group` | null |
| `set_value` | `lesion`, `property` | Object with a schema `status` and typed `value` |
| `resolve_issue` | `issue` | Optional review explanation payload |

Use raw report subject IDs for `focus`, drawing mark IDs for `mark`, and IDs from the previous combined output for lesions and issues. A property override retains its original source assessment and the review record. Unavailable statuses carry no value.

To edit the sector set, use `set_value` with `target.property` set to `sectors`. Its value is `{"status":"recorded","value":{"type":"sectors","in":["pzpl_mid_rs"],"maybe":[]}}`. Central validates the codes against the registry crosswalk and retains the earlier proposal.

With unchanged input hashes, reruns fix prior assignments and apply the decisions. Rejected groups invalidate dependent memberships. With changed hashes, central starts a new matching attempt and retains decisions whose targets still exist. Missing targets raise information issues. Reruns retain the earlier LLM result as `before_decisions` and make no new model call. Reviewed targets use rules confidence; an LLM reading of changed inputs contributes only to history.

Once a run contains review history, removing or emptying `decisions.json` preserves that history and its fixed assignments. Change a reviewed assignment with a new decision. An unchanged ambiguous assignment retains its alternatives and review question until the doctor resolves it.

## Verification and probe

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use synthetic contracts and an injected Gemini transport. Local sample extractions, labels and scores belong under ignored `Other/output/`. The three-case evaluation is a non-expert probe. Its hand-written inputs and labels come from the same reader, so its scores do not estimate production extraction accuracy.

After writing per-case `labels.json` files and running those cases, score the pinned results with:

```sh
.venv/bin/python -m central.evaluation
```

Each reference file pins the report and drawing hashes. Uncertain labels and missing LLM readings are listed but excluded from the scored denominator. Scores are written to a new timestamped JSON file under `Other/output/central-eval/`.

The review UI projection and CSV export remain step 5 work. Registry handling of benign findings and bilateral foci remains open. Historical pT checks stay informational while the COMPARE TNM document is unverified.
