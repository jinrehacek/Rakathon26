import { LESION_FIELDS } from "./redcap.js";
import { adaptShowcaseAnalysis } from "./showcase-analysis.js";
import { sectorCodes } from "./sector-spec.js";

const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const text = value => typeof value === "string" && value.trim().length > 0;
const copy = value => structuredClone(value);
const fail = message => { throw new Error(`Cannot adapt analysis: ${message}`); };
const statuses = new Set(["recorded", "not reported", "unreadable", "not assessed", "not applicable"]);
const bases = new Set(["explicit", "normalized", "inferred", "calculated"]);

function index(items, name) {
  if (!Array.isArray(items)) fail(`${name} must be an array.`);
  const result = new Map();
  for (const item of items) {
    if (!object(item) || !text(item.id) || result.has(item.id)) {
      fail(`${name} contains an invalid or duplicate identifier.`);
    }
    result.set(item.id, item);
  }
  return result;
}

function references(ids, lookup, context, required = false) {
  if (!Array.isArray(ids) || (required && !ids.length)) fail(`${context}: reference list is missing.`);
  for (const id of ids) {
    if (typeof id !== "string" || !lookup.has(id)) fail(`${context}: unknown reference ${String(id)}.`);
  }
}

function rejectCycles(nodes, dependencies, name) {
  const completed = new Set();
  for (const start of nodes.keys()) {
    const path = new Set();
    const visit = id => {
      if (path.has(id)) fail(`${name} contains a reference cycle.`);
      if (completed.has(id)) return;
      path.add(id);
      for (const dependency of dependencies(nodes.get(id))) visit(dependency);
      path.delete(id);
      completed.add(id);
    };
    visit(start);
  }
}

async function sha256(value) {
  if (!globalThis.crypto?.subtle) fail("Web Crypto SHA-256 is required in this browser context.");
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Accept the report-extraction-v1 fixture or the separate UI-ready synthetic
 * showcase contract. Neither adapter performs extraction or associates its
 * text with any displayed scan.
 * Raw observations (including unavailable values, certainty and unmapped fields)
 * are retained. The report-only fixture maps evidenced patterns and explicitly
 * labelled dimensions; the UI-ready showcase supplies the lesion fields directly.
 *
 * result.json bundles and other envelopes are deliberately rejected rather than
 * guessed. No network, source files, external models or image processing.
 */
export async function adaptAnalysis(raw, sectors, {
  caseId, reportText, showcase = false, demoAssignments,
} = {}) {
  if (!text(caseId) || typeof reportText !== "string") fail("caseId and exact reportText are required.");
  if (typeof showcase !== "boolean") fail("showcase must be a boolean.");
  const codes = sectorCodes(sectors);
  if (object(raw) && raw.schema_version === "doctor-review-showcase-v1") {
    return adaptShowcaseAnalysis(raw, sectors, { caseId, reportText, showcase });
  }
  if (!object(raw) || raw.mode !== "fixture" || raw.prompt_version !== "report-extraction-v1" ||
      raw.output_contract_version !== "1.0.0" || !object(raw.response)) {
    fail("Unsupported envelope; expected the versioned synthetic fixture response.");
  }
  const payload = raw.response;
  const hash = await sha256(reportText);
  if (raw.for_text_sha256 !== hash || payload.source_text_sha256 !== hash) {
    fail("Report SHA-256 does not match both the fixture envelope and response.");
  }
  const evidence = index(payload.evidence, "evidence");
  const subjects = index(payload.subjects, "subjects");
  const observations = index(payload.observations, "observations");
  const coverage = index(payload.coverage, "coverage");
  const inputIssues = index(payload.issues, "issues");
  // The extractor uses Python Unicode code-point offsets, not JS UTF-16 offsets.
  const characters = [...reportText];
  const layers = new Set();
  for (const anchor of evidence.values()) {
    if (!text(anchor.text_layer_id) || anchor.page !== 1 ||
        !Number.isSafeInteger(anchor.start_offset) || !Number.isSafeInteger(anchor.end_offset) ||
        anchor.start_offset < 0 || anchor.end_offset <= anchor.start_offset ||
        anchor.end_offset > characters.length || !text(anchor.quotation) ||
        characters.slice(anchor.start_offset, anchor.end_offset).join("") !== anchor.quotation) {
      fail(`Evidence ${anchor.id} has invalid text offsets, page or quotation.`);
    }
    if (anchor.image_region != null) fail(`Text-only fixture evidence ${anchor.id} cannot claim image coordinates.`);
    layers.add(anchor.text_layer_id);
  }
  if (layers.size > 1) fail("Fixture evidence refers to multiple text layers.");
  for (const subject of subjects.values()) {
    references(subject.evidence_ids, evidence, `Subject ${subject.id} evidence`, true);
    if (!["specimen", "tumour_focus", "other_finding", "tissue_sample"].includes(subject.kind) ||
        !text(subject.label) || !["explicit", "proposed"].includes(subject.identification_basis)) {
      fail(`Subject ${subject.id} has an unsupported kind, label or identification basis.`);
    }
    if (subject.parent_id != null) references([subject.parent_id], subjects, `Subject ${subject.id} parent`);
  }
  rejectCycles(subjects, subject => subject.parent_id == null ? [] : [subject.parent_id], "Subjects");
  for (const check of coverage.values()) references([check.subject_id], subjects, `Coverage ${check.id} subject`);
  for (const observation of observations.values()) {
    references([observation.subject_id], subjects, `Observation ${observation.id} subject`);
    references(observation.evidence_ids ?? [], evidence, `Observation ${observation.id} evidence`,
      observation.status === "recorded");
    references(observation.derived_from ?? [], observations, `Observation ${observation.id} derivation`);
    if (!statuses.has(observation.status) || !bases.has(observation.basis) || !text(observation.property)) {
      fail(`Observation ${observation.id} has an unsupported status, basis or property.`);
    }
    if (observation.status === "recorded" ? !object(observation.value) : observation.value != null) {
      fail(`Observation ${observation.id} value contradicts its availability status.`);
    }
    if (observation.status === "not reported" && ![...coverage.values()].some(check =>
      check.subject_id === observation.subject_id && check.property === observation.property &&
      check.checked === true && check.source_complete === true)) {
      fail(`Observation ${observation.id}: not reported requires complete coverage.`);
    }
  }
  rejectCycles(observations, observation => observation.derived_from ?? [], "Observations");
  for (const issue of inputIssues.values()) {
    if (!text(issue.summary)) fail(`Extraction issue ${issue.id} needs a summary.`);
    references(issue.evidence_ids, evidence, `Issue ${issue.id} evidence`, true);
    references(issue.alternative_subject_ids, subjects, `Issue ${issue.id} subjects`, true);
    if (issue.subject_id !== undefined) references([issue.subject_id], subjects, `Issue ${issue.id} subject`);
  }
  const focuses = [...subjects.values()].filter(subject => subject.kind === "tumour_focus");
  if (!focuses.length) fail("No report tumour-focus subjects are available; marks do not create lesions.");
  const focusIds = new Set(focuses.map(subject => subject.id));
  if (demoAssignments !== undefined) {
    if (!showcase || !object(demoAssignments)) fail("Demo assignments require showcase:true and a subject-to-code object.");
    for (const [id, assigned] of Object.entries(demoAssignments)) {
      if (!focusIds.has(id)) fail(`Demo assignment references unknown tumour focus ${id}.`);
      if (!Array.isArray(assigned) || assigned.some(code => !codes.has(code)) ||
          new Set(assigned).size !== assigned.length) {
        fail(`Demo assignment for ${id} has unknown or duplicate canonical sector codes.`);
      }
    }
  }
  const resolveEvidence = ids => ids.map(id => ({
    ...copy(evidence.get(id)), source_text_sha256: hash,
  }));
  const lesions = focuses.map((subject, index) => {
    const sourceObservations = [...observations.values()]
      .filter(observation => observation.subject_id === subject.id)
      .map(observation => ({
        ...copy(observation), evidence: resolveEvidence(observation.evidence_ids ?? []),
      }));
    const lesion = {
      id: subject.id, instance: index + 1, label: subject.label,
      regions: showcase ? [...(demoAssignments?.[subject.id] ?? [])] : [],
      values: Object.fromEntries(LESION_FIELDS.map(field => [field.name, ""])),
      issues: [], reviewed: false, sourceObservations,
    };
    const addIssue = (suffix, message, regionCodes = [], extra = {}) => {
      lesion.issues.push({
        id: `${subject.id}:${suffix}`, message, regionCodes: [...regionCodes],
        resolved: false, resolution: "", ...extra,
      });
    };
    if (showcase) {
      addIssue("showcase-unlinked", "SHOWCASE ONLY: the synthetic text/model fixture and displayed scans are unlinked. No correspondence or scan analysis is claimed.");
    }
    for (const code of lesion.regions) {
      addIssue(`showcase-region:${code}`, `SHOWCASE ONLY: ${code} is a fabricated demo placement, not a model prediction or finding from the displayed drawing.`,
        [code], { showcaseOnly: true });
    }
    // Global/specimen attribution issues also block every focus; none disappear
    // merely because they do not name one of the displayed lesions.
    for (const issue of inputIssues.values()) {
      addIssue(`extraction:${issue.id}`, `Extraction issue: ${issue.summary}`, [], {
        sourceIssue: copy(issue), evidence: resolveEvidence(issue.evidence_ids),
      });
    }
    if (subject.identification_basis !== "explicit") {
      addIssue("proposed-focus", "The tumour-focus identity was proposed, not explicitly identified in the report.");
    }
    const candidates = new Map();
    const offer = (field, value, observation) => {
      if (!candidates.has(field)) candidates.set(field, []);
      candidates.get(field).push({ value, observationId: observation.id });
    };
    for (const observation of sourceObservations) {
      if (observation.status !== "recorded") continue;
      if (!["explicit", "normalized"].includes(observation.basis) ||
          (observation.derived_from ?? []).length ||
          observation.review_status === "rejected") {
        addIssue(`unmapped:${observation.id}`, `${observation.property}: inferred, derived or rejected values were retained but not prefilled.`);
        continue;
      }
      const value = observation.value;
      const quotation = observation.evidence.map(anchor => anchor.quotation).join("\n");
      if (["gleason_patterns", "gleason_score"].includes(observation.property) &&
          value.type === observation.property) {
        const primary = value.primary_pattern;
        const secondary = value.secondary_pattern;
        if (!Number.isInteger(primary) || primary < 1 || primary > 5 ||
            !Number.isInteger(secondary) || secondary < 1 || secondary > 5 ||
            (value.type === "gleason_score" && value.total !== primary + secondary) ||
            !new RegExp(`\\b${primary}\\s*\\+\\s*${secondary}\\b`, "u").test(quotation)) {
          addIssue(`unmapped:${observation.id}`, "Gleason patterns are invalid or not supported by the quoted pattern pair; retained without prefilling.");
          continue;
        }
        offer("gleason_prim_grade", String(primary), observation);
        offer("gleason_sec_grade", String(secondary), observation);
      } else if (observation.property === "dimensions" && value.type === "dimensions") {
        const measurements = value.measurements;
        const axes = new Set();
        const supported = Array.isArray(measurements) && measurements.length > 0 &&
          measurements.every(measurement => {
            if (!object(measurement) || !["x", "y", "z"].includes(measurement.axis) ||
                axes.has(measurement.axis) || measurement.unit !== "mm" || measurement.approximate === true ||
                typeof measurement.value !== "number" || !Number.isFinite(measurement.value) ||
                measurement.value <= 0 || measurement.value > 100) return false;
            axes.add(measurement.axis);
            const number = String(measurement.value).replace(".", "\\.");
            return new RegExp(`\\b${measurement.axis}\\s*[:=]?\\s*${number}\\s*mm\\b`, "iu").test(quotation);
          });
        if (!supported) {
          addIssue(`dimensions:${observation.id}`, "Dimensions retained but x/y/z left empty: explicit x/y/z axis labels and exact supported mm values are required. Measurement order is not an axis.");
          continue;
        }
        for (const measurement of measurements) {
          offer(`lesion_${measurement.axis}_mm`, String(measurement.value), observation);
        }
      }
      // Other properties, totals, percentages and specimen classifications have
      // no implemented mapping. They remain unchanged in sourceObservations/raw.
    }
    for (const [field, proposed] of candidates) {
      const distinct = new Set(proposed.map(candidate => candidate.value));
      if (distinct.size === 1) lesion.values[field] = proposed[0].value;
      else addIssue(`conflict:${field}`, `Conflicting source observations for ${field}; kept all observations and left the field empty.`,
        [], { sourceObservationIds: proposed.map(candidate => candidate.observationId) });
    }
    return lesion;
  });
  return {
    schemaVersion: "doctor-review-analysis-v1", caseId, recordId: "", showcase,
    sourceBinding: "showcase-unlinked", sourceAnalysis: copy(raw), reportText, lesions,
  };
}
