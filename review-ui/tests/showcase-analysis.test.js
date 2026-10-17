import { adaptShowcaseAnalysis } from "../showcase-analysis.js";
import { LESION_FIELDS, validateReview, buildLesionCsv } from "../redcap.js";

/** Run only on synthetic UI-ready fixtures; never reads or changes saved reviews. */
export async function runShowcaseAnalysisTests(raw, reportText, sectors) {
  let passed = 0;
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const clone = value => structuredClone(value);
  const options = extra => ({ caseId: "DEMO-PREFILLED", reportText, showcase: true, ...extra });
  const test = async (name, run) => {
    try { await run(); passed += 1; }
    catch (error) { throw new Error(`${name}: ${error.message}`); }
  };
  const reject = async (input, configuration = options(), suppliedSectors = sectors) => {
    let error;
    try { await adaptShowcaseAnalysis(input, suppliedSectors, configuration); } catch (caught) { error = caught; }
    assert(error instanceof Error, "Invalid input must fail explicitly");
  };
  const replaceHash = async (input, text) => {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    input.report_sha256 = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  };

  await test("All twelve fields load exactly and remain independent across A/B", async () => {
    assert(raw.lesions.length >= 2, "Supply the complete synthetic A/B fixture");
    const state = await adaptShowcaseAnalysis(raw, sectors, options());
    assert(state.schemaVersion === "doctor-review-analysis-v1" && state.recordId === "" &&
      state.showcase === true && state.sourceBinding === "showcase-unlinked", "Use the explicitly unlinked review state");
    for (let index = 0; index < raw.lesions.length; index += 1) {
      const input = raw.lesions[index];
      const lesion = state.lesions[index];
      assert(lesion.id === input.id && lesion.instance === index + 1 && lesion.reviewed === false, "Independent unreviewed instances");
      assert(lesion.sourceObservations.length === 12, "Complete fixture must supply all twelve properties");
      for (const field of LESION_FIELDS) {
        assert(input.fields[field.name]?.status === "recorded", `Fixture must record ${field.name}`);
        assert(lesion.values[field.name] === input.fields[field.name].value, `Keep exact ${field.name} raw value`);
        const observation = lesion.sourceObservations.find(item => item.property === field.name);
        assert(observation.value.raw_code === lesion.values[field.name] &&
          observation.subject_id === lesion.id && observation.id === `${lesion.id}:${field.name}`,
        "Keep field provenance and exact raw code");
      }
    }
    assert(state.lesions[0].values !== state.lesions[1].values, "A/B clinical values must not share mutable objects");
    assert(JSON.stringify(state.lesions[0].values) !== JSON.stringify(state.lesions[1].values), "A/B must demonstrate distinct synthetic values");
    const presence = state.lesions.flatMap(lesion => [lesion.values.extracaps_ext, lesion.values.perineural_inv_sur]);
    assert(presence.includes("3") && presence.includes("2"), "Keep No (3) distinct from Uncertain (2)");
  });
  await test("Raw preservation, evidence offsets, hash and independent certainty", async () => {
    const before = JSON.stringify(raw);
    const state = await adaptShowcaseAnalysis(raw, sectors, options());
    assert(JSON.stringify(state.sourceAnalysis) === before && JSON.stringify(raw) === before, "Retain the full unchanged input");
    for (const lesion of state.lesions) for (const observation of lesion.sourceObservations) {
      const supplied = raw.lesions.find(item => item.id === lesion.id).fields[observation.property];
      assert(observation.status === supplied.status && observation.basis === supplied.basis &&
        observation.certainty.extraction === "unassessed" && observation.certainty.interpretation === "unassessed",
      "Basis/status must not be conflated with confidence");
      for (const anchor of observation.evidence) {
        assert([...reportText].slice(anchor.start_offset, anchor.end_offset).join("") === anchor.quotation &&
          anchor.source_text_sha256 === raw.report_sha256, "Resolve exact source quotation, Unicode offsets and hash");
      }
    }
    state.lesions[0].values.hist_type_sur = "1";
    state.lesions[0].sourceObservations[0].evidence[0].quotation = "Changed review display";
    assert(JSON.stringify(raw) === before && JSON.stringify(state.sourceAnalysis) === before, "Do not mutate either raw provenance copy");
  });
  await test("Only JSON sectors are used and every fabrication has a blocking issue", async () => {
    const input = clone(raw);
    input.lesions[0].regions = ["urethra"];
    const state = await adaptShowcaseAnalysis(input, sectors, options({ demoAssignments: { [input.lesions[0].id]: ["pzpl_mid_ls"] } }));
    assert(state.lesions[0].regions.join(",") === "urethra", "Do not trust external demoAssignments or infer locations");
    for (const lesion of state.lesions) {
      assert(lesion.issues.some(issue => issue.id === `${lesion.id}:showcase-unlinked` &&
        issue.message.includes("unlinked") && !issue.resolved), "Unlinked showcase warning is mandatory");
      for (const code of lesion.regions) {
        assert(lesion.issues.some(issue => issue.id === `${lesion.id}:showcase-region:${code}` &&
          issue.showcaseOnly === true && issue.regionCodes.join(",") === code &&
          issue.message.includes("fabricated") && issue.resolved === false && issue.resolution === ""),
        "Every fabricated region requires doctor resolution");
      }
    }
    input.lesions[0].regions = [];
    input.lesions[0].region_evidence_ids = [];
    input.lesions[0].region_reason = "";
    assert((await adaptShowcaseAnalysis(input, sectors, options())).lesions[0].regions.length === 0, "No regions means no inferred assignment");
  });
  await test("Omitted and unavailable fields remain empty without defaults", async () => {
    const input = clone(raw);
    delete input.lesions[0].fields.hist_type_sur;
    delete input.lesions[0].fields.lesion_z_mm;
    const field = input.lesions[0].fields.extracaps_ext;
    field.value = null;
    field.status = "not reported";
    field.evidence_ids = [];
    field.coverage_checked = true;
    field.source_complete = true;
    field.basis = "explicit";
    const state = await adaptShowcaseAnalysis(input, sectors, options());
    const lesion = state.lesions[0];
    assert(lesion.values.hist_type_sur === "" && lesion.values.lesion_z_mm === "" &&
      lesion.values.extracaps_ext === "", "Missing must not become carcinoma, axis guesses, negatives or Not specified");
    assert(!lesion.sourceObservations.some(item => item.property === "hist_type_sur"), "Omission does not manufacture an observation");
    const observation = lesion.sourceObservations.find(item => item.property === "extracaps_ext");
    assert(observation.status === "not reported" && observation.value === null, "Unavailable observations have no value");
    assert(lesion.issues.some(issue => issue.sourceRef === observation.id && issue.resolved === false), "Unavailable answer needs review");
    delete field.coverage_checked;
    await reject(input);
    for (const status of ["unreadable", "not assessed", "not applicable"]) {
      const unavailable = clone(raw);
      Object.assign(unavailable.lesions[0].fields.lesion_x_mm, { value: null, status });
      const result = await adaptShowcaseAnalysis(unavailable, sectors, options());
      assert(result.lesions[0].values.lesion_x_mm === "", "Unavailable quantities stay empty");
    }
  });
  await test("Inferred/calculated prefills require reasoning and individual blocking flags", async () => {
    for (const basis of ["inferred", "calculated"]) {
      const input = clone(raw);
      const field = input.lesions[0].fields.gleason_tert_perc;
      field.basis = basis;
      delete field.reason;
      await reject(input);
      field.reason = " ";
      await reject(input);
      field.reason = "Explicitly fabricated reasoning for this synthetic demonstration.";
      const state = await adaptShowcaseAnalysis(input, sectors, options());
      const lesion = state.lesions[0];
      assert(lesion.values.gleason_tert_perc === field.value, "Preserve declared inferred/calculated prefill");
      const observation = lesion.sourceObservations.find(item => item.property === "gleason_tert_perc");
      assert(observation.basis === basis && observation.reason === field.reason, "Show reasoning separately from confidence");
      assert(lesion.issues.some(issue => issue.sourceRef === observation.id &&
        issue.regionCodes.length === 0 && issue.resolved === false && issue.resolution === ""),
      "Require individual doctor review for every inferred/calculated field");
    }
  });
  await test("Invalid clinical names, raw categories, numbers, statuses and bases reject", async () => {
    for (const mutate of [
      input => { input.lesions[0].fields.isup = clone(input.lesions[0].fields.hist_type_sur); },
      input => { input.lesions[0].fields.surgery_date = clone(input.lesions[0].fields.hist_type_sur); },
      input => { input.lesions[0].fields.hist_type_sur.value = "Carcinoma"; },
      input => { input.lesions[0].fields.hist_type_sur.value = 2; },
      input => { input.lesions[0].fields.extracaps_ext.value = "0"; },
      input => { input.lesions[0].fields.gleason_prim_grade.value = "6"; },
      input => { input.lesions[0].fields.lesion_x_mm.value = "100.01"; },
      input => { input.lesions[0].fields.lesion_y_mm.value = "-1"; },
      input => { input.lesions[0].fields.lesion_z_mm.value = "12mm"; },
      input => { input.lesions[0].fields.gleason_prim_perc.value = "Infinity"; },
      input => { input.lesions[0].fields.gleason_sec_perc.value = "101"; },
      input => { input.lesions[0].fields.gleason_tert_perc.value = ""; },
      input => { input.lesions[0].fields.hist_type_sur.status = "absent"; },
      input => { input.lesions[0].fields.hist_type_sur.basis = "guessed"; },
    ]) {
      const input = clone(raw);
      mutate(input);
      await reject(input);
    }
  });
  await test("References, duplicates, hashes, exact-once quotations and showcase gate reject", async () => {
    for (const mutate of [
      input => { input.report_sha256 = "0".repeat(64); },
      input => { input.lesions[0].fields.hist_type_sur.evidence_ids = ["missing"]; },
      input => { input.lesions[0].region_evidence_ids = ["missing"]; },
      input => { input.lesions[0].region_reason = " "; },
      input => { input.lesions[0].regions = ["not-a-canonical-sector"]; },
      input => { input.lesions[0].regions = ["urethra", "urethra"]; },
      input => { input.lesions.push(clone(input.lesions[0])); },
      input => { input.evidence.push(clone(input.evidence[0])); },
      input => { input.evidence[0].quotation = "This quotation is not in the synthetic text."; },
      input => { input.evidence[0].quotation = ""; },
      input => { input.lesions = []; },
    ]) {
      const input = clone(raw);
      mutate(input);
      await reject(input);
    }
    await reject(raw, options({ showcase: false }));
    await reject(raw, options({ showcase: undefined }));
    await reject(raw, options({ reportText: `${reportText} ` }));
    await reject(raw, options(), sectors.slice(1));
    const repeated = clone(raw);
    const repeatedText = `${reportText}\n${repeated.evidence[0].quotation}`;
    await replaceHash(repeated, repeatedText);
    await reject(repeated, options({ reportText: repeatedText }));
    const overlap = clone(raw);
    overlap.evidence[0].quotation = "aa";
    const overlapText = `${reportText}\naaa`;
    await replaceHash(overlap, overlapText);
    await reject(overlap, options({ reportText: overlapText }));
  });
  await test("Unicode code-point offsets and direct field-name axes", async () => {
    const input = clone(raw);
    const unicodeText = `🧪 Synthetic demonstration.\n${reportText}`;
    await replaceHash(input, unicodeText);
    const state = await adaptShowcaseAnalysis(input, sectors, options({ reportText: unicodeText }));
    for (const lesion of state.lesions) {
      for (const axis of ["x", "y", "z"]) assert(
        lesion.values[`lesion_${axis}_mm`] === input.lesions.find(item => item.id === lesion.id).fields[`lesion_${axis}_mm`].value,
        "Explicit input field names, not dimension ordering, determine axes");
      for (const observation of lesion.sourceObservations) for (const anchor of observation.evidence) {
        assert([...unicodeText].slice(anchor.start_offset, anchor.end_offset).join("") === anchor.quotation, "Offsets must count the emoji as one code point");
      }
    }
  });
  await test("Synthetic review permits correct lesion-only CSV without specimen leakage", async () => {
    const state = await adaptShowcaseAnalysis(raw, sectors, options());
    assert(validateReview(state, sectors).length > 0, "Never auto-confirm an imported synthetic analysis");
    state.recordId = "TEST-PREFILLED-SYNTHETIC";
    for (const lesion of state.lesions) {
      lesion.reviewed = true;
      for (const issue of lesion.issues) {
        issue.resolved = true;
        issue.disposition = "resolved";
        issue.resolution = "Synthetic test review only; not a clinical sign-off.";
      }
    }
    assert(validateReview(state, sectors).length === 0, "Synthetic review should satisfy existing gates");
    const [headerLine, ...lines] = buildLesionCsv(state, sectors).trimEnd().split("\r\n");
    const header = headerLine.split(",");
    assert(!header.includes("isup") && !header.includes("surgery_date") &&
      !header.includes("surgery_c61_complete"), "No specimen-level or surgery row fields");
    assert(lines.length === raw.lesions.length, "Exactly one row per synthetic focus");
    for (let index = 0; index < lines.length; index += 1) {
      const row = lines[index].split(",");
      const get = name => row[header.indexOf(name)];
      for (const field of LESION_FIELDS) assert(get(field.name) === raw.lesions[index].fields[field.name].value, "CSV raw code mismatch");
      assert(get("redcap_repeat_instance") === String(index + 1) &&
        get("surgery_c61_resected_lesion_complete") === "0" && get("all_sgm___1") === "0", "Keep explicit instances and incomplete form status");
      for (const sector of sectors) assert(get(sector.column) ===
        (raw.lesions[index].regions.includes(sector.code) ? "1" : "0"), "Only declared JSON region checkboxes");
    }
  });
  return { passed };
}
