import { LESION_FIELDS } from "./redcap.js";
import { sectorCodes } from "./sector-spec.js";

const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const nonempty = value => typeof value === "string" && value.trim().length > 0;
const fail = message => { throw new Error(`Cannot adapt showcase analysis: ${message}`); };
const fields = new Map(LESION_FIELDS.map(field => [field.name, field]));
const statuses = new Set(["recorded", "not reported", "unreadable", "not assessed", "not applicable"]);
const bases = new Set(["explicit", "normalized", "inferred", "calculated"]);

function keys(value, allowed, context) {
  if (!object(value)) fail(`${context} must be an object.`);
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) fail(`${context}: unsupported key ${key}.`);
  }
}

function index(items, context) {
  if (!Array.isArray(items)) fail(`${context} must be an array.`);
  const result = new Map();
  for (const item of items) {
    if (!object(item) || !nonempty(item.id) || result.has(item.id)) {
      fail(`${context} has a missing or duplicate identifier.`);
    }
    result.set(item.id, item);
  }
  return result;
}

async function sha256(text) {
  if (!globalThis.crypto?.subtle) fail("Web Crypto SHA-256 is required.");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Separate, synthetic UI-ready contract, not the report-extractor contract.
 * Declared REDCap field names determine axes and scope; no clinical parsing,
 * defaults, scan association, demoAssignments or network calls are involved.
 * Every returned lesion starts unreviewed with blocking showcase issues.
 */
export async function adaptShowcaseAnalysis(raw, sectors, { caseId, reportText, showcase } = {}) {
  if (showcase !== true) fail("This synthetic contract requires showcase:true.");
  if (!nonempty(caseId) || typeof reportText !== "string") fail("caseId and exact reportText are required.");
  const codes = sectorCodes(sectors, "Cannot adapt showcase analysis");
  keys(raw, ["schema_version", "mode", "report_sha256", "evidence", "lesions"], "Envelope");
  if (raw.schema_version !== "doctor-review-showcase-v1" || raw.mode !== "synthetic") {
    fail("Unsupported schema_version or mode.");
  }
  const hash = await sha256(reportText);
  if (raw.report_sha256 !== hash) fail("Report SHA-256 does not match exact UTF-8 reportText.");
  const evidence = index(raw.evidence, "Evidence");
  const anchors = new Map();
  for (const anchor of evidence.values()) {
    keys(anchor, ["id", "quotation"], `Evidence ${anchor.id}`);
    if (!nonempty(anchor.quotation)) fail(`Evidence ${anchor.id} needs a nonempty quotation.`);
    const offset = reportText.indexOf(anchor.quotation);
    // Advance by one UTF-16 unit to detect even overlapping repeated matches.
    if (offset < 0 || reportText.indexOf(anchor.quotation, offset + 1) !== -1) {
      fail(`Evidence ${anchor.id} quotation must occur exactly once in reportText.`);
    }
    // Extractor offsets count Unicode code points, not JavaScript UTF-16 units.
    const start = [...reportText.slice(0, offset)].length;
    anchors.set(anchor.id, {
      ...structuredClone(anchor), start_offset: start,
      end_offset: start + [...anchor.quotation].length, source_text_sha256: hash,
    });
  }
  const resolve = (ids, context, required) => {
    if (!Array.isArray(ids) || (required && ids.length === 0) ||
        new Set(ids).size !== ids.length) fail(`${context}: invalid or empty evidence reference list.`);
    return ids.map(id => {
      if (typeof id !== "string" || !anchors.has(id)) fail(`${context}: unknown evidence reference ${String(id)}.`);
      return structuredClone(anchors.get(id));
    });
  };
  const inputs = index(raw.lesions, "Lesions");
  if (!inputs.size) fail("At least one synthetic lesion is required.");
  const lesions = [...inputs.values()].map((input, index) => {
    keys(input, ["id", "label", "fields", "regions", "region_evidence_ids", "region_reason"], `Lesion ${input.id}`);
    if (!nonempty(input.label) || !object(input.fields)) fail(`Lesion ${input.id} needs a label and fields object.`);
    if (!Array.isArray(input.regions) || new Set(input.regions).size !== input.regions.length ||
        input.regions.some(code => typeof code !== "string" || !codes.has(code))) {
      fail(`Lesion ${input.id} has invalid or duplicate region codes.`);
    }
    const regionEvidence = resolve(input.region_evidence_ids, `Lesion ${input.id} regions`, input.regions.length > 0);
    if (typeof input.region_reason !== "string" || (input.regions.length > 0 && !nonempty(input.region_reason))) {
      fail(`Lesion ${input.id} needs a written region_reason for supplied regions.`);
    }
    const lesion = {
      id: input.id, instance: index + 1, label: input.label, regions: [...input.regions],
      values: Object.fromEntries(LESION_FIELDS.map(field => [field.name, ""])),
      issues: [], reviewed: false, sourceObservations: [],
    };
    const issue = (suffix, message, regionCodes = [], extra = {}) => {
      lesion.issues.push({
        id: `${input.id}:${suffix}`, message, regionCodes: [...regionCodes],
        resolved: false, resolution: "", sourceRef: input.id,
        hint: "Review the synthetic JSON and its own evidence, not the unrelated displayed scans.", ...extra,
      });
    };
    issue("showcase-unlinked", "SHOWCASE ONLY: synthetic UI-ready input and displayed scans are unlinked. These values are fabricated, not analysis of the scans.");
    for (const code of input.regions) {
      issue(`showcase-region:${code}`, `SHOWCASE ONLY: ${code} is a fabricated sector placement, not a finding from the displayed drawing.`,
        [code], { showcaseOnly: true, sourceRef: `${input.id}:regions`,
          hint: input.region_reason, evidence: structuredClone(regionEvidence) });
    }
    for (const [name, supplied] of Object.entries(input.fields)) {
      const field = fields.get(name);
      if (!field) fail(`Lesion ${input.id}: unknown or non-lesion field ${name}.`);
      keys(supplied, ["value", "status", "basis", "evidence_ids", "reason", "coverage_checked", "source_complete"],
        `Field ${input.id}:${name}`);
      if (!statuses.has(supplied.status) || !bases.has(supplied.basis)) {
        fail(`Field ${input.id}:${name} has an invalid status or basis.`);
      }
      if (supplied.reason !== undefined && !nonempty(supplied.reason)) {
        fail(`Field ${input.id}:${name} reason must be a nonempty string when supplied.`);
      }
      const recorded = supplied.status === "recorded";
      const resolved = resolve(supplied.evidence_ids, `Field ${input.id}:${name}`, supplied.status !== "not reported");
      if (recorded) {
        if (typeof supplied.value !== "string" || supplied.value === "") {
          fail(`Field ${input.id}:${name} needs a nonempty raw REDCap string.`);
        }
        if (field.choices) {
          if (!field.choices.some(([code]) => code === supplied.value)) {
            fail(`Field ${input.id}:${name} has an invalid raw choice code.`);
          }
        } else if (!/^(?:\d+(?:\.\d+)?|\.\d+)$/u.test(supplied.value) ||
                   !Number.isFinite(Number(supplied.value)) ||
                   Number(supplied.value) < field.min || Number(supplied.value) > field.max) {
          fail(`Field ${input.id}:${name} must be a decimal number from ${field.min} to ${field.max}.`);
        }
        if (["inferred", "calculated"].includes(supplied.basis) && !nonempty(supplied.reason)) {
          fail(`Field ${input.id}:${name}: inferred or calculated values require explicit reasoning.`);
        }
        lesion.values[name] = supplied.value;
      } else {
        if (supplied.value !== null) fail(`Unavailable field ${input.id}:${name} must have value:null.`);
        if (supplied.status === "not reported" &&
            (supplied.coverage_checked !== true || supplied.source_complete !== true)) {
          fail(`Field ${input.id}:${name}: not reported requires complete checked coverage.`);
        }
      }
      const observationId = `${input.id}:${name}`;
      lesion.sourceObservations.push({
        id: observationId, subject_id: input.id, property: name, status: supplied.status, basis: supplied.basis,
        value: recorded ? {
          type: field.type === "number" ? "quantity" : "coded",
          original_wording: resolved.map(anchor => anchor.quotation).join("\n"),
          raw_code: supplied.value,
        } : null,
        evidence_ids: [...supplied.evidence_ids], evidence: resolved,
        certainty: { extraction: "unassessed", interpretation: "unassessed" },
        ...(supplied.reason !== undefined ? { reason: supplied.reason } : {}),
        ...(!recorded ? { unavailable_reason: supplied.reason ?? `JSON marks this property as ${supplied.status}.` } : {}),
      });
      if (!recorded || ["inferred", "calculated"].includes(supplied.basis)) {
        issue(`field-review:${name}`, `${field.label}: ${recorded ? supplied.basis : supplied.status}; doctor review is required. No unknown/default value has been substituted.`,
          [], { sourceRef: observationId, hint: supplied.reason ?? `Source status: ${supplied.status}.` });
      }
    }
    return lesion;
  });
  return {
    schemaVersion: "doctor-review-analysis-v1", caseId, recordId: "", showcase: true,
    sourceBinding: "showcase-unlinked", sourceAnalysis: structuredClone(raw), reportText, lesions,
  };
}
