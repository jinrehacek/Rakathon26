import { LESION_FIELDS } from "./redcap.js";

const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const nonempty = value => typeof value === "string" && value.trim().length > 0;
const positiveInteger = value => Number.isSafeInteger(value) && value > 0;
const fields = new Set(LESION_FIELDS.map(field => field.name));
const mutableIssueKeys = new Set(["resolution", "resolved", "reopenedReason", "disposition"]);

function equal(left, right) {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length &&
      left.every((value, index) => equal(value, right[index]));
  }
  if (!object(left) || !object(right)) return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length &&
    keys.every(key => Object.hasOwn(right, key) && equal(left[key], right[key]));
}

/** Validate a doctor's anchor against the unchanged local report or image. */
export function validateEvidence(evidence, context, { allowAbsent = false, reportOnly = false } = {}) {
  const errors = [];
  if (!object(evidence)) return ["Evidence must be an object."];
  if (!nonempty(evidence.reason)) errors.push("Evidence requires a written reason.");
  if (evidence.kind === "absent") {
    if (!allowAbsent) errors.push("Absent evidence is not allowed here.");
    if (evidence.basis !== "absent") errors.push("Absent evidence must use basis absent.");
    return errors;
  }
  if (!["explicit", "inferred"].includes(evidence.basis)) {
    errors.push("Evidence basis must be explicit or inferred.");
  }
  if (reportOnly && evidence.source !== "report") {
    errors.push("A report anchor is required; a drawing mark alone cannot create a lesion.");
  }
  if (evidence.kind === "text") {
    if (evidence.source !== "report") errors.push("Text evidence must refer to the report.");
    if (!nonempty(evidence.quotation)) errors.push("Text evidence requires a nonempty quotation.");
    const text = typeof context?.reportText === "string" ? [...context.reportText] : null;
    if (!text || !Number.isSafeInteger(evidence.start) || !Number.isSafeInteger(evidence.end) ||
        evidence.start < 0 || evidence.end <= evidence.start || evidence.end > text.length) {
      errors.push("Text offsets must be in-bounds, half-open Unicode code point offsets.");
    } else if (text.slice(evidence.start, evidence.end).join("") !== evidence.quotation) {
      errors.push("The quotation does not match the report at these offsets.");
    }
  } else if (evidence.kind === "image_crop") {
    if (!["report", "drawing"].includes(evidence.source)) {
      errors.push("Image evidence must refer to the report or drawing.");
    }
    const expected = context?.sources?.[evidence.source]?.sha256;
    if (!nonempty(evidence.sha256) || !nonempty(expected) || evidence.sha256 !== expected) {
      errors.push("Image evidence must match the source SHA-256.");
    }
    const size = context?.imageSizes?.[evidence.source];
    const bounds = evidence.bounds;
    if (!positiveInteger(size?.width) || !positiveInteger(size?.height)) {
      errors.push("The actual source image dimensions are required.");
    } else if (!Array.isArray(bounds) || bounds.length !== 4 ||
        !bounds.every(Number.isSafeInteger) || bounds[0] < 0 || bounds[1] < 0 ||
        bounds[2] <= 0 || bounds[3] <= 0 ||
        bounds[0] > size.width - bounds[2] || bounds[1] > size.height - bounds[3]) {
      errors.push("Image crop bounds must be positive-sized integer pixels within the source image.");
    }
  } else {
    errors.push("Unknown evidence kind.");
  }
  return errors;
}

/** Allocate a stable instance without reusing excluded records or changing state. */
export function createDoctorLesion(state, evidence, context) {
  const errors = validateEvidence(evidence, context, { reportOnly: true });
  if (errors.length) throw new Error(errors.join(" "));
  if (!object(state) || !Array.isArray(state.lesions)) throw new Error("Lesions must be an array.");
  let maximum = 0;
  const instances = new Set();
  for (const lesion of state.lesions) {
    if (!object(lesion) || !positiveInteger(lesion.instance) || instances.has(lesion.instance)) {
      throw new Error("Existing lesion instances must be unique positive safe integers.");
    }
    instances.add(lesion.instance);
    maximum = Math.max(maximum, lesion.instance);
  }
  if (maximum === Number.MAX_SAFE_INTEGER) throw new Error("Lesion instances are exhausted.");
  const instance = maximum + 1;
  return {
    id: `doctor-${crypto.randomUUID()}`, doctorAdded: true, instance,
    label: `Doctor-added lesion ${instance}`, regions: [], values: {}, issues: [],
    sourceObservations: [], reviewed: false, creationEvidence: structuredClone(evidence),
  };
}

function issueDefinition(issue) {
  return Object.fromEntries(Object.entries(issue).filter(([key]) => !mutableIssueKeys.has(key)));
}

function validIssues(issues, originals) {
  return Array.isArray(issues) && Array.isArray(originals) && issues.length === originals.length &&
    originals.every((original, index) => {
      const issue = issues[index];
      return object(original) && object(issue) && equal(issueDefinition(issue), issueDefinition(original)) &&
        typeof issue.resolved === "boolean" && typeof issue.resolution === "string" &&
        (issue.reopenedReason === undefined || typeof issue.reopenedReason === "string") &&
        (issue.disposition === undefined || ["unresolved", "resolved", "reviewed_unknown"].includes(issue.disposition));
    });
}

function validEvidenceMaps(lesion, knownRegions, context) {
  if (lesion.pendingRegionEdits !== undefined) {
    if (!object(lesion.pendingRegionEdits)) return false;
    for (const [code, change] of Object.entries(lesion.pendingRegionEdits)) {
      if (!knownRegions.has(code) || !object(change) || typeof change.from !== "boolean" ||
          typeof change.to !== "boolean" || change.from === change.to ||
          change.to !== lesion.regions.includes(code) || lesion.reviewed) return false;
    }
  }
  if (lesion.valueEvidence !== undefined) {
    if (!object(lesion.valueEvidence)) return false;
    for (const [field, evidence] of Object.entries(lesion.valueEvidence)) {
      if (!fields.has(field)) return false;
      const value = lesion.values[field];
      const allowAbsent = value === "" ||
        (["extracaps_ext", "perineural_inv_sur"].includes(field) && value === "4");
      if (validateEvidence(evidence, context, { allowAbsent }).length) return false;
    }
  }
  if (lesion.regionEvidence !== undefined) {
    if (!object(lesion.regionEvidence)) return false;
    for (const [code, evidence] of Object.entries(lesion.regionEvidence)) {
      if (!knownRegions.has(code) || validateEvidence(evidence, context).length) return false;
    }
  }
  return true;
}

/** Validate a saved draft, retaining immutable prediction provenance and instances. */
export function validSavedReview(saved, prediction, sectors, context) {
  if (!object(saved) || !object(prediction) || !Array.isArray(sectors) ||
      !Array.isArray(prediction.lesions) || !Array.isArray(saved.lesions)) return false;
  for (const key of ["schemaVersion", "caseId", "showcase", "sourceBinding", "sourceAnalysis", "reportText"]) {
    if (!equal(saved[key], prediction[key])) return false;
  }
  if (typeof saved.recordId !== "string" || !Array.isArray(saved.reviewLog) ||
      !saved.reviewLog.every(entry => object(entry) && typeof entry.at === "string" &&
        typeof entry.action === "string" && typeof entry.actor === "string" && object(entry.details))) return false;
  const originals = new Map();
  for (const original of prediction.lesions) {
    if (!object(original) || !nonempty(original.id) || originals.has(original.id)) return false;
    originals.set(original.id, original);
  }
  const knownRegions = new Set(sectors.map(sector => sector?.code));
  const ids = new Set(), instances = new Set();
  for (const lesion of saved.lesions) {
    if (!object(lesion) || !nonempty(lesion.id) || ids.has(lesion.id) ||
        !positiveInteger(lesion.instance) || instances.has(lesion.instance) ||
        !nonempty(lesion.label) || typeof lesion.reviewed !== "boolean" ||
        !Array.isArray(lesion.regions) || new Set(lesion.regions).size !== lesion.regions.length ||
        !lesion.regions.every(code => typeof code === "string" && knownRegions.has(code)) ||
        !object(lesion.values) || !Object.entries(lesion.values).every(([key, value]) =>
          fields.has(key) && typeof value === "string") ||
        (lesion.excluded !== undefined && typeof lesion.excluded !== "boolean") ||
        (lesion.excluded === true && !nonempty(lesion.exclusionReason)) ||
        (lesion.doctorAdded !== undefined && typeof lesion.doctorAdded !== "boolean")) return false;
    ids.add(lesion.id);
    instances.add(lesion.instance);
    const original = originals.get(lesion.id);
    if (original) {
      if (lesion.doctorAdded === true || lesion.instance !== original.instance ||
          !equal(lesion.sourceObservations, original.sourceObservations) ||
          !validIssues(lesion.issues, original.issues)) return false;
      if (lesion.creationEvidence !== undefined &&
          validateEvidence(lesion.creationEvidence, context, { reportOnly: true }).length) return false;
    } else if (lesion.doctorAdded !== true || !Array.isArray(lesion.sourceObservations) ||
        lesion.sourceObservations.length !== 0 || !Array.isArray(lesion.issues) || lesion.issues.length !== 0 ||
        validateEvidence(lesion.creationEvidence, context, { reportOnly: true }).length) return false;
    if (!validEvidenceMaps(lesion, knownRegions, context)) return false;
  }
  return [...originals.keys()].every(id => ids.has(id));
}
