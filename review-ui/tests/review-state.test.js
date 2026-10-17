import { validateEvidence, createDoctorLesion, validSavedReview } from "../review-state.js";
import { stageRegion, pendingRegionCodes, documentRegions } from "../region-edits.js";
import { validateReview } from "../redcap.js";

/** Entirely synthetic browser tests; no patient content or external calls. */
export function runReviewStateTests(sectors) {
  let passed = 0;
  const groups = [];
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const clone = value => structuredClone(value);
  const test = (name, run) => {
    try { run(); passed += 1; groups.push(name); }
    catch (error) { throw new Error(`${name}: ${error.message}`); }
  };
  const context = {
    reportText: "🧪 Žluťoučký nález.",
    sources: { report: { sha256: "a".repeat(64) }, drawing: { sha256: "b".repeat(64) } },
    imageSizes: { report: { width: 120, height: 90 }, drawing: { width: 513, height: 631 } },
  };
  const text = () => ({
    kind: "text", source: "report", quotation: "Žluťoučký", start: 2, end: 11,
    basis: "explicit", reason: "Synthetic report confirms a focus.",
  });
  const image = (source = "report") => ({
    kind: "image_crop", source, sha256: context.sources[source].sha256,
    bounds: [0, 0, context.imageSizes[source].width, context.imageSizes[source].height],
    basis: "inferred", reason: "Synthetic crop reason.",
  });
  const absent = () => ({ kind: "absent", basis: "absent", reason: "Not reported in synthetic report." });
  const prediction = () => ({
    schemaVersion: "doctor-review-analysis-v1", caseId: "SYNTHETIC-STATE",
    showcase: true, sourceBinding: "showcase-unlinked",
    sourceAnalysis: { response: { synthetic: true, nested: { a: 1, b: 2 } } },
    reportText: context.reportText, recordId: "", lesions: [{
      id: "original-a", instance: 2, label: "Synthetic original", regions: [],
      values: {}, reviewed: false,
      sourceObservations: [{ id: "observation-a", value: { a: 1, b: 2 } }],
      issues: [{
        id: "issue-a", message: "Synthetic unresolved issue.", sourceRef: "Synthetic source",
        hint: "Synthetic hint", regionCodes: [], customDefinition: { a: 1, b: 2 },
        resolved: false, resolution: "",
      }],
    }],
  });
  const saved = original => ({ ...clone(original), reviewLog: [] });
  const valid = (draft, original) => validSavedReview(draft, original, sectors, context);
  const rejects = run => {
    let error;
    try { run(); } catch (caught) { error = caught; }
    assert(error instanceof Error, "Expected an explicit error.");
  };

  test("Immediate region edits are independent, reversible, persisted and export-blocking", () => {
    const original = prediction(), draft = saved(original), lesion = draft.lesions[0];
    const [a, b] = sectors.map(sector => sector.code);
    stageRegion(lesion, a, true);
    stageRegion(lesion, b, true);
    assert(lesion.regions.join() === [a, b].join() && pendingRegionCodes(lesion).length === 2,
      "Keep multiple region selections without replacing the earlier one.");
    assert(valid(draft, original), "Undocumented drafts must survive reload.");
    assert(validateReview(draft, sectors).some(error => error.includes("pending region edits")),
      "Undocumented assignments must block export.");
    stageRegion(lesion, a, false);
    assert(pendingRegionCodes(lesion).join() === b, "A net-zero toggle must clear only that edit.");
    documentRegions(lesion, text());
    assert(!pendingRegionCodes(lesion).length && lesion.regionEvidence[b].quotation === text().quotation,
      "Group documentation must anchor each remaining change.");
    assert(valid(draft, original), "Documented region edits must restore.");
    stageRegion(lesion, b, false);
    assert(lesion.pendingRegionEdits[b].from === true && lesion.pendingRegionEdits[b].to === false,
      "Removals also need documentation.");
    stageRegion(lesion, b, true);
    assert(!pendingRegionCodes(lesion).length && lesion.regionEvidence[b],
      "Undoing a removal must retain the previously documented evidence.");
    rejects(() => documentRegions(lesion, text()));
    lesion.excluded = true;
    rejects(() => stageRegion(lesion, a, true));
  });
  test("Malformed pending edits cannot restore or bypass confirmation", () => {
    const original = prediction(), code = sectors[0].code;
    for (const patch of [
      { pendingRegionEdits: [] }, { pendingRegionEdits: { unknown: { from: false, to: true } } },
      { pendingRegionEdits: { [code]: { from: true, to: true } } },
      { pendingRegionEdits: { [code]: { from: false, to: true } } },
      { pendingRegionEdits: { [code]: { from: "false", to: false } } },
      { pendingRegionEdits: { [code]: { from: false, to: true } }, regions: [code], reviewed: true },
    ]) {
      const draft = saved(original);
      Object.assign(draft.lesions[0], patch);
      assert(!valid(draft, original), "Inconsistent or reviewed pending edits must fail restoration.");
    }
  });
  test("Unicode code point quotations and required evidence metadata", () => {
    assert(validateEvidence(text(), context).length === 0, "Exact Unicode quotation must pass.");
    for (const patch of [
      { start: 3, end: 12 }, { quotation: "different" }, { end: 999 }, { start: -1 },
      { start: 2.5 }, { end: 2 }, { quotation: "" }, { quotation: " " },
      { basis: "normalized" }, { basis: "absent" }, { reason: " " }, { source: "drawing" },
      { kind: "unknown" },
    ]) assert(validateEvidence({ ...text(), ...patch }, context).length > 0, JSON.stringify(patch));
    assert(validateEvidence(null, context).length > 0, "Null must fail.");
    assert(validateEvidence(text(), {}).length > 0, "Missing report text must fail.");
  });
  test("Actual image bounds, hashes, sources and report-only anchors", () => {
    for (const source of ["report", "drawing"]) {
      assert(validateEvidence(image(source), context).length === 0, "Exact full image bounds must pass.");
    }
    for (const patch of [
      { bounds: [-1, 0, 10, 10] }, { bounds: [0, -1, 10, 10] },
      { bounds: [0, 0, 0, 10] }, { bounds: [0, 0, 10, -1] },
      { bounds: [119, 0, 2, 2] }, { bounds: [0, 89, 2, 2] },
      { bounds: [0.5, 0, 10, 10] }, { bounds: [0, 0, 10] },
      { bounds: [0, 0, Infinity, 10] }, { sha256: "wrong" }, { source: "unknown" },
    ]) assert(validateEvidence({ ...image(), ...patch }, context).length > 0, JSON.stringify(patch));
    assert(validateEvidence(image(), { ...context, imageSizes: {} }).length > 0, "No guessed image dimensions.");
    assert(validateEvidence(image(), { ...context, sources: {} }).length > 0, "No missing source hash.");
    assert(validateEvidence(image("drawing"), context, { reportOnly: true }).length > 0, "Drawing cannot create a lesion.");
    assert(validateEvidence(image(), context, { reportOnly: true }).length === 0, "Report image can create a lesion.");
  });
  test("Absent anchors require explicit permission and absence basis", () => {
    assert(validateEvidence(absent(), context).length > 0, "Absent must fail by default.");
    assert(validateEvidence(absent(), context, { allowAbsent: true }).length === 0, "Allowed absence must pass.");
    assert(validateEvidence({ ...absent(), basis: "explicit" }, context, { allowAbsent: true }).length > 0, "Basis must agree.");
    assert(validateEvidence({ ...absent(), reason: "" }, context, { allowAbsent: true }).length > 0, "Absence still needs a reason.");
  });
  test("Doctor creation preserves state, clones evidence and leaves clinical fields empty", () => {
    const state = prediction(), evidence = text();
    const before = JSON.stringify(state);
    const lesion = createDoctorLesion(state, evidence, context);
    assert(JSON.stringify(state) === before, "Creation must not mutate state.");
    assert(lesion.id.startsWith("doctor-") && lesion.instance === 3 && lesion.doctorAdded === true, "Stable next instance.");
    assert(lesion.label === "Doctor-added lesion 3" && lesion.reviewed === false, "Explicit doctor label and unreviewed.");
    assert(lesion.regions.length === 0 && Object.keys(lesion.values).length === 0 &&
      lesion.issues.length === 0 && lesion.sourceObservations.length === 0, "No clinical defaults or marks.");
    evidence.reason = "mutated";
    assert(lesion.creationEvidence.reason !== evidence.reason, "Creation evidence must be detached.");
    assert(createDoctorLesion(state, text(), context).id !== lesion.id, "UUID must be unique.");
    rejects(() => createDoctorLesion(state, absent(), context));
    rejects(() => createDoctorLesion(state, image("drawing"), context));
    assert(createDoctorLesion(state, image(), context).instance === 3, "Report crop accepted.");
  });
  test("Stable instances include exclusions, exceed four and reject invalid or exhausted counters", () => {
    const state = { lesions: [{ instance: 8, excluded: true }, { instance: 3 }] };
    assert(createDoctorLesion(state, text(), context).instance === 9, "Never reuse an excluded instance.");
    assert(createDoctorLesion({ lesions: [] }, text(), context).instance === 1, "Empty state starts at one.");
    for (const instance of [0, -1, 1.2, "2", NaN, Infinity, Number.MAX_SAFE_INTEGER]) {
      rejects(() => createDoctorLesion({ lesions: [{ instance }] }, text(), context));
    }
    rejects(() => createDoctorLesion({ lesions: [{ instance: 1 }, { instance: 1 }] }, text(), context));
    rejects(() => createDoctorLesion({}, text(), context));
  });
  test("Legacy v2-shaped review restores with omitted new optional properties", () => {
    const original = prediction();
    const draft = saved(original);
    draft.lesions[0].values.lesion_x_mm = "invalid raw draft value";
    assert(valid(draft, original), "Draft raw values are not exporter validation.");
    draft.schemaVersion = original.schemaVersion = "doctor-review-v2";
    assert(valid(draft, original), "Schema identity, not a hardcoded version list.");
    delete original.lesions[0].sourceObservations;
    delete draft.lesions[0].sourceObservations;
    assert(valid(draft, original), "Legacy omitted source observations preserved.");
  });
  test("Doctor additions, exclusions, reordered original records and multiple associations restore", () => {
    const original = prediction(), draft = saved(original);
    for (let index = 0; index < 5; index += 1) {
      draft.lesions.push(createDoctorLesion(draft, text(), context));
    }
    draft.lesions[0].excluded = true;
    draft.lesions[0].exclusionReason = "Synthetic duplicate focus.";
    draft.lesions[1].regions = draft.lesions[2].regions = [sectors[0].code];
    draft.lesions.reverse();
    draft.reviewLog.push({ at: "synthetic-time", action: "exclude", actor: "synthetic-doctor", details: { reason: "duplicate" } });
    assert(valid(draft, original), "More than four lesions and exclusions must restore.");
    assert(draft.lesions.find(l => l.id === "original-a").instance === 2, "Original instance remains stable.");
  });
  test("Prediction binding and immutable source data cannot be tampered with", () => {
    const original = prediction();
    for (const key of ["schemaVersion", "caseId", "showcase", "sourceBinding", "sourceAnalysis", "reportText"]) {
      const draft = saved(original);
      draft[key] = "tampered";
      assert(!valid(draft, original), `Binding ${key} must match.`);
    }
    for (const change of [
      l => { l.instance = 3; }, l => { l.doctorAdded = true; },
      l => { l.sourceObservations[0].value.a = 9; },
      l => { l.issues[0].message = "changed"; },
      l => { l.issues[0].customDefinition.a = 9; },
      l => { l.issues[0].extraImmutableKey = true; },
      l => { delete l.issues[0].hint; }, l => { l.issues = []; },
    ]) {
      const draft = saved(original);
      change(draft.lesions[0]);
      assert(!valid(draft, original), "Immutable lesion or issue mutation must fail.");
    }
    const missing = saved(original);
    missing.lesions = [];
    assert(!valid(missing, original), "Original lesions must remain present even when excluded.");
  });
  test("Immutable object key order does not affect provenance equality", () => {
    const original = prediction(), draft = saved(original);
    draft.sourceAnalysis.response.nested = { b: 2, a: 1 };
    draft.lesions[0].sourceObservations[0].value = { b: 2, a: 1 };
    draft.lesions[0].issues[0].customDefinition = { b: 2, a: 1 };
    assert(valid(draft, original), "Key-order changes alone are not source changes.");
  });
  test("Malformed additions, duplicate IDs and instances, and removed evidence cannot restore", () => {
    const original = prediction();
    for (const change of [
      l => { delete l.doctorAdded; }, l => { l.doctorAdded = false; },
      l => { l.sourceObservations = [{}]; }, l => { l.issues = [{}]; },
      l => { l.creationEvidence = image("drawing"); }, l => { delete l.creationEvidence; },
      l => { l.creationEvidence.quotation = "tampered"; }, l => { l.instance = 2; },
      l => { l.id = "original-a"; }, l => { l.instance = Number.MAX_SAFE_INTEGER + 1; },
    ]) {
      const draft = saved(original), addition = createDoctorLesion(draft, text(), context);
      change(addition);
      draft.lesions.push(addition);
      assert(!valid(draft, original), "Malformed or disguised addition must fail.");
    }
  });
  test("Draft shape, known fields, regions, exclusions and issue dispositions are checked", () => {
    const original = prediction();
    for (const change of [
      l => { l.label = " "; }, l => { l.reviewed = "true"; }, l => { l.instance = -1; },
      l => { l.values = []; }, l => { l.values.unknown = ""; }, l => { l.values.hist_type_sur = 2; },
      l => { l.regions = [sectors[0].code, sectors[0].code]; }, l => { l.regions = ["not-a-region"]; },
      l => { l.excluded = "true"; }, l => { l.excluded = true; }, l => { l.doctorAdded = "false"; },
      l => { l.issues[0].resolved = 1; }, l => { l.issues[0].resolution = null; },
      l => { l.issues[0].disposition = "made-up"; },
    ]) {
      const draft = saved(original);
      change(draft.lesions[0]);
      assert(!valid(draft, original), "Malformed saved lesion must fail.");
    }
    for (const disposition of [undefined, "unresolved", "resolved", "reviewed_unknown"]) {
      const draft = saved(original);
      Object.assign(draft.lesions[0].issues[0], { disposition, resolved: true, resolution: "Synthetic written decision.", reopenedReason: "Synthetic reopening." });
      assert(valid(draft, original), "Documented issue dispositions must restore.");
    }
  });
  test("Optional field and region evidence is validated with restricted absence", () => {
    const original = prediction();
    for (const [field, value, allowed] of [
      ["hist_type_sur", "", true], ["hist_type_sur", "4", false],
      ["extracaps_ext", "4", true], ["perineural_inv_sur", "4", true],
      ["extracaps_ext", "3", false], ["lesion_x_mm", "4", false],
    ]) {
      const draft = saved(original), lesion = draft.lesions[0];
      lesion.values[field] = value;
      lesion.valueEvidence = { [field]: absent() };
      assert(valid(draft, original) === allowed, `Absent restriction: ${field}=${value}`);
    }
    const draft = saved(original), lesion = draft.lesions[0], code = sectors[0].code;
    lesion.values.hist_type_sur = "2";
    lesion.valueEvidence = { hist_type_sur: text() };
    lesion.regions = [code];
    lesion.regionEvidence = { [code]: image("drawing") };
    assert(valid(draft, original), "Anchored values and regions restore.");
    lesion.regionEvidence[code] = absent();
    assert(!valid(draft, original), "Selected region cannot use absence.");
    lesion.regionEvidence = { unknown: image() };
    assert(!valid(draft, original), "Evidence cannot use an unknown region.");
    lesion.regionEvidence = {};
    lesion.valueEvidence.hist_type_sur.quotation = "tampered";
    assert(!valid(draft, original), "Tampered field evidence fails.");
    lesion.valueEvidence = { unknown: text() };
    assert(!valid(draft, original), "Evidence cannot use an unknown field.");
    lesion.valueEvidence = [];
    assert(!valid(draft, original), "Evidence maps must be objects.");
  });
  test("Review log structure and validation purity", () => {
    const original = prediction(), draft = saved(original);
    const before = JSON.stringify({ original, draft, context, sectors });
    assert(valid(draft, original), "Baseline review must pass.");
    assert(JSON.stringify({ original, draft, context, sectors }) === before, "Validation must be pure.");
    for (const entry of [null, [], {}, { at: "", actor: "", action: "", details: [] }, { at: 1, actor: "", action: "", details: {} }]) {
      draft.reviewLog = [entry];
      assert(!valid(draft, original), "Malformed log entry must fail.");
    }
    draft.reviewLog = [];
    draft.recordId = 5;
    assert(!valid(draft, original), "Record ID must be a string.");
    assert(!validSavedReview(null, original, sectors, context), "Null saved data must fail.");
  });
  return { passed, groups };
}
