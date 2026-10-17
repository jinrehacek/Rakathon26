import { LESION_FIELDS, validateReview, buildLesionCsv } from "../redcap.js";

// Pass the actual 41-sector map from the browser test runner. All case content
// here is synthetic. No fetch, server, patient data, or REDCap access is needed.
export function runExportTests(sectors) {
  let passed = 0;
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const test = (name, run) => {
    try {
      run();
      passed += 1;
    } catch (error) {
      throw new Error(`${name}: ${error.message}`);
    }
  };
  const fixture = () => ({
    caseId: "SYNTHETIC-CASE-NOT-A-REDCAP-ID",
    recordId: "SYNTHETIC-REVIEW-001",
    lesions: [{
      id: "synthetic-focus", instance: 3, label: "Synthetic focus",
      regions: [sectors[0].code],
      values: { hist_type_sur: "2", extracaps_ext: "4", perineural_inv_sur: "3" },
      issues: [], reviewed: true,
    }],
  });
  const blocked = (state, message) => {
    assert(validateReview(state, sectors).length > 0, message);
    let threw = false;
    try { buildLesionCsv(state, sectors); } catch (error) { threw = error instanceof Error; }
    assert(threw, "CSV export must throw on validation errors");
  };
  // Independent CSV parser to check escaping, embedded newlines and row widths.
  const parse = text => {
    const rows = [];
    let row = [];
    let cell = "";
    let quoted = false;
    for (let i = 0; i < text.length; i += 1) {
      const char = text[i];
      if (char === '"') {
        if (quoted && text[i + 1] === '"') { cell += '"'; i += 1; }
        else quoted = !quoted;
      } else if (char === "," && !quoted) {
        row.push(cell); cell = "";
      } else if (char === "\r" && text[i + 1] === "\n" && !quoted) {
        row.push(cell); rows.push(row); row = []; cell = ""; i += 1;
      } else cell += char;
    }
    assert(!quoted && row.length === 0 && cell === "", "CSV must finish with CRLF and balanced quotes");
    assert(rows.every(item => item.length === rows[0].length), "CSV row widths must match");
    return rows;
  };
  const table = state => {
    const [header, ...rows] = parse(buildLesionCsv(state, sectors));
    return { header, rows, get: (row, name) => row[header.indexOf(name)] };
  };

  test("Actual sector specification", () => {
    assert(Array.isArray(sectors) && sectors.length === 41, "Supply the actual 41-sector array");
    assert(validateReview(fixture(), sectors).length === 0, "Synthetic complete review must be valid");
  });
  test("Only section 6 clinical fields and no defaults", () => {
    assert(LESION_FIELDS.length === 12, "Expected twelve editable lesion fields");
    assert(LESION_FIELDS.filter(field => field.required).map(field => field.name).join(",") ===
      "hist_type_sur,extracaps_ext,perineural_inv_sur", "Expected exactly three required fields");
    for (const name of ["hist_type_sur", "extracaps_ext", "perineural_inv_sur"]) {
      const state = fixture();
      delete state.lesions[0].values[name];
      blocked(state, `${name} must not receive a default`);
    }
    const state = fixture();
    const before = JSON.stringify(state);
    const output = table(state);
    for (const name of ["lesion_x_mm", "lesion_y_mm", "lesion_z_mm", "gleason_prim_grade",
      "gleason_prim_perc", "gleason_sec_grade", "gleason_sec_perc", "gleason_tert_grade", "gleason_tert_perc"]) {
      assert(output.get(output.rows[0], name) === "", `${name} must stay empty`);
    }
    assert(JSON.stringify(state) === before, "Validation/export must not mutate state");
  });
  test("Multiple explicit instances, deterministic output, no fabricated surgery row", () => {
    const state = fixture();
    state.lesions.push({ ...state.lesions[0], id: "synthetic-focus-2", instance: 8, regions: [] });
    state.lesions.reverse();
    const output = table(state);
    assert(output.rows.length === 2, "Exactly one row per lesion, no surgery row");
    assert(output.rows.map(row => output.get(row, "redcap_repeat_instance")).join(",") === "3,8",
      "Keep explicit nonconsecutive instances, sorted numerically");
    for (const row of output.rows) {
      assert(output.get(row, "redcap_repeat_instrument") === "surgery_c61_resected_lesion", "Lesion instrument only");
      assert(output.get(row, "surgery_c61_resected_lesion_complete") === "0", "Doctor review must not mark form complete");
    }
    assert(!output.header.includes("surgery_date") && !output.header.includes("surgery_c61_complete"),
      "No surgery-level fields");
    const csv = buildLesionCsv(state, sectors);
    assert(csv === buildLesionCsv({ ...state, lesions: [...state.lesions].reverse() }, [...sectors].reverse()),
      "CSV must not depend on lesion/sector input order");
    assert(!csv.replaceAll("\r\n", "").includes("\n") && csv.endsWith("\r\n"), "Use CRLF");
  });
  test("All 41 explicit binary checkboxes and all_sgm=0", () => {
    const state = fixture();
    state.lesions[0].regions = [sectors[0].code, sectors[40].code];
    const output = table(state);
    const columns = output.header.filter(name => name.startsWith("sur_prostate_regions___"));
    assert(columns.length === 41 && new Set(columns).size === 41, "Exactly 41 distinct region columns");
    for (const sector of sectors) {
      assert(columns.includes(sector.column), `Missing ${sector.column}`);
      assert(output.get(output.rows[0], sector.column) ===
        (state.lesions[0].regions.includes(sector.code) ? "1" : "0"), "Explicit checkbox mismatch");
    }
    assert(output.get(output.rows[0], "all_sgm___1") === "0", "Disable all-segments shortcut");
    state.lesions[0].regions = sectors.map(sector => sector.code);
    const all = table(state);
    assert(sectors.every(sector => all.get(all.rows[0], sector.column) === "1"), "All-sector selection includes urethra");
    assert(all.get(all.rows[0], "all_sgm___1") === "0", "Shortcut stays off even when all selected");
  });
  test("One lesion spans multiple levels; overlapping lesions stay separate", () => {
    const state = fixture();
    const codes = ["pzpl_base_ls", "pzpl_mid_ls"];
    state.lesions[0].regions = [...codes];
    state.lesions.push({ ...state.lesions[0], id: "overlapping-focus", instance: 4, regions: [codes[1]] });
    const output = table(state);
    assert(output.rows.length === 2, "Do not split one lesion into a row per segment or merge overlapping lesions");
    assert(codes.every(code => output.get(output.rows[0], `sur_prostate_regions___${code}`) === "1"),
      "Base and Mid segments must export together on the first lesion");
    assert(output.get(output.rows[1], `sur_prostate_regions___${codes[0]}`) === "0" &&
      output.get(output.rows[1], `sur_prostate_regions___${codes[1]}`) === "1",
    "An overlapping lesion must retain its own independent region set");
  });
  test("Uncertainties require explicit resolution and written reasoning", () => {
    const state = fixture();
    const issue = { id: "synthetic-conflict", message: "Synthetic disagreement",
      regionCodes: [sectors[0].code], resolved: false, resolution: "" };
    state.lesions[0].issues = [issue];
    blocked(state, "Unresolved uncertainty must block");
    issue.resolved = true;
    issue.resolution = "   ";
    blocked(state, "A resolution flag without reasoning must block");
    issue.resolution = "Doctor inspected synthetic sources and confirmed sector.";
    assert(validateReview(state, sectors).length === 0, "Explicit resolved issue should pass");
    issue.resolved = "true";
    blocked(state, "Truthy strings are not confirmation");
  });
  test("Explicit doctor confirmation", () => {
    const state = fixture();
    for (const value of [false, undefined, "true", 1]) {
      state.lesions[0].reviewed = value;
      blocked(state, "Only reviewed === true may export");
    }
  });
  test("Invalid or duplicate repeat instances", () => {
    for (const value of [0, -1, 1.5, "1", NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      const state = fixture();
      state.lesions[0].instance = value;
      blocked(state, "Invalid repeat instance must block");
    }
    const state = fixture();
    state.lesions.push({ ...state.lesions[0], id: "synthetic-duplicate" });
    blocked(state, "Duplicate repeat instance must block");
  });
  test("Unknown regions, unknown fields, and damaged sector specifications", () => {
    const state = fixture();
    state.lesions[0].regions.push("unknown");
    blocked(state, "Unknown selected region must not be dropped");
    state.lesions[0].regions.pop();
    state.lesions[0].values.isup = "2";
    blocked(state, "Specimen-level field must not be dropped");
    for (const invalid of [sectors.slice(1), [...sectors.slice(1), sectors[1]],
      sectors.map((sector, i) => i === 0 ? { ...sector, column: "wrong" } : sector)]) {
      assert(validateReview(fixture(), invalid).length > 0, "Incomplete/duplicate/mismapped sectors must block");
      let threw = false;
      try { buildLesionCsv(fixture(), invalid); } catch { threw = true; }
      assert(threw, "Export must reject invalid sector specifications");
    }
  });
  test("Numeric bounds and raw categories", () => {
    for (const field of LESION_FIELDS) {
      if (field.type === "number") {
        for (const value of ["-1", "100.01", "NaN", "Infinity", "0x10", "1e2", "1,5", " ", "12mm", "=1+1", 10]) {
          const state = fixture();
          state.lesions[0].values[field.name] = value;
          blocked(state, `${field.name} must reject ${value}`);
        }
        for (const value of ["0", "100", "12.5"]) {
          const state = fixture();
          state.lesions[0].values[field.name] = value;
          assert(validateReview(state, sectors).length === 0, `${field.name} should accept ${value}`);
        }
      } else {
        for (const value of ["0", "8", "Carcinoma", " 2", 2]) {
          const state = fixture();
          state.lesions[0].values[field.name] = value;
          blocked(state, "Only documented string raw category codes allowed");
        }
        for (const [code] of field.choices) {
          const state = fixture();
          state.lesions[0].values[field.name] = code;
          assert(validateReview(state, sectors).length === 0, `Documented choice ${code} must be valid`);
        }
      }
    }
  });
  test("CSV escaping preserves record identity and rejects formula identities", () => {
    const state = fixture();
    state.recordId = 'SYNTHETIC,"quoted"\r\nidentity';
    const before = JSON.stringify(state);
    const csv = buildLesionCsv(state, sectors);
    assert(csv.includes('"SYNTHETIC,""quoted""\r\nidentity"'), "Use standard CSV escaping");
    const output = table(state);
    assert(output.get(output.rows[0], "record_id") === state.recordId, "Escaping must preserve identity");
    assert(JSON.stringify(state) === before, "Export must not rewrite source identity");
    for (const value of ["=1+1", "+1", "-1", "@SUM(A1)", " \t=1", "\n=1", "\tSAFE"]) {
      state.recordId = value;
      blocked(state, "Reject unsafe identity without adding an apostrophe");
      assert(state.recordId === value, "Unsafe identity must remain unchanged");
    }
  });
  test("No case-ID substitution, empty lesions, or missing review lists", () => {
    for (const value of ["", "   ", undefined, null, 1]) {
      const state = fixture();
      state.recordId = value;
      blocked(state, "Case ID must never substitute for missing record ID");
    }
    const state = fixture();
    state.lesions = [];
    blocked(state, "Empty lesion list must block");
    const missing = fixture();
    delete missing.lesions[0].issues;
    blocked(missing, "Missing issue list must not bypass uncertainty review");
    assert(validateReview(null, sectors).length > 0, "Malformed state should return errors, not throw");
  });
  test("Showcase exports cannot target a real REDCap identity", () => {
    const state = fixture();
    state.showcase = true;
    for (const identity of ["CMP-0000001", "TEST-", "DEMO-", " TEST-001", "test-001"]) {
      state.recordId = identity;
      blocked(state, "Showcase must require an explicit TEST- or DEMO- prefix");
    }
    for (const identity of ["TEST-SYNTHETIC-001", "DEMO-SYNTHETIC-001"]) {
      state.recordId = identity;
      assert(validateReview(state, sectors).length === 0, "Explicit demo identity should pass");
      assert(buildLesionCsv(state, sectors).includes(identity), "Keep the exact demo identity");
    }
    delete state.showcase;
    state.recordId = "CMP-0000001";
    assert(validateReview(state, sectors).length === 0, "Non-showcase identities remain unrestricted");
  });
  test("Excluded lesions remain in the draft without clinical review or renumbering", () => {
    const state = fixture();
    state.lesions.push({
      id: "synthetic-excluded", instance: 1, excluded: true,
      exclusionReason: "Doctor excluded a synthetic non-lesion finding.", reviewed: false,
      regions: ["unmapped-draft-mark"], values: { hist_type_sur: "" },
      issues: [{ id: "excluded-unresolved", resolved: false }],
    });
    state.lesions.push({ ...fixture().lesions[0], id: "synthetic-included-2", instance: 9, excluded: false });
    const before = JSON.stringify(state);
    assert(validateReview(state, sectors).length === 0, "Excluded findings need no clinical or issue review");
    const output = table(state);
    assert(output.rows.length === 2, "Omit only excluded rows");
    assert(output.rows.map(row => output.get(row, "redcap_repeat_instance")).join(",") === "3,9",
      "Keep included instance numbers, even with gaps");
    assert(JSON.stringify(state) === before && state.lesions.length === 3,
      "Do not delete, renumber, resolve or otherwise mutate excluded/original records");
  });
  test("Exclusions require a nonempty string reason", () => {
    for (const reason of [undefined, null, "", " \n\t ", 1, false]) {
      const state = fixture();
      state.lesions.push({ id: "excluded", instance: 7, excluded: true, exclusionReason: reason });
      blocked(state, "An exclusion must carry an explicit written reason");
    }
    const state = fixture();
    state.lesions.push({ id: "excluded", instance: 7, excluded: true,
      exclusionReason: "Doctor excluded synthetic annotation." });
    assert(validateReview(state, sectors).length === 0, "A reasoned exclusion needs no other review fields");
  });
  test("All excluded lesions cannot produce a header-only import", () => {
    const state = fixture();
    state.lesions[0].excluded = true;
    state.lesions[0].exclusionReason = "Synthetic exclusion.";
    blocked(state, "At least one included reviewed lesion is required");
    state.lesions.push({ ...fixture().lesions[0], id: "unreviewed-included", instance: 8, reviewed: false });
    blocked(state, "An included lesion must still be explicitly reviewed");
  });
  test("Malformed exclusion flags cannot silently include or drop a lesion", () => {
    for (const excluded of [null, "true", "false", 0, 1, [], {}]) {
      const state = fixture();
      state.lesions[0].excluded = excluded;
      state.lesions[0].exclusionReason = "Synthetic reason does not make an invalid flag valid.";
      blocked(state, "Only a boolean exclusion flag is allowed when supplied");
    }
    const state = fixture();
    state.lesions[0].exclusionReason = 1;
    blocked(state, "An optional supplied exclusion reason must be a string");
  });
  test("Positive unique instances include excluded records", () => {
    const state = fixture();
    state.lesions.push({ id: "excluded-duplicate", instance: 3, excluded: true, exclusionReason: "Synthetic exclusion." });
    blocked(state, "An excluded instance cannot duplicate an included instance");
    state.lesions.reverse();
    blocked(state, "Duplicate detection must not depend on exclusion order");
    state.lesions[0].instance = 7;
    state.lesions.push({ ...state.lesions[0], id: "excluded-duplicate-2" });
    blocked(state, "Two excluded instances cannot duplicate each other");
    state.lesions.pop();
    for (const instance of [0, -1, 1.5, "7", NaN, Infinity]) {
      state.lesions[0].instance = instance;
      blocked(state, "Excluded instances must remain explicit positive integers");
    }
  });
  test("Four included lesions are exported with their explicit instances", () => {
    const state = fixture();
    state.lesions = [12, 2, 7, 4].map(instance => ({
      ...fixture().lesions[0], id: `synthetic-${instance}`, instance, excluded: false,
    }));
    const before = JSON.stringify(state);
    const output = table(state);
    assert(output.rows.length === 4, "No arbitrary lesion-count cap or dropped fourth focus");
    assert(output.rows.map(row => output.get(row, "redcap_repeat_instance")).join(",") === "2,4,7,12",
      "Sort included rows without renumbering");
    assert(JSON.stringify(state) === before, "Export sorting must not reorder the source lesions");
  });
  test("Reviewed-unknown issues keep optional blanks and require real mandatory answers", () => {
    const state = fixture();
    state.lesions[0].issues = [{
      id: "synthetic-unknown", message: "Synthetic uncertainty remains after inspection.",
      regionCodes: [], resolved: true, disposition: "reviewed_unknown",
      resolution: "Doctor reviewed the synthetic evidence; this optional measurement remains unknown.",
    }];
    state.lesions[0].values.lesion_x_mm = "";
    state.lesions[0].values.extracaps_ext = "4";
    state.lesions[0].values.perineural_inv_sur = "4";
    const before = JSON.stringify(state);
    assert(validateReview(state, sectors).length === 0, "Reviewed unknown may pass with documented required answers");
    const output = table(state);
    assert(output.get(output.rows[0], "lesion_x_mm") === "", "Unknown optional measurement stays blank");
    assert(output.get(output.rows[0], "extracaps_ext") === "4" &&
      output.get(output.rows[0], "perineural_inv_sur") === "4", "Keep explicitly selected Not specified codes");
    assert(JSON.stringify(state) === before, "Unknown disposition must not alter clinical values or issues");
    for (const field of ["hist_type_sur", "extracaps_ext", "perineural_inv_sur"]) {
      const saved = state.lesions[0].values[field];
      state.lesions[0].values[field] = "";
      blocked(state, "Reviewed unknown does not waive required REDCap answers");
      state.lesions[0].values[field] = saved;
    }
    state.lesions[0].issues[0].resolved = false;
    blocked(state, "Reviewed-unknown disposition still requires resolved === true");
    state.lesions[0].issues[0].resolved = true;
    state.lesions[0].issues[0].resolution = " ";
    blocked(state, "Reviewed unknown still requires a written explanation");
  });
  test("Only documented issue dispositions or legacy omission are accepted", () => {
    const state = fixture();
    const issue = { id: "synthetic-disposition", message: "Synthetic review issue.",
      regionCodes: [], resolved: true, resolution: "Doctor inspected the synthetic source." };
    state.lesions[0].issues = [issue];
    for (const disposition of [undefined, "resolved", "reviewed_unknown"]) {
      issue.disposition = disposition;
      assert(validateReview(state, sectors).length === 0, "Documented disposition or legacy absence is supported");
      buildLesionCsv(state, sectors);
    }
    for (const disposition of ["unknown", "reviewed", "", null, true, 1]) {
      issue.disposition = disposition;
      blocked(state, "Unknown issue dispositions must block, not be ignored");
    }
  });
  test("Reviewed-unknown region associations block included lesion export", () => {
    const state = fixture();
    const issue = {
      id: "synthetic-region-unknown", message: "Synthetic region association is still uncertain.",
      regionCodes: [sectors[0].code], resolved: true, disposition: "reviewed_unknown",
      resolution: "Doctor inspected the synthetic drawing but cannot settle this association.",
    };
    state.lesions[0].issues = [issue];
    const before = JSON.stringify(state);
    blocked(state, "Sector checkboxes have no unknown code");
    assert(validateReview(state, sectors).some(error =>
      error.includes("settle the region association or exclude the lesion")),
      "Explain the available doctor decisions");
    assert(JSON.stringify(state) === before &&
      state.lesions[0].regions.includes(sectors[0].code), "Do not silently drop region predictions or issues");
    issue.disposition = "resolved";
    issue.resolution = "Doctor settled the synthetic region association.";
    assert(validateReview(state, sectors).length === 0, "A settled region association can export");
    issue.disposition = "reviewed_unknown";
    issue.regionCodes = [];
    assert(validateReview(state, sectors).length === 0, "Optional non-region unknowns may still pass");
  });
  test("Excluded lesions may retain reviewed-unknown region associations", () => {
    const state = fixture();
    state.lesions.push({
      id: "synthetic-excluded-region-unknown", instance: 7, excluded: true,
      exclusionReason: "Doctor excluded this synthetic finding because its association could not be settled.",
      regions: [sectors[0].code], values: {}, reviewed: false,
      issues: [{
        id: "excluded-region-unknown", message: "Synthetic unresolved region association.",
        regionCodes: [sectors[0].code], resolved: true, disposition: "reviewed_unknown",
        resolution: "Reviewed; association remains unknown.",
      }],
    });
    const before = JSON.stringify(state);
    const output = table(state);
    assert(output.rows.length === 1 && output.get(output.rows[0], "redcap_repeat_instance") === "3",
      "Exclude the uncertain lesion without removing the included one");
    assert(JSON.stringify(state) === before, "Keep excluded uncertainties unchanged in the draft");
  });
  return { passed };
}
