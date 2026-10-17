const fieldProperties = { hist_type_sur: "histology_type", extracaps_ext: "extraprostatic_extension", perineural_inv_sur: "perineural_invasion" };

function override(lesion, field) {
  const raw = lesion.values[field], wording = lesion.valueEvidence[field]?.quotation || lesion.valueEvidence[field]?.reason || "Doctor review";
  if ((raw === "" && fieldProperties[field]) || (["extracaps_ext", "perineural_inv_sur"].includes(field) && raw === "4")) return { property: fieldProperties[field], status: "not reported", value: null };
  if (field === "hist_type_sur") return { property: "histology_type", status: "recorded", value: { type: "coded", code: raw, original_wording: wording } };
  if (fieldProperties[field]) return { property: fieldProperties[field], status: "recorded", value: { type: "presence", value: { "1": "present", "2": "indeterminate", "3": "absent" }[raw], original_wording: wording } };
  if (field.startsWith("gleason_")) {
    const value = { type: "gleason_patterns", original_wording: wording };
    for (const [part, suffix] of [["primary", "prim"], ["secondary", "sec"], ["tertiary", "tert"]]) {
      if (lesion.values[`gleason_${suffix}_grade`]) value[part] = { pattern: +lesion.values[`gleason_${suffix}_grade`], ...(lesion.values[`gleason_${suffix}_perc`] ? { percent: +lesion.values[`gleason_${suffix}_perc`] } : {}) };
    }
    if (!value.primary || !value.secondary) throw new Error("Set both primary and secondary Gleason patterns before downloading central decisions.");
    return { property: "gleason_patterns", status: "recorded", value };
  }
  const measurements = ["x", "y", "z"].filter(axis => lesion.values[`lesion_${axis}_mm`] !== undefined && lesion.values[`lesion_${axis}_mm`] !== "").map(axis => ({ axis, unit: "mm", value: +lesion.values[`lesion_${axis}_mm`], approximate: false }));
  return { property: "dimensions", status: measurements.length ? "recorded" : "not reported", value: measurements.length ? { type: "dimensions", measurements, original_wording: wording } : null };
}

export function buildCentralDecisions(state, { reviewer, timestamp = new Date().toISOString() } = {}) {
  if (state.sourceBinding !== "pinned-combined") throw new Error("Central decisions require a pinned combined assessment.");
  if (!reviewer?.trim()) throw new Error("Enter a reviewer name before downloading decisions.");
  if (state.lesions.some(l => l.doctorAdded)) throw new Error("Doctor-added lesions are preserved in review JSON. Central does not support adding lesions through decisions-1.");
  if (state.lesions.some(l => Object.keys(l.pendingRegionEdits || {}).length)) throw new Error("Document pending sector edits first.");
  const decisions = structuredClone(state.centralDecisions || []);
  const append = (kind, target, value, reason) => decisions.push({ id: crypto.randomUUID(), kind, target, value, reviewer: reviewer.trim(), timestamp, reason });
  for (const lesion of state.lesions) {
    const original = state.sourceAnalysis.lesions.find(l => l.id === lesion.id);
    const target = { lesion: lesion.id, ...(original?.focus ? { focus: original.focus } : {}) };
    if (Object.keys(lesion.regionEvidence || {}).length) append("set_value", { ...target, property: "sectors" }, { status: "recorded", value: { type: "sectors", in: [...lesion.regions], maybe: [] } }, Object.values(lesion.regionEvidence).map(e => e.reason).join("; "));
    const emitted = new Set();
    for (const field of Object.keys(lesion.valueEvidence || {})) {
      const { property, status, value } = override(lesion, field);
      if (emitted.has(property)) continue;
      emitted.add(property);
      append("set_value", { ...target, property }, { status, value }, lesion.valueEvidence[field].reason);
    }
  }
  for (const issue of state.caseIssues || []) if (issue.resolved && issue.resolution.trim()) append("resolve_issue", { issue: issue.id }, { disposition: issue.disposition || "resolved" }, issue.resolution);
  return { schema_version: "decisions-1", decisions };
}
