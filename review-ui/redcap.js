/**
 * Offline, lesion-only first-import draft. Not an existing-record update or
 * reconciliation workflow. Column names and codes were checked against
 * Other/redcap/import_template_header.csv and section 6 of REDCAP.md.
 * Lesion-only import has NOT been verified in REDCap. No network calls are made.
 * Labels, evidence and issue resolutions stay in the review draft: this REDCap
 * instrument has no fields for them. Surgery and patient identity forms are not
 * generated. Doctor review does not change REDCap's Incomplete form status.
 */

const presenceChoices = [
  ["1", "Yes"], ["2", "Uncertain"], ["3", "No"], ["4", "Not specified"],
];
const gradeChoices = ["1", "2", "3", "4", "5"].map(code => [code, code]);

/** Editable clinical properties only; region checkboxes are supplied separately. */
export const LESION_FIELDS = [
  {
    name: "hist_type_sur", label: "Type of histology", type: "select", required: true,
    choices: [
      ["1", "Benign"], ["2", "Carcinoma"], ["3", "Neuroendocrine tumor"],
      ["4", "Sarcoma"], ["5", "Haematolymphoid tumor"], ["6", "Metastasis"],
      ["7", "Other malignant tumors"],
    ],
  },
  ...["x", "y", "z"].map(axis => ({
    name: `lesion_${axis}_mm`, label: `${axis.toUpperCase()}-dimension of the lesion [mm]`,
    type: "number", required: false, min: 0, max: 100,
  })),
  {
    name: "extracaps_ext", label: "Extraprostatic extension", type: "select",
    required: true, choices: presenceChoices,
  },
  {
    name: "perineural_inv_sur", label: "Perineural invasion", type: "select",
    required: true, choices: presenceChoices,
  },
  ...[["prim", "primary"], ["sec", "secondary"], ["tert", "tertiary"]].flatMap(
    ([suffix, label]) => [
      {
        name: `gleason_${suffix}_grade`, label: `Gleason ${label} score`,
        type: "select", required: false, choices: gradeChoices,
      },
      {
        name: `gleason_${suffix}_perc`, label: `Gleason ${label} score (%)`,
        type: "number", required: false, min: 0, max: 100,
      },
    ],
  ),
];

// Prevent a UI consumer from inadvertently changing the export validation rules.
for (const field of LESION_FIELDS) {
  if (field.choices && !Object.isFrozen(field.choices)) {
    field.choices.forEach(Object.freeze);
    Object.freeze(field.choices);
  }
  Object.freeze(field);
}
Object.freeze(LESION_FIELDS);

// Exact order of the 41 columns in the saved REDCap import template, independent
// of the caller's polygon ordering or the order in which the doctor clicks them.
const REGION_CODES = Object.freeze([
  "pzpl_apex_rs", "pzpm_apex_rs", "tzp_apex_rs", "pzpm_apex_ls",
  "tzp_apex_ls", "pzpl_apex_ls", "pza_apex_ls", "tza_apex_ls",
  "as_apex_ls", "as_apex_rs", "tza_apex_rs", "pza_apex_rs", "urethra",
  "pzpl_mid_rs", "pzpm_mid_rs", "pzpm_mid_ls", "pzpl_mid_ls",
  "pza_mid_ls", "as_mid_ls", "tza_mid_ls", "tzp_mid_ls",
  "as_mid_rs", "tza_mid_rs", "tzp_mid_rs", "pza_mid_rs",
  "pzpl_base_rs", "cz_base_rs", "cz_base_ls", "pzpl_base_ls",
  "pza_base_ls", "as_base_ls", "tza_base_ls", "tzp_base_ls",
  "tzp_base_rs", "tza_base_rs", "as_base_rs", "pza_base_rs",
  "pzpm_base_ls", "pzpm_base_rs", "sv_base_rs", "sv_base_ls",
]);
const REGION_SET = new Set(REGION_CODES);
const FIELD_SET = new Set(LESION_FIELDS.map(field => field.name));
const INSTRUMENT = "surgery_c61_resected_lesion";
const REGION_PREFIX = "sur_prostate_regions___";
const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);
const nonempty = value => typeof value === "string" && value.trim().length > 0;

/**
 * Return all blocking errors without mutating the draft. Blank optional fields
 * stay blank; even "Not specified" must be an explicit reviewed raw code.
 * Exclusions retain their instance and written reason in the draft, not the CSV.
 * Reviewed-unknown issues retain their explanation without inventing values.
 */
export function validateReview(state, sectors) {
  const errors = [];
  if (!Array.isArray(sectors) || sectors.length !== 41) {
    errors.push("The sector specification must contain exactly 41 REDCap regions.");
  }
  const seenSectors = new Set();
  if (Array.isArray(sectors)) {
    for (const sector of sectors) {
      if (!isObject(sector) || !REGION_SET.has(sector.code) ||
          sector.column !== `${REGION_PREFIX}${sector.code}`) {
        errors.push("The sector specification contains an unknown region or incorrect import column.");
        continue;
      }
      if (seenSectors.has(sector.code)) {
        errors.push(`The sector specification repeats region ${sector.code}.`);
      }
      seenSectors.add(sector.code);
    }
  }
  if (seenSectors.size !== 41) {
    errors.push("The sector specification is missing one or more of the 41 REDCap regions.");
  }
  if (!isObject(state)) {
    errors.push("A review state is required.");
    return errors;
  }
  if (!nonempty(state.recordId)) {
    errors.push("Enter the REDCap record ID explicitly; the case ID is not a substitute.");
  } else if (/^\s*[=+\-@]/u.test(state.recordId) ||
             /[\u0000-\u0009\u000b\u000c\u000e-\u001f\u007f]/u.test(state.recordId)) {
    // Reject rather than prefixing an apostrophe, which would change the record.
    errors.push("The REDCap record ID is unsafe for spreadsheet export (formula prefix or control character).");
  }
  if (state.showcase === true && typeof state.recordId === "string" &&
      !/^(?:TEST|DEMO)-\S/u.test(state.recordId)) {
    errors.push("Showcase data may only be exported with an explicit TEST- or DEMO- record ID.");
  }
  if (!Array.isArray(state.lesions) || state.lesions.length === 0) {
    errors.push("At least one explicitly reviewed lesion is required.");
    return errors;
  }
  const instances = new Set();
  let includedCount = 0;
  state.lesions.forEach((lesion, index) => {
    const context = `Lesion ${index + 1}`;
    if (!isObject(lesion)) {
      errors.push(`${context}: a lesion object is required.`);
      return;
    }
    if (!Number.isSafeInteger(lesion.instance) || lesion.instance <= 0) {
      errors.push(`${context}: repeat instance must be an explicit positive safe integer.`);
    } else if (instances.has(lesion.instance)) {
      errors.push(`${context}: duplicate repeat instance ${lesion.instance}.`);
    } else {
      instances.add(lesion.instance);
    }
    if (lesion.excluded !== undefined && typeof lesion.excluded !== "boolean") {
      errors.push(`${context}: excluded must be a boolean when supplied.`);
    }
    if (lesion.exclusionReason !== undefined && typeof lesion.exclusionReason !== "string") {
      errors.push(`${context}: exclusion reason must be a string when supplied.`);
    }
    if (lesion.excluded === true) {
      if (!nonempty(lesion.exclusionReason)) {
        errors.push(`${context}: exclusion requires an explicit written reason.`);
      }
      return;
    }
    includedCount += 1;
    if (lesion.pendingRegionEdits !== undefined &&
        (!isObject(lesion.pendingRegionEdits) || Object.keys(lesion.pendingRegionEdits).length > 0)) {
      errors.push(`${context}: document pending region edits with source evidence before export.`);
    }
    if (lesion.reviewed !== true) {
      errors.push(`${context}: the doctor must explicitly confirm review.`);
    }
    if (!Array.isArray(lesion.regions)) {
      errors.push(`${context}: an explicit region selection array is required (it may be empty).`);
    } else {
      const selected = new Set();
      for (const code of lesion.regions) {
        if (!REGION_SET.has(code) || !seenSectors.has(code)) {
          errors.push(`${context}: unknown region code ${String(code)}.`);
        } else if (selected.has(code)) {
          errors.push(`${context}: duplicate selected region ${code}.`);
        }
        selected.add(code);
      }
    }
    if (!Array.isArray(lesion.issues)) {
      errors.push(`${context}: an explicit uncertainty issue list is required.`);
    } else {
      lesion.issues.forEach((issue, issueIndex) => {
        if (!isObject(issue) || issue.resolved !== true || !nonempty(issue.resolution)) {
          errors.push(`${context}: uncertainty ${issueIndex + 1} must be explicitly resolved with a written resolution.`);
        }
        if (isObject(issue)) {
          if (issue.disposition !== undefined &&
              !["resolved", "reviewed_unknown"].includes(issue.disposition)) {
            errors.push(`${context}: uncertainty ${issueIndex + 1} has an invalid disposition.`);
          }
          if (issue.disposition === "reviewed_unknown" &&
              Array.isArray(issue.regionCodes) && issue.regionCodes.length > 0) {
            errors.push(`${context}: uncertainty ${issueIndex + 1} concerns region checkboxes, which have no unknown code; the doctor must settle the region association or exclude the lesion.`);
          }
          if (!Array.isArray(issue.regionCodes) ||
              issue.regionCodes.some(code => !REGION_SET.has(code) || !seenSectors.has(code))) {
            errors.push(`${context}: uncertainty ${issueIndex + 1} has missing or unknown region codes.`);
          }
        }
      });
    }
    if (!isObject(lesion.values)) {
      errors.push(`${context}: clinical field values are required.`);
      return;
    }
    for (const name of Object.keys(lesion.values)) {
      if (!FIELD_SET.has(name)) {
        errors.push(`${context}: unsupported lesion field ${name}; it cannot be silently dropped.`);
      }
    }
    for (const field of LESION_FIELDS) {
      const value = lesion.values[field.name];
      if (value === undefined || value === "") {
        if (field.required) errors.push(`${context}: ${field.label} is required; no default is supplied.`);
        continue;
      }
      if (typeof value !== "string") {
        errors.push(`${context}: ${field.label} must be a string containing a raw REDCap value.`);
      } else if (field.choices) {
        if (!field.choices.some(([code]) => code === value)) {
          errors.push(`${context}: ${field.label} must use a documented raw choice code.`);
        }
      } else if (!/^(?:\d+(?:\.\d+)?|\.\d+)$/u.test(value) ||
                 !Number.isFinite(Number(value)) ||
                 Number(value) < field.min || Number(value) > field.max) {
        errors.push(`${context}: ${field.label} must be a decimal number from ${field.min} to ${field.max}.`);
      }
    }
  });
  if (includedCount === 0) {
    errors.push("At least one included, explicitly reviewed lesion is required; all lesions are excluded.");
  }
  return errors;
}

function csvCell(value) {
  const text = String(value);
  return /[",\r\n]/u.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/**
 * First-import draft: one row per INCLUDED explicit instance, sorted numerically
 * without renumbering. Excluded lesions stay unchanged in the review state.
 * No surgery row, defaults, automatic numbering, or "Complete" status. Resolved
 * and reviewed-unknown issue dispositions do not supply clinical field values.
 * Existing-record update/clearing semantics are outside this MVP; the doctor
 * must check REDCap's import comparison table before saving.
 */
export function buildLesionCsv(state, sectors) {
  const errors = validateReview(state, sectors);
  if (errors.length) throw new Error(`Cannot export review:\n${errors.join("\n")}`);
  const header = [
    "record_id", "redcap_repeat_instrument", "redcap_repeat_instance", "all_sgm___1",
    ...REGION_CODES.map(code => `${REGION_PREFIX}${code}`),
    ...LESION_FIELDS.map(field => field.name), `${INSTRUMENT}_complete`,
  ];
  const rows = state.lesions.filter(lesion => lesion.excluded !== true)
    .sort((a, b) => a.instance - b.instance).map(lesion => {
      const selected = new Set(lesion.regions);
      return [
        state.recordId, INSTRUMENT, lesion.instance, "0",
        ...REGION_CODES.map(code => selected.has(code) ? "1" : "0"),
        ...LESION_FIELDS.map(field => lesion.values[field.name] ?? ""), "0",
      ];
    });
  return [header, ...rows].map(row => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
