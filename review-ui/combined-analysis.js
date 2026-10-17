import { sectorCodes } from "./sector-spec.js";
import { LESION_FIELDS } from "./redcap.js";
import { SURGERY_FIELDS } from "./surgery.js";

const copy = value => structuredClone(value);
const fail = message => { throw new Error(`Cannot open combined assessment: ${message}`); };
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const statuses = new Set(["recorded", "not reported", "unreadable", "not assessed", "not applicable"]);
const bases = new Set(["explicit", "normalized", "inferred", "calculated"]);
export async function digest(bytes) {
  const data = typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))].map(b => b.toString(16).padStart(2, "0")).join("");
}
const index = (items, name) => {
  if (!Array.isArray(items)) fail(`${name} must be an array.`);
  const map = new Map();
  for (const item of items) {
    if (!object(item) || typeof item.id !== "string" || !item.id || map.has(item.id)) fail(`${name} contains missing or duplicate IDs.`);
    map.set(item.id, item);
  }
  return map;
};

export function projectProperty(assessment, scope = "lesion") {
  const p = assessment.property, v = assessment.value;
  if (assessment.disposition === "unresolved" || assessment.review_status === "rejected") return {};
  const presence = { extraprostatic_extension: "extracaps_ext", perineural_invasion: "perineural_inv_sur" };
  if (scope === "lesion" && presence[p]) {
    if (assessment.status === "not reported") return { [presence[p]]: "4" };
    if (assessment.status === "recorded" && v?.type === "presence") return { [presence[p]]: { present: "1", absent: "3", indeterminate: "2" }[v.value] };
    return {};
  }
  if (assessment.status !== "recorded" || !v) return {};
  if (scope === "lesion") {
    if (p === "histology_type" && v.type === "coded") return { hist_type_sur: v.code };
    if (p === "gleason_patterns" && v.type === "gleason_patterns") {
      const out = {};
      for (const [part, suffix] of [["primary", "prim"], ["secondary", "sec"], ["tertiary", "tert"]]) {
        const pattern = v[part]?.pattern ?? v[`${part}_pattern`];
        if (pattern != null) out[`gleason_${suffix}_grade`] = String(pattern);
        if (v[part]?.percent != null) out[`gleason_${suffix}_perc`] = String(v[part].percent);
      }
      return out;
    }
    if (p === "dimensions" && v.type === "dimensions") {
      const out = {}, seen = new Set();
      for (const m of v.measurements || []) {
        if (!["x", "y", "z"].includes(m.axis) || m.unit !== "mm" || m.approximate || seen.has(m.axis)) return {};
        seen.add(m.axis); out[`lesion_${m.axis}_mm`] = String(m.value);
      }
      return out;
    }
  } else {
    const classifications = { classification_pt: "pt_surg", classification_pn: "pn_surg", classification_pm: "pm_surg", classification_r: "classify_r_surg", classification_l: "classify_l_surg", classification_v: "vascular_inv" };
    if (classifications[p] && v.type === "classification") {
      const field = SURGERY_FIELDS.find(f => f.name === classifications[p]);
      const code = v.normalized_code || v.original_code;
      const choice = field.choices.find(([, label]) => label.toLowerCase() === code?.toLowerCase());
      return choice ? { [field.name]: choice[0] } : {};
    }
    if (p === "grade_group" && v.type === "coded") return { isup: v.code };
    if (p === "histology" && v.type === "coded") return { histol_post_surg: v.code };
    if (["lymph_nodes_examined", "lymph_nodes_positive"].includes(p) && v.type === "quantity" && !v.approximate) return { [p === "lymph_nodes_examined" ? "node_no_surgery" : "node_positive_no_surgery"]: String(v.value) };
    if (p === "conclusion_text" && v.type === "text") return { surgery_text: v.text };
    if (p === "reported_lesion_count" && v.type === "quantity" && !v.approximate && Number.isInteger(v.value)) return v.value >= 1 && v.value <= 6 ? { total_number_lesion_surg: String(v.value) } : { total_number_lesion_surg: "7", total_number_lesion_surg_oth: String(v.value) };
  }
  return {};
}

// The caller supplies the exact serialized input bytes; reserialization cannot
// prove a pinned hash. Scans are checked separately before being displayed.
export async function adaptCombined(raw, sectors, { reportBytes, drawingBytes } = {}) {
  const codes = sectorCodes(sectors);
  if (raw?.schema_version !== "combined-1" || typeof raw.case_id !== "string" || !raw.case_id.trim()) fail("Expected combined-1 with a case_id.");
  if (raw.pairing?.case_id !== raw.case_id || raw.pairing?.assessment !== "supported") fail("The document pairing is not supported for this case.");
  for (const [role, bytes] of [["report", reportBytes], ["drawing", drawingBytes]]) {
    if (!bytes || await digest(bytes) !== raw.inputs?.[role]?.sha256) fail(`The ${role} JSON does not match its pinned SHA-256.`);
  }
  const decode = bytes => JSON.parse(typeof bytes === "string" ? bytes : new TextDecoder().decode(bytes));
  const report = decode(reportBytes), drawing = decode(drawingBytes);
  if (!["report-2", "report-3"].includes(report.extraction?.output_contract_version) || report.extraction.complete !== true ||
      drawing.extraction?.schema_version !== "drawing-1" || drawing.extraction.case_id !== raw.case_id) fail("Incomplete or unsupported report/drawing contract or case mismatch.");
  if (report.quarantine?.length || report.validation_errors?.length) fail("The report contains quarantined content or validation errors.");
  if (raw.inputs.report.extraction_id && raw.inputs.report.extraction_id !== report.extraction.id) fail("Report extraction ID differs from the pinned input.");
  const reportText = report.text_layer?.text;
  if (typeof reportText !== "string" || await digest(reportText) !== report.text_layer.text_sha256) fail("The report text hash differs.");
  const anchors = index(report.extraction.evidence, "Report evidence");
  const observations = index(report.extraction.observations, "Report observations");
  const subjects = index(report.extraction.subjects, "Report subjects");
  const marks = index(drawing.marks, "Drawing marks");
  const candidates = index(raw.candidates, "Candidates");
  const hypotheses = index(raw.matching?.hypotheses, "Hypotheses");
  const knownRefs = new Set([
    ...[...observations.keys(), ...anchors.keys(), ...subjects.keys()].map(id => `report:${id}`),
    ...marks.keys(), ...candidates.keys(), ...hypotheses.keys(),
    ...(drawing.groups || []).map(group => `group:${group.id}`),
    ...[...raw.decisions_history || [], ...raw.decisions_applied || []].map(d => `decision:${d.id}`),
  ]);
  const chars = [...reportText];
  for (const anchor of anchors.values()) {
    if (anchor.quotation != null && (!Number.isSafeInteger(anchor.start_offset) || !Number.isSafeInteger(anchor.end_offset) || anchor.start_offset < 0 || anchor.end_offset <= anchor.start_offset || chars.slice(anchor.start_offset, anchor.end_offset).join("") !== anchor.quotation)) fail(`Invalid report evidence ${anchor.id}.`);
  }
  const resolveAnchors = assessment => {
    const ids = new Set(assessment.evidence_ids || []);
    for (const ref of [...assessment.supports || [], ...assessment.derived_from || []]) {
      if (ref.startsWith("report:")) for (const id of observations.get(ref.slice(7))?.evidence_ids || []) ids.add(`report:${id}`);
    }
    return [...ids].map(id => anchors.get(id.replace(/^report:/, ""))).filter(Boolean).map(copy);
  };
  const sourceObservations = properties => {
    if (!Array.isArray(properties)) fail("Missing property assessments.");
    const seen = new Set();
    return properties.map(p => {
      if (!statuses.has(p.status) || !bases.has(p.basis) || seen.has(p.property) || !["adopted", "provisional", "unresolved", "unavailable", "not applicable"].includes(p.disposition)) fail(`Invalid or duplicate property ${p.property}.`);
      seen.add(p.property);
      const selected = ["adopted", "provisional"].includes(p.disposition);
      if ((selected && (p.status !== "recorded" || !p.value || !p.supports?.length)) || (!selected && p.value != null)) fail(`Invalid selected value for ${p.property}.`);
      for (const ref of [...p.supports || [], ...p.opposes || [], ...p.evidence_ids || [], ...p.derived_from || []]) {
        if (!knownRefs.has(ref)) fail(`Unknown source reference ${ref} for ${p.property}.`);
      }
      return { ...copy(p), id: p.property, evidence: resolveAnchors(p), certainty: copy(p.source_certainty || {}) };
    });
  };
  const mapped = (properties, scope) => {
    const out = {};
    const fields = scope === "lesion" ? LESION_FIELDS : SURGERY_FIELDS;
    for (const prop of properties) for (const [name, value] of Object.entries(projectProperty(prop, scope))) {
      const field = fields.find(f => f.name === name);
      if (typeof value !== "string" || (field.choices && !field.choices.some(([code]) => code === value)) ||
          (field.type === "number" && (!Number.isFinite(+value) || +value < field.min || +value > field.max))) fail(`Invalid mapped value for ${name}.`);
      if (Object.hasOwn(out, name) && out[name] !== value) fail(`Conflicting mapped values for ${name}.`);
      out[name] = value;
    }
    return out;
  };
  const issue = (id, message, regionCodes = [], extra = {}) => ({ id, message, regionCodes, sourceRef: id, hint: "Inspect the pinned source findings and record your decision.", resolved: false, resolution: "", severity: "question", ...extra });
  const seenOrders = new Set();
  const lesions = [...index(raw.lesions, "Lesions").values()].sort((a, b) => a.order - b.order).map(input => {
    if (!Number.isSafeInteger(input.order) || input.order <= 0 || seenOrders.has(input.order)) fail("Lesion orders must be unique positive integers.");
    seenOrders.add(input.order);
    if (input.kind !== "tumour focus") fail("Only tumour-focus interpretations may become lesion records.");
    if (input.hypothesis && !hypotheses.has(input.hypothesis)) fail("Lesion has an unknown matching hypothesis.");
    if (input.focus && subjects.get(input.focus)?.kind !== "tumour_focus") fail("Lesion focus is missing from the report.");
    for (const id of input.candidates || []) if (!candidates.has(id)) fail("Lesion references an unknown candidate.");
    for (const id of input.marks || []) if (!marks.has(id)) fail("Lesion references an unknown mark.");
    if (!input.focus && !input.supports?.some(ref => ref.startsWith("report:") && observations.has(ref.slice(7)))) fail("A drawing mark alone cannot establish a lesion.");
    for (const list of [input.sectors?.in, input.sectors?.maybe]) if (!Array.isArray(list) || new Set(list).size !== list.length || list.some(code => !codes.has(code))) fail("Invalid sector set.");
    if (input.sectors.in.some(code => input.sectors.maybe.includes(code))) fail("In and maybe sectors overlap.");
    const properties = sourceObservations(input.properties);
    const issues = [issue(`${input.id}:sectors`, `Confirm the proposed sectors. Confidence: ${input.sectors.confidence?.final || "unassessed"}.`, [...new Set([...input.sectors.in, ...input.sectors.maybe])], { hint: (input.sectors.confidence?.explanations || []).join(" ") })];
    if (input.sectors.maybe.length) issues.push(issue(`${input.id}:maybe`, "Possible sectors are not selected. Explicitly decide whether to include or exclude each one.", [...input.sectors.maybe]));
    for (const p of properties) {
      if (["inferred", "calculated"].includes(p.basis) || p.disposition === "unresolved" || ["low", "conflict"].includes(p.confidence?.final) || p.requires_confirmation) issues.push(issue(`${input.id}:property:${p.property}`, `${p.property}: ${p.disposition}, ${p.basis}, confidence ${p.confidence?.final || "unassessed"}.`, [], { property: p.property, fieldNames: Object.keys(projectProperty(p)), hint: p.rationale || p.unavailable_reason || "Inspect the source alternatives." }));
      if (p.property === "dimensions" && p.status === "recorded" && !Object.keys(projectProperty(p)).length) issues.push(issue(`${input.id}:dimensions`, "Dimensions retained without mapping to x/y/z. The source lacks exact, named axes."));
    }
    return { id: input.id, instance: input.order, label: subjects.get(input.focus)?.label || input.id, regions: copy(input.sectors.in), maybeRegions: copy(input.sectors.maybe), values: mapped(properties, "lesion"), sourceObservations: properties, issues, reviewed: false };
  });
  const caseIssues = [...index(raw.issues, "Issues").values()].map(input => {
    if (!["info", "question"].includes(input.severity)) fail("Unknown issue severity.");
    const related = lesions.filter(l => {
      const original = raw.lesions.find(s => s.id === l.id);
      return (input.context || []).some(ref => [l.id, original.focus, original.hypothesis, ...(original.marks || []), ...(original.candidates || [])].includes(ref));
    });
    const regions = [...new Set((input.context || []).flatMap(ref => marks.get(ref)?.redcap || candidates.get(ref)?.sectors_in || []))].filter(code => codes.has(code));
    return issue(input.id, `${input.kind}: ${input.reason || input.explanation || input.summary || "Inspect this issue."}`, regions, { severity: input.severity, sourceRef: (input.context || []).join(", "), sourceIssue: copy(input), lesionIds: related.map(l => l.id), hint: `Raised by ${(input.raised_by || []).join(", ")}. ${(input.alternatives || []).length} alternatives retained.` });
  });
  const properties = sourceObservations(raw.specimen?.properties);
  return {
    schemaVersion: "doctor-review-combined-v1", caseId: raw.case_id, recordId: "", showcase: false,
    sourceBinding: "pinned-combined", sourceAnalysis: copy(raw), sourceReport: report, sourceDrawing: drawing,
    reportText, lesions, caseIssues, exportScope: "surgery", surgery: { values: mapped(properties, "surgery"), sourceObservations: properties, reviewed: false, valueEvidence: {} },
    centralDecisions: [], reviewLog: [],
  };
}
