import { adaptAnalysis } from "../analysis.js";

/** Browser runner supplies the synthetic fixture, its exact UTF-8 text and sectors. */
export async function runAnalysisTests(raw, reportText, sectors) {
  let passed = 0;
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const clone = value => structuredClone(value);
  const options = extra => ({ caseId: "DEMO-ANALYSIS", reportText, ...extra });
  const test = async (name, run) => {
    try { await run(); passed += 1; }
    catch (error) { throw new Error(`${name}: ${error.message}`); }
  };
  const rejected = async (input, configuration = options(), sectorInput = sectors) => {
    let error;
    try { await adaptAnalysis(input, sectorInput, configuration); } catch (caught) { error = caught; }
    assert(error instanceof Error, "Invalid input must fail explicitly");
    return error;
  };
  const replaceHash = async (input, newText) => {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(newText));
    const hash = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
    input.for_text_sha256 = hash;
    input.response.source_text_sha256 = hash;
  };
  const focus = (state, id = "focus-a") => state.lesions.find(lesion => lesion.id === id);

  await test("Synthetic per-focus patterns and missing mandatory fields", async () => {
    const state = await adaptAnalysis(raw, sectors, options());
    assert(state.schemaVersion === "doctor-review-analysis-v1" && state.recordId === "", "Start with an empty explicit REDCap identity");
    assert(state.lesions.length === 2 && state.lesions.every(lesion => lesion.reviewed === false), "Two unreviewed report foci");
    assert(focus(state).values.gleason_prim_grade === "3" && focus(state).values.gleason_sec_grade === "4", "Map supported raw per-focus patterns");
    assert(focus(state, "focus-b").values.gleason_prim_grade === "", "Do not propagate patterns between foci");
    for (const lesion of state.lesions) {
      for (const field of ["hist_type_sur", "extracaps_ext", "perineural_inv_sur", "gleason_prim_perc", "gleason_sec_perc"]) {
        assert(lesion.values[field] === "", `${field} must not receive a default, inference or negative`);
      }
    }
  });
  await test("Unknown axes stay empty; textual location never fabricates sectors", async () => {
    const state = await adaptAnalysis(raw, sectors, options({ showcase: true }));
    for (const lesion of state.lesions) {
      assert(lesion.regions.length === 0, "No assignments means no sectors, even in showcase");
      assert(["x", "y", "z"].every(axis => lesion.values[`lesion_${axis}_mm`] === ""), "Dimension order does not establish axes");
      assert(lesion.issues.some(issue => issue.message.includes("axis")), "Axis ambiguity requires an issue");
    }
  });
  await test("Raw JSON, evidence, confidence, unavailable statuses and specimen scope", async () => {
    const original = JSON.stringify(raw);
    const state = await adaptAnalysis(raw, sectors, options());
    assert(JSON.stringify(state.sourceAnalysis) === original && JSON.stringify(raw) === original, "Preserve every raw value without mutation");
    assert(state.sourceAnalysis.response.observations.some(observation =>
      observation.property === "grade_group" && observation.subject_id === "specimen-1"), "Retain specimen grade group");
    for (const lesion of state.lesions) {
      assert(!("isup" in lesion.values) && !("grade_group" in lesion.values), "No specimen grade group leakage");
      assert(lesion.sourceObservations.every(observation => observation.subject_id === lesion.id), "Only own per-focus observations");
      for (const observation of lesion.sourceObservations) {
        const source = raw.response.observations.find(item => item.id === observation.id);
        const { evidence, ...rest } = observation;
        assert(JSON.stringify(rest) === JSON.stringify(source), "Do not merge confidence with status/basis/value");
        assert(evidence.length === (source.evidence_ids ?? []).length, "Resolve all evidence IDs");
        for (const anchor of evidence) {
          const { source_text_sha256, ...sourceAnchor } = anchor;
          assert(source_text_sha256 === raw.for_text_sha256, "Evidence retains exact source hash");
          assert(JSON.stringify(sourceAnchor) === JSON.stringify(raw.response.evidence.find(item => item.id === anchor.id)), "Preserve raw quotation/offsets");
        }
      }
    }
    focus(state).sourceObservations[0].value.original_wording = "changed local display copy";
    assert(JSON.stringify(raw) === original && JSON.stringify(state.sourceAnalysis) === original, "Editable display data must not mutate raw provenance");
    const input = clone(raw);
    input.response.observations.push({
      id: "synthetic-unavailable", subject_id: "focus-a", property: "dimensions",
      status: "not assessed", basis: "explicit", value: null, evidence_ids: ["e-size-a"],
      unavailable_reason: "Synthetic test status", certainty: { extraction: "low", interpretation: "high" },
    });
    const unavailable = focus(await adaptAnalysis(input, sectors, options())).sourceObservations.find(item => item.id === "synthetic-unavailable");
    assert(unavailable.status === "not assessed" && unavailable.value === null &&
      unavailable.certainty.extraction === "low" && unavailable.certainty.interpretation === "high", "Keep unavailable status and independent confidence");
  });
  await test("Explicit demo assignments are clearly fabricated and block review", async () => {
    const state = await adaptAnalysis(raw, sectors, options({
      showcase: true, demoAssignments: { "focus-a": ["pzpl_mid_ls"], "focus-b": ["pza_apex_rs"] },
    }));
    assert(state.showcase === true && state.sourceBinding === "showcase-unlinked", "Never claim model/scan binding");
    assert(focus(state).regions.join(",") === "pzpl_mid_ls" &&
      focus(state, "focus-b").regions.join(",") === "pza_apex_rs", "Use only exact parent-supplied demo assignments");
    for (const lesion of state.lesions) {
      assert(lesion.issues.some(issue => issue.message.includes("unlinked")), "Every showcase lesion warns of unlinked scans");
      for (const code of lesion.regions) {
        assert(lesion.issues.some(issue => issue.showcaseOnly === true &&
          issue.regionCodes.includes(code) && issue.message.includes("fabricated") &&
          issue.resolved === false && issue.resolution === ""), "Every fabricated sector requires resolution");
      }
    }
    await rejected(raw, options({ demoAssignments: { "focus-a": ["pzpl_mid_ls"] } }));
    await rejected(raw, options({ showcase: true, demoAssignments: { "unknown-focus": [] } }));
    await rejected(raw, options({ showcase: true, demoAssignments: { "focus-a": ["PZpl_mid_left"] } }));
    await rejected(raw, options({ showcase: true, demoAssignments: { "focus-a": ["pzpl_mid_ls", "pzpl_mid_ls"] } }));
  });
  await test("Exact supported labelled axes can map, but fabricated labels cannot", async () => {
    const input = clone(raw);
    const dimension = input.response.observations.find(item => item.id === "obs-focus-a-dimensions");
    dimension.value.measurements = [{ value: 11, unit: "mm", axis: "x" }, { value: 15, unit: "mm", axis: "y" }];
    const unlabelled = await adaptAnalysis(input, sectors, options());
    assert(focus(unlabelled).values.lesion_x_mm === "", "Structured axis labels unsupported by the quotation are not sufficient");
    const quotation = "Synthetic labelled dimensions x=11 mm; y=15 mm.";
    const labelledText = `${reportText}${quotation}\n`;
    input.response.evidence.push({
      id: "e-synthetic-labelled-axes", text_layer_id: input.response.evidence[0].text_layer_id,
      page: 1, quotation, start_offset: [...reportText].length, end_offset: [...reportText].length + quotation.length,
    });
    dimension.evidence_ids = ["e-synthetic-labelled-axes"];
    dimension.value.original_wording = quotation;
    await replaceHash(input, labelledText);
    const mapped = await adaptAnalysis(input, sectors, options({ reportText: labelledText }));
    assert(focus(mapped).values.lesion_x_mm === "11" && focus(mapped).values.lesion_y_mm === "15" &&
      focus(mapped).values.lesion_z_mm === "", "Map only explicit mm x/y axes; never fabricate a third dimension");
  });
  await test("Input extraction issues are retained and require fresh resolution", async () => {
    const input = clone(raw);
    const issue = { id: "synthetic-attribution", kind: "unresolved_attribution",
      summary: "Synthetic attribution conflict", evidence_ids: ["e-gleason"],
      alternative_subject_ids: ["specimen-1", "focus-b"] };
    input.response.issues.push(issue);
    const state = await adaptAnalysis(input, sectors, options());
    for (const lesion of state.lesions) {
      const retained = lesion.issues.find(item => item.sourceIssue?.id === issue.id);
      assert(retained && retained.resolved === false && retained.resolution === "" &&
        JSON.stringify(retained.sourceIssue) === JSON.stringify(issue), "Specimen/global issues must not disappear");
      assert(retained.evidence[0].quotation === "Gleason 3+4=7", "Retain issue evidence");
    }
  });
  await test("Unknown subjects, evidence and dependencies fail explicitly", async () => {
    for (const mutate of [
      input => { input.response.subjects[1].parent_id = "missing"; },
      input => { input.response.subjects[1].evidence_ids = ["missing"]; },
      input => { input.response.observations[0].subject_id = "missing"; },
      input => { input.response.observations[0].evidence_ids = ["missing"]; },
      input => { input.response.observations[0].derived_from = ["missing"]; },
      input => { input.response.coverage[0].subject_id = "missing"; },
      input => { input.response.issues.push({ id: "bad", summary: "Bad reference", evidence_ids: ["e-size-a"], alternative_subject_ids: ["missing"] }); },
      input => { input.response.issues.push({ id: "bad", summary: "Bad evidence", evidence_ids: ["missing"], alternative_subject_ids: ["focus-a"] }); },
      input => { input.response.evidence[0].quotation = "not the exact source"; },
      input => { input.response.subjects.push(clone(input.response.subjects[0])); },
      input => { input.response.observations[0].status = "absent"; },
    ]) {
      const input = clone(raw);
      mutate(input);
      await rejected(input);
    }
  });
  await test("Exact report hashes and known envelopes only", async () => {
    await rejected(raw, options({ reportText: `${reportText} ` }));
    for (const name of ["for_text_sha256", "response"]) {
      const input = clone(raw);
      if (name === "response") input.response.source_text_sha256 = "0".repeat(64);
      else input.for_text_sha256 = "0".repeat(64);
      await rejected(input);
    }
    await rejected(raw.response);
    await rejected({ text_layer: {}, extraction: raw.response });
    await rejected(raw, options(), sectors.slice(1));
    await rejected(raw, options(), sectors.map((sector, index) => index === 0 ? { ...sector, code: "guess" } : sector));
  });
  await test("Inferred/calculated patterns are preserved separately, never auto-filled", async () => {
    const input = clone(raw);
    for (const observation of input.response.observations) {
      if (["gleason_patterns", "gleason_score"].includes(observation.property)) observation.basis = "inferred";
    }
    const state = await adaptAnalysis(input, sectors, options());
    assert(focus(state).values.gleason_prim_grade === "" && focus(state).values.gleason_sec_grade === "", "No inferred pattern prefill");
    assert(focus(state).sourceObservations.some(observation => observation.basis === "inferred"), "Keep inferred observations");
    assert(focus(state).issues.some(issue => issue.message.includes("inferred")), "Inference requires review");
  });
  return { passed };
}
