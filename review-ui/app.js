import { LESION_FIELDS, validateReview, buildLesionCsv } from "./redcap.js";
import { adaptAnalysis } from "./analysis.js";
import { createDoctorLesion, validSavedReview, validateEvidence } from "./review-state.js";
import { stageRegion, pendingRegionCodes, documentRegions } from "./region-edits.js";
import { sectorLabel, sectorName } from "./map-labels.js";

let storageKey;
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);
let sectors, prediction, state, activeId, regionCode, caseConfig;
const regionUndo = [];
let pendingDecision = null;
let cropBounds = null;
let cropStart = null;
const imageSizes = {};
const axialLevels = ["base", "mid", "apex"];
const mapGroups = [
  ...axialLevels.map(level => ({ id: level, label: level[0].toUpperCase() + level.slice(1) })),
  { id: "sv", label: "Seminal vesicles" }, { id: "urethra", label: "Urethra (atlas)" },
];

function groupSectors(id) {
  return sectors.filter(sector => id === "sv" ? sector.code.startsWith("sv_")
    : id === "urethra" ? sector.code === id
    : sector.code.includes(`_${id}_`) && !sector.code.startsWith("sv_"));
}

function sectionSummary(lesion) {
  return mapGroups.map(group => {
    const count = groupSectors(group.id).filter(sector => lesion.regions.includes(sector.code)).length;
    return count ? `${group.label} ${count}` : "";
  }).filter(Boolean).join(" · ") || "No regions";
}

function notify(message) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

function active() {
  return state.lesions.find((lesion) => lesion.id === activeId);
}

function evidenceContext() {
  return { reportText: prediction.reportText, sources: caseConfig.sources, imageSizes };
}

function save() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(state));
    $("save-status").textContent = "Saved locally · showcase only";
    notify("");
  } catch {
    $("save-status").textContent = "Not saved";
    notify("Local saving failed. Download the review JSON before leaving this page.");
  }
}

function fillMap(svg, subset, { interactive = true, labels = true } = {}) {
  const visible = state.lesions.filter((lesion) => !lesion.excluded);
  svg.replaceChildren();
  for (const sector of subset) {
    const members = visible.filter((lesion) => lesion.regions.includes(sector.code));
    const assigned = members.some((lesion) => lesion.id === activeId);
    const uncertain = !active().excluded && active().issues.some((issue) =>
      (!issue.resolved || issue.disposition === "reviewed_unknown") && issue.regionCodes.includes(sector.code));
    const polygon = document.createElementNS(NS, "polygon");
    polygon.setAttribute("points", sector.points.map((point) => point.join(",")).join(" "));
    polygon.setAttribute("class", [
      assigned ? "assigned" : members.length ? "other-lesion" : "",
      uncertain ? "uncertain" : "", sector.code === regionCode ? "focused" : "",
    ].join(" "));
    if (interactive) {
      polygon.setAttribute("tabindex", "0");
      polygon.setAttribute("role", "button");
      polygon.setAttribute("aria-pressed", String(assigned));
      polygon.setAttribute("aria-disabled", String(Boolean(active().excluded)));
      polygon.setAttribute("aria-label", `${sectorName(sector)} (${sector.code}). ${assigned ? "Assigned to current lesion. Click to remove." : "Not assigned to current lesion. Click to add."}`);
      polygon.dataset.region = sector.code;
    } else {
      polygon.dataset.overviewRegion = sector.code;
      polygon.setAttribute("pointer-events", "none");
      polygon.setAttribute("aria-hidden", "true");
    }
    const title = document.createElementNS(NS, "title");
    title.textContent = `${sectorName(sector)} (${sector.code})`;
    polygon.append(title);
    svg.append(polygon);
    const position = labels ? sectorLabel(sector) : null;
    if (position) {
      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", position.x);
      label.setAttribute("y", position.y);
      label.classList.add("sector-label");
      label.classList.toggle("selected", assigned);
      label.setAttribute("aria-hidden", "true");
      label.textContent = position.text;
      svg.append(label);
    }
  }
}

function inspectedLevel() {
  return axialLevels.find(level => groupSectors(level).some(sector => sector.code === regionCode));
}

function atlasImage() {
  const image = document.createElementNS(NS, "image");
  image.setAttribute("href", "assets/pirads_v2.1.png");
  image.setAttribute("width", "513");
  image.setAttribute("height", "631");
  image.setAttribute("pointer-events", "none");
  return image;
}

function renderMap() {
  const focused = document.activeElement?.matches(".region-map polygon")
    ? { code: document.activeElement.dataset.region, view: document.activeElement.closest("svg").dataset.view } : null;
  $("linked-views").replaceChildren();
  for (const group of mapGroups) {
    const subset = groupSectors(group.id);
    const points = subset.flatMap((sector) => sector.points);
    const left = Math.max(0, Math.min(...points.map(([x]) => x)) - 9);
    const top = Math.max(0, Math.min(...points.map(([, y]) => y)) - 9);
    const right = Math.min(513, Math.max(...points.map(([x]) => x)) + 9);
    const bottom = Math.min(631, Math.max(...points.map(([, y]) => y)) + 9);
    const card = document.createElement("section");
    card.id = `axial-${group.id}`;
    card.dataset.level = group.id;
    const selected = active().excluded ? 0 : subset.filter(sector => active().regions.includes(sector.code)).length;
    card.className = `linked-view ${selected ? "has-selection" : ""} ${inspectedLevel() === group.id ? "current" : ""} ${group.id === "sv" || group.id === "urethra" ? "compact" : ""}`;
    const heading = document.createElement("h3");
    heading.textContent = `${group.label} · ${selected} selected`;
    const svg = document.createElementNS(NS, "svg");
    svg.classList.add("region-map");
    svg.dataset.view = group.id;
    svg.setAttribute("viewBox", `${left} ${top} ${right - left} ${bottom - top}`);
    svg.setAttribute("aria-label", `${group.label} regions`);
    fillMap(svg, subset);
    card.append(heading);
    if (axialLevels.includes(group.id) || group.id === "sv") {
      const orientation = document.createElement("div");
      orientation.className = "map-orientation";
      orientation.innerHTML = "<span>Patient R</span><span>Patient L</span>";
      card.append(orientation);
    }
    card.append(svg);
    if (group.id === "urethra") {
      const naming = document.createElement("p");
      naming.className = "muted terminology-warning";
      naming.textContent = "Atlas: Urethra. Mapped source title: External urethral sphincter. Naming needs clinical confirmation.";
      card.append(naming);
    }
    $("linked-views").append(card);
  }
  fillMap($("atlas-overview"), sectors, { interactive: false, labels: false });
  $("atlas-overview").prepend(atlasImage());
  if (focused) document.querySelector(`svg[data-view="${focused.view}"] [data-region="${CSS.escape(focused.code)}"]`)?.focus();
  $("selected-regions").innerHTML = `<strong>${escape(active().label)} — ${active().regions.length} regions</strong>` +
    mapGroups.map(group => {
      const selected = groupSectors(group.id).filter(sector => active().regions.includes(sector.code));
      return selected.length ? `<div><span>${escape(group.label)}</span>${selected.map(sector =>
        `<button data-inspect-region="${escape(sector.code)}" title="${escape(sectorName(sector))}">${escape(sector.code)}</button>`).join("")}</div>` : "";
    }).join("") + (active().regions.length ? "" : '<p class="muted">No assigned regions. Click a sector below to add one.</p>');
  const pending = pendingRegionCodes(active()).length;
  $("region-edit-status").textContent = pending
    ? `${pending} region edit${pending === 1 ? " needs" : "s need"} evidence`
    : "No undocumented region edits";
  $("document-regions").disabled = active().excluded || !pending;
  $("undo-region").disabled = active().excluded || !regionUndo.some(item => item.lesionId === activeId);
}

function renderRegion() {
  const sector = sectors.find((item) => item.code === regionCode);
  const members = state.lesions.filter((lesion) => !lesion.excluded && lesion.regions.includes(regionCode));
  $("region-detail").innerHTML = `<span class="eyebrow">SELECTED REGION</span>
    <h3>${escape(sectorName(sector))}</h3><code>${escape(sector.column)}</code>
    <label class="assignment"><input id="assign-region" type="checkbox" ${active().regions.includes(regionCode) ? "checked" : ""} ${active().excluded ? "disabled" : ""}>
    Include this region in ${escape(active().label)} (instance ${escape(active().instance)})</label>
    <p><strong>Associated records:</strong> ${members.length ? members.map((member) => escape(member.label)).join(", ") : "None — not a confirmed negative finding."}</p>
    <div class="association-links">${members.map((member) => `<button data-lesion="${escape(member.id)}">${escape(member.label)}</button>`).join("")}</div>
    <p>Shared regions keep separate lesion associations; values are not merged.</p>`;
}

function renderObservations() {
  const observations = active().sourceObservations;
  const sourceGroups = [
    ["Explicit / normalized source findings", observations.filter(item => item.status === "recorded" && ["explicit", "normalized"].includes(item.basis))],
    ["Inferred / calculated suggestions", observations.filter(item => item.status === "recorded" && !["explicit", "normalized"].includes(item.basis))],
    ["Unavailable findings", observations.filter(item => item.status !== "recorded")],
  ];
  $("analysis-observations").innerHTML = '<p class="muted">These findings belong to the synthetic example report, not the displayed scans. Original observations remain unchanged.</p>' +
    sourceGroups.filter(([, items]) => items.length).map(([heading, items]) => `<h3>${heading}</h3>` + items.map((observation) => `<article>
      <p><strong>${escape(observation.property)}</strong> · ${escape(observation.status)} · ${escape(observation.basis)}</p>
      <p>${escape(observation.value?.original_wording || observation.value?.original_code || observation.unavailable_reason || JSON.stringify(observation.value ?? null))}</p>
      ${(observation.evidence || []).map((evidence) => `<blockquote>${escape(evidence.quotation)}</blockquote>`).join("")}
      <p class="muted">Reading: ${escape(observation.certainty?.extraction || "unassessed")}; interpretation: ${escape(observation.certainty?.interpretation || "unassessed")}</p>
    </article>`).join("")).join("");
  const changes = [
    ...(active().creationEvidence ? [["Lesion added by doctor", active().creationEvidence]] : []),
    ...Object.entries(active().valueEvidence || {}),
    ...Object.entries(active().regionEvidence || {}),
  ];
  const evidenceArticle = ([name, evidence]) => `<article>
    <p><strong>${escape(name)}</strong> · ${escape(evidence.basis)}</p>
    <p>${escape(evidence.reason)}</p>
    ${evidence.kind === "text" ? `<blockquote>${escape(evidence.quotation)}</blockquote>` :
      evidence.kind === "image_crop" ? `<p>${escape(evidence.source)} scan crop [${evidence.bounds.join(", ")}] · SHA-256 <code>${escape(evidence.sha256)}</code></p>
      <svg class="evidence-crop" viewBox="${evidence.bounds.join(" ")}" role="img" aria-label="Supporting ${escape(evidence.source)} scan crop"><image href="${escape($(`source-${evidence.source}`).querySelector("img").src)}" width="${imageSizes[evidence.source].width}" height="${imageSizes[evidence.source].height}"></image></svg>` :
      "<p>Finding absent / not supplied; no positive finding is inferred.</p>"}
  </article>`;
  $("doctor-observations").innerHTML = ["explicit", "inferred", "absent"].map((basis) => {
    const entries = changes.filter(([, evidence]) => evidence.basis === basis);
    return entries.length ? `<h3>${basis === "inferred" ? "Doctor inferences — not explicit findings" : basis === "absent" ? "Absent / not supplied" : "Explicit findings"}</h3>` + entries.map(evidenceArticle).join("") : "";
  }).join("") || '<p class="muted">No doctor changes yet. Original proposals are preserved in the review record.</p>';
}

function renderFields() {
  $("active-lesion-name").textContent = `${active().label} · repeat instance ${active().instance}`;
  const original = prediction.lesions.find(lesion => lesion.id === activeId);
  const supplied = LESION_FIELDS.filter(field => original?.values[field.name] !== undefined && original.values[field.name] !== "").length;
  $("prefill-summary").textContent = active().doctorAdded
    ? "Doctor-added lesion: no analysis values to prefill."
    : `${supplied} of ${LESION_FIELDS.length} properties prefilled from analysis. Review them; edit only where correction is needed.`;
  $("lesion-fields").innerHTML = LESION_FIELDS.map((field) => {
    const value = active().values[field.name] ?? "";
    const sourceValue = original?.values[field.name];
    const provenance = active().valueEvidence?.[field.name] || (sourceValue !== undefined && value !== sourceValue)
      ? "Doctor-corrected"
      : sourceValue !== undefined && sourceValue !== "" ? "From analysis" : "Not supplied by analysis";
    const input = field.choices
      ? `<select data-field="${escape(field.name)}" ${active().excluded ? "disabled" : ""}><option value="">Not supplied — choose if known</option>${field.choices.map(([code, label]) =>
        `<option value="${escape(code)}" ${String(code) === value ? "selected" : ""}>${escape(label)}</option>`).join("")}</select>`
      : `<input data-field="${escape(field.name)}" ${active().excluded ? "disabled" : ""} type="number" step="any" min="${field.min ?? 0}" max="${field.max ?? 100}" value="${escape(value)}">`;
    return `<label class="${field.choices ? "wide" : ""}">${escape(field.label)}${field.required ? " *" : ""}${input}<small data-field-origin="${escape(field.name)}">${provenance}</small></label>`;
  }).join("");
}

function renderIssues() {
  $("issues").innerHTML = active().issues.map((issue) => `<article class="issue ${issue.resolved ? "resolved" : ""}">
    <p><strong>${issue.resolved ? issue.disposition === "reviewed_unknown" ? "Reviewed — still unknown" : "Resolved" : "Needs review"}</strong> · ${escape(issue.message)}</p>
    ${issue.reopenedReason ? `<p>${escape(issue.reopenedReason)}</p>` : ""}
    <p class="source-ref">Source: ${escape(issue.sourceRef)}<br>Hint: ${escape(issue.hint)}</p>
    <label>Decision / reason<textarea data-resolution="${escape(issue.id)}" ${active().excluded ? "disabled" : ""} placeholder="Explain the correction or why uncertainty is retained.">${escape(issue.resolution)}</textarea></label>
    <label>Review outcome<select data-disposition="${escape(issue.id)}" ${active().excluded || !issue.resolution.trim() ? "disabled" : ""}>
      <option value="unresolved" ${!issue.resolved ? "selected" : ""}>Needs review</option>
      <option value="resolved" ${issue.resolved && issue.disposition !== "reviewed_unknown" ? "selected" : ""}>Reviewed and addressed</option>
      <option value="reviewed_unknown" ${issue.resolved && issue.disposition === "reviewed_unknown" ? "selected" : ""}>Reviewed — genuinely unknown</option>
    </select></label>
  </article>`).join("") || '<p class="muted">No supplied uncertainty flags for this record.</p>';
  const issues = state.lesions.filter((lesion) => !lesion.excluded).flatMap((lesion) => lesion.issues);
  $("issue-count").textContent = `${issues.filter((issue) => !issue.resolved).length} open · ${issues.filter((issue) => issue.resolved && issue.disposition === "reviewed_unknown").length} unknown`;
  $("confirm-lesion").checked = active().reviewed;
  $("confirm-lesion").disabled = active().excluded || pendingRegionCodes(active()).length > 0 ||
    active().issues.some((issue) => !issue.resolved || !issue.resolution.trim());
}

function renderReadiness() {
  const errors = validateReview(state, sectors);
  $("export-csv").disabled = errors.length > 0;
  $("export-summary").textContent = errors.length
    ? `${errors.length} item${errors.length === 1 ? "" : "s"} to address before export. Review every included lesion and issue; unknown is allowed only where REDCap permits it.`
    : `Ready to download ${state.lesions.filter((lesion) => !lesion.excluded).length} first-import lesion rows. Nothing will be sent to REDCap.`;
  $("export-errors").innerHTML = errors.map((error) => `<li>${escape(error)}</li>`).join("");
  $("csv-preview").textContent = errors.length ? "Complete review to enable export." : buildLesionCsv(state, sectors);
}

function render() {
  $("record-id").value = state.recordId;
  $("lesion-list").innerHTML = state.lesions.map((lesion) => `<button class="lesion-button ${lesion.id === activeId ? "active" : ""} ${lesion.excluded ? "excluded" : ""}" data-lesion="${escape(lesion.id)}" aria-pressed="${lesion.id === activeId}">
    ${lesion.id === activeId ? "● " : ""}${escape(lesion.label)}<small>Instance ${lesion.instance} · ${lesion.regions.length} regions · ${lesion.excluded ? "excluded" : lesion.reviewed ? "reviewed" : "unreviewed"}</small><small>${escape(sectionSummary(lesion))}</small></button>`).join("");
  $("add-lesion").disabled = false;
  $("exclude-lesion").disabled = false;
  $("exclude-lesion").textContent = active().excluded ? "Restore lesion" : "Exclude lesion";
  $("lesion-status").textContent = active().excluded
    ? `Excluded from CSV: ${active().exclusionReason}. Original findings are preserved. Restore to edit and review again.`
    : `Editing ${active().label} · ${sectionSummary(active())}. Other lesions are unchanged.`;
  renderMap(); renderRegion(); renderFields(); renderObservations(); renderIssues(); renderReadiness();
}

function audit(action, details) {
  state.reviewLog.push({ at: new Date().toISOString(), actor: "local showcase user (not authenticated)", lesionId: activeId, action, details });
}

function edit(update, action, details, dataChange = true) {
  update(active());
  if (dataChange) for (const issue of active().issues) {
    if (issue.resolved) {
      issue.resolved = false;
      delete issue.disposition;
      issue.reopenedReason = "Reopened after a value or region edit. Recheck this decision; the earlier reason is retained.";
    }
  }
  active().reviewed = false;
  audit(action, details);
  save();
  render();
}

function inspectRegion(code) {
  regionCode = code;
  render();
}

function assignRegion(code, assigned = !active().regions.includes(code)) {
  if (active().excluded) { notify("Restore this lesion before editing regions."); return; }
  regionCode = code;
  if (active().regions.includes(code) === assigned) { render(); return; }
  regionUndo.push({ lesionId: activeId, code, assigned: active().regions.includes(code) });
  edit(lesion => stageRegion(lesion, code, assigned), "region-staged", { code, assigned });
}

$("undo-region").addEventListener("click", () => {
  const index = regionUndo.findLastIndex(item => item.lesionId === activeId);
  if (index < 0) return;
  const previous = regionUndo.splice(index, 1)[0];
  regionCode = previous.code;
  edit(lesion => stageRegion(lesion, previous.code, previous.assigned), "region-undo", previous);
});
$("document-regions").addEventListener("click", () => {
  const edits = structuredClone(active().pendingRegionEdits);
  requestDecision({
    title: `Document region edits for ${active().label}`,
    description: Object.entries(edits).map(([code, change]) =>
      `${change.to ? "Add" : "Remove"}: ${sectorName(sectors.find(sector => sector.code === code))} (${code})`).join("\n") +
      "\nCite evidence that supports this group of edits. Use separate groups if they need different evidence. Review confirmation is still required.",
    apply(evidence) {
      edit(lesion => documentRegions(lesion, evidence), "region-edits-documented", { edits, evidence }, false);
      for (let index = regionUndo.length - 1; index >= 0; index--) {
        if (regionUndo[index].lesionId === activeId) regionUndo.splice(index, 1);
      }
    },
  });
});

function switchSource(role) {
  for (const tab of document.querySelectorAll("[data-source-tab]")) {
    const selected = tab.dataset.sourceTab === role;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $(`view-${tab.dataset.sourceTab}`).hidden = !selected;
  }
  $("source-zoom-control").hidden = role === "text";
}

document.querySelectorAll("[data-source-tab]").forEach(tab => {
  tab.addEventListener("click", () => switchSource(tab.dataset.sourceTab));
  tab.addEventListener("keydown", event => {
    const tabs = [...document.querySelectorAll("[data-source-tab]")];
    const index = tabs.indexOf(tab);
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
      : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    switchSource(tabs[next].dataset.sourceTab);
    tabs[next].focus();
  });
});
$("source-zoom").addEventListener("change", event => {
  for (const source of document.querySelectorAll(".scan-source")) source.style.width = `${event.target.value}%`;
});

function updateEvidenceSource() {
  const source = $("change-source").value;
  const image = source.endsWith("-image");
  $("change-quote-label").hidden = source !== "report-text";
  $("change-crop").hidden = !image;
  $("change-basis").disabled = source === "absent";
  cropBounds = null;
  cropStart = null;
  $("crop-box").hidden = true;
  $("crop-coordinates").textContent = "No crop selected.";
  if (image) $("change-scan").src = $(`source-${source.split("-")[0]}`).querySelector("img").src;
}

function requestDecision(options) {
  pendingDecision = options;
  $("change-form").reset();
  $("change-title").textContent = options.title;
  $("change-description").textContent = options.description;
  $("change-error").hidden = true;
  $("change-evidence").hidden = options.evidence === false;
  const sources = [["report-text", "Illustrative report text (not the displayed scan)"], ["report-image", "Report scan crop"]];
  if (!options.reportOnly) sources.push(["drawing-image", "Drawing scan crop"]);
  if (options.allowAbsent) sources.push(["absent", "Absent / not reported — no positive finding"]);
  $("change-source").replaceChildren(...sources.map(([value, label]) => new Option(label, value)));
  updateEvidenceSource();
  render();
  $("change-dialog").showModal();
}

function decisionEvidence() {
  const reason = $("change-reason").value.trim();
  if (!reason) throw new Error("Record a decision / reason before confirming.");
  if (pendingDecision.evidence === false) return { reason };
  const source = $("change-source").value;
  const basis = $("change-basis").value;
  let evidence;
  if (source === "absent") evidence = { kind: "absent", basis: "absent", reason };
  else if (source === "report-text") {
    const quotation = $("change-quote").value;
    const offset = prediction.reportText.indexOf(quotation);
    if (!quotation.trim() || offset < 0) throw new Error("Copy an exact, nonempty quotation from the illustrative report text.");
    const start = [...prediction.reportText.slice(0, offset)].length;
    evidence = { kind: "text", source: "report", quotation, start, end: start + [...quotation].length, basis, reason };
  } else {
    const role = source.split("-")[0];
    evidence = { kind: "image_crop", source: role, sha256: caseConfig.sources[role].sha256, bounds: cropBounds, basis, reason };
  }
  const errors = validateEvidence(evidence, evidenceContext(), pendingDecision);
  if (errors.length) throw new Error(errors.join(" "));
  return evidence;
}

$("change-source").addEventListener("change", updateEvidenceSource);
$("cancel-change").addEventListener("click", () => $("change-dialog").close());
$("change-dialog").addEventListener("close", () => {
  if ($("change-dialog").open) return;
  pendingDecision = null;
  if (state) render();
});
$("change-form").addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    const evidence = decisionEvidence();
    pendingDecision.apply(evidence);
    $("change-dialog").close();
  } catch (error) {
    $("change-error").textContent = error.message;
    $("change-error").hidden = false;
  }
});

function cropPoint(event) {
  const rect = $("change-scan").getBoundingClientRect();
  const size = imageSizes[$("change-source").value.split("-")[0]];
  return [
    Math.round(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * size.width),
    Math.round(Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) * size.height),
  ];
}

$("crop-frame").addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  event.preventDefault();
  cropStart = cropPoint(event);
  cropBounds = null;
  $("crop-box").hidden = true;
  $("crop-frame").setPointerCapture(event.pointerId);
});
$("crop-frame").addEventListener("pointermove", (event) => {
  if (!cropStart) return;
  const end = cropPoint(event);
  cropBounds = [
    Math.min(cropStart[0], end[0]), Math.min(cropStart[1], end[1]),
    Math.abs(end[0] - cropStart[0]), Math.abs(end[1] - cropStart[1]),
  ];
  const size = imageSizes[$("change-source").value.split("-")[0]];
  const box = $("crop-box");
  box.hidden = false;
  box.style.left = `${cropBounds[0] / size.width * 100}%`;
  box.style.top = `${cropBounds[1] / size.height * 100}%`;
  box.style.width = `${cropBounds[2] / size.width * 100}%`;
  box.style.height = `${cropBounds[3] / size.height * 100}%`;
  $("crop-coordinates").textContent = `Original pixels [x, y, width, height]: ${cropBounds.join(", ")}`;
});
$("crop-frame").addEventListener("pointerup", () => { cropStart = null; });
$("crop-frame").addEventListener("pointercancel", () => {
  cropStart = null;
  cropBounds = null;
  $("crop-box").hidden = true;
  $("crop-coordinates").textContent = "Selection cancelled. Select a crop again.";
});

$("add-lesion").addEventListener("click", () => requestDecision({
  title: "Add a doctor-identified lesion?",
  description: "Cite the report finding. A drawing mark alone cannot create a lesion. No regions or clinical values will be filled automatically.",
  reportOnly: true,
  apply(evidence) {
    const lesion = createDoctorLesion(state, evidence, evidenceContext());
    state.lesions.push(lesion);
    activeId = lesion.id;
    audit("lesion-added", { evidence });
    save();
    render();
  },
}));
$("exclude-lesion").addEventListener("click", () => {
  const excluded = !active().excluded;
  requestDecision({
    title: excluded ? "Exclude this lesion from the first-import CSV?" : "Restore this lesion for review?",
    description: `${active().label}. ${excluded ? "The original proposal, values and evidence stay in the review record. This will not delete anything in REDCap." : "Its previous values return unchanged and require review again."}`,
    evidence: false,
    apply({ reason }) {
      edit((lesion) => {
        lesion.excluded = excluded;
        lesion.exclusionReason = reason;
      }, excluded ? "lesion-excluded" : "lesion-restored", { reason }, !excluded);
    },
  });
});

function download(contents, filename, type) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const link = document.createElement("a");
  link.href = url; link.download = filename; link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.addEventListener("click", (event) => {
  if (!state) return;
  const inspect = event.target.closest("[data-inspect-region]");
  if (inspect) { inspectRegion(inspect.dataset.inspectRegion); return; }
  const lesion = event.target.closest("[data-lesion]");
  const region = event.target.closest("[data-region]");
  if (lesion) {
    activeId = lesion.dataset.lesion;
    regionCode = active().regions[0] || sectors[0].code;
    render();
  }
  if (region) assignRegion(region.dataset.region);
});
document.addEventListener("keydown", (event) => {
  if (!state || !["Enter", " "].includes(event.key)) return;
  if (event.target.matches(".region-map polygon")) {
    event.preventDefault(); assignRegion(event.target.dataset.region);
  }
});
document.addEventListener("change", (event) => {
  if (!state) return;
  const target = event.target;
  if (target.id === "record-id") {
    const value = target.value;
    if (value !== state.recordId && confirm(`Change target test record ID from "${state.recordId}" to "${value}"?`)) {
      state.recordId = value; audit("record-id", { value }); save();
    }
    $("record-id").value = state.recordId;
    renderReadiness();
  }
  if (target.id === "assign-region") {
    assignRegion(regionCode, target.checked);
  }
  if (target.dataset.field) {
    const name = target.dataset.field;
    const field = LESION_FIELDS.find((item) => item.name === name);
    const value = target.value;
    const previous = active().values[name] ?? "";
    if (previous === value) return;
    if (!target.checkValidity()) { render(); notify(`${field.label}: enter a value within the documented range.`); return; }
    const label = (raw) => field.choices?.find(([code]) => code === raw)?.[1] || raw || "Not supplied";
    requestDecision({
      title: `Change ${field.label}?`,
      description: `${active().label}\nPrevious: ${label(previous)}\nProposed: ${label(value)}\nPrevious review confirmation is invalidated; addressed issues reopen.`,
      allowAbsent: value === "" || (["extracaps_ext", "perineural_inv_sur"].includes(name) && value === "4"),
      apply(evidence) {
        edit((lesion) => {
          lesion.values[name] = value;
          (lesion.valueEvidence ??= {})[name] = evidence;
        }, "field-edit", { field: name, from: previous, to: value, evidence });
      },
    });
  }
  if (target.dataset.resolution) {
    const id = target.dataset.resolution;
    const value = target.value;
    if (!confirm(`Save this issue decision / reason?\n${value}`)) { render(); return; }
    edit((lesion) => {
      const issue = lesion.issues.find((item) => item.id === id);
      issue.resolution = value;
      issue.resolved = false;
      delete issue.disposition;
    }, "issue-reason", { issue: id, reason: value }, false);
  }
  if (target.dataset.disposition) {
    const id = target.dataset.disposition;
    const disposition = target.value;
    if (!confirm(`Change this issue's outcome to "${target.selectedOptions[0].textContent}"?\nUnknown values are never filled automatically. Sector checkboxes cannot represent unknown.`)) { render(); return; }
    edit((lesion) => {
      const issue = lesion.issues.find((item) => item.id === id);
      issue.resolved = disposition !== "unresolved";
      if (issue.resolved) { issue.disposition = disposition; delete issue.reopenedReason; }
      else delete issue.disposition;
    }, "issue-resolution", { issue: id, disposition }, false);
  }
  if (target.id === "confirm-lesion") { active().reviewed = target.checked; audit("review-confirmation", { reviewed: target.checked }); save(); render(); }
});
$("download-json").addEventListener("click", () => download(
  JSON.stringify({ ...state, sourceConfig: caseConfig, originalPrediction: prediction, exportPurpose: "first_import_lesion_draft", liveRedcapImportVerified: false }, null, 2),
  `${state.caseId}-review.json`, "application/json",
));
$("export-csv").addEventListener("click", () => {
  try {
    download(buildLesionCsv(state, sectors), `${state.caseId}-lesions.csv`, "text/csv;charset=utf-8");
  } catch (error) { notify(error.message); }
});
$("reset-demo").addEventListener("click", () => {
  if (!confirm("Discard locally saved showcase edits and reload this reference case?")) return;
  if (!storageKey) { location.reload(); return; }
  try { localStorage.removeItem(storageKey); location.reload(); }
  catch { notify("Cannot clear local storage. Your saved review has not been reset."); }
});

async function loadLocal(url) {
  const resolved = new URL(url, location.href);
  if (resolved.origin !== location.origin || !resolved.pathname.startsWith("/.local-data/")) throw new Error("Showcase references must stay in the local data folder.");
  const response = await fetch(resolved);
  if (!response.ok) throw new Error("Local showcase file is missing. Run prepare_showcase.py as described in README.");
  return response;
}

async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function displayScan(role) {
  const source = caseConfig.sources[role];
  const response = await loadLocal(source.url);
  const bytes = await response.arrayBuffer();
  if (await sha256(bytes) !== source.sha256) throw new Error("A source scan changed; prepare the showcase again before reviewing.");
  const image = document.createElement("img");
  const loaded = new Promise((resolve, reject) => {
    image.addEventListener("load", resolve, { once: true });
    image.addEventListener("error", () => reject(new Error(`The verified ${role} scan could not be loaded.`)), { once: true });
  });
  image.src = URL.createObjectURL(new Blob([bytes], { type: "image/jpeg" }));
  image.alt = `Provided artificial Rakathon ${role} scan`;
  const link = document.createElement("a");
  link.href = image.src; link.target = "_blank"; link.rel = "noopener";
  link.append(document.createTextNode("Open full-size scan"), image);
  $(`source-${role}`).replaceChildren(link);
  await loaded;
  imageSizes[role] = { width: image.naturalWidth, height: image.naturalHeight };
}

async function start() {
  caseConfig = await (await loadLocal(".local-data/case.json")).json();
  if (caseConfig.mode !== "showcase" || caseConfig.sourceBinding !== "showcase-unlinked") throw new Error("Only the explicitly unlinked showcase configuration is supported.");
  const responses = await Promise.all([fetch("assets/sectors.json"), loadLocal(caseConfig.analysisUrl), loadLocal(caseConfig.reportTextUrl)]);
  if (responses.some((response) => !response.ok)) throw new Error("Sector or analysis assets could not be loaded.");
  const [map, raw, reportText] = await Promise.all([responses[0].json(), responses[1].json(), responses[2].text()]);
  sectors = map;
  if (sectors.length !== 41 || new Set(sectors.map((sector) => sector.code)).size !== 41) throw new Error("The region map must have exactly 41 distinct REDCap sectors.");
  prediction = await adaptAnalysis(raw, sectors, {
    caseId: caseConfig.caseId, reportText, showcase: true, demoAssignments: caseConfig.demoAssignments,
  });
  await Promise.all(["drawing", "report"].map(displayScan));
  const fingerprint = await sha256(new TextEncoder().encode(JSON.stringify({ raw, caseConfig, adapter: prediction.schemaVersion })));
  storageKey = `prostapaper.review.v2.${caseConfig.caseId}.${fingerprint}`;
  const saved = localStorage.getItem(storageKey);
  state = saved ? JSON.parse(saved) : { ...structuredClone(prediction), reviewLog: [] };
  if (!validSavedReview(state, prediction, sectors, evidenceContext())) { state = undefined; throw new Error("Saved review does not match this demo version. Download or keep the saved data before using Reset showcase to discard it explicitly."); }
  activeId = state.lesions[0].id;
  regionCode = state.lesions[0].regions[0] || sectors[0].code;
  $("case-code").textContent = `Source pair: ${caseConfig.sourceCaseId}`;
  const identity = caseConfig.sourceIdentity;
  if (identity) {
    if (identity.sourceCaseId !== caseConfig.sourceCaseId || typeof identity.originalId !== "string" ||
        !identity.originalId.trim() || identity.basis !== "explicit" || !Array.isArray(identity.evidence) ||
        identity.evidence.length !== 2 ||
        !["report", "drawing"].every(role => identity.evidence.some(anchor =>
          anchor.source === role && anchor.quotation === identity.originalId))) {
      throw new Error("Original identity mapping does not match this source pair.");
    }
    $("case-title").textContent = identity.originalId;
    $("identity-status").textContent = "Original source ID restored from the local dictionary; report and drawing agree. The illustrative analysis is still unrelated.";
  } else {
    $("identity-status").textContent = "Original source ID unavailable. Prepare with the local ID dictionary; the random pair ID is not a patient ID.";
  }
  $("record-id").value = state.recordId;
  $("record-id").disabled = false;
  $("download-json").disabled = false;
  $("analysis-report").textContent = prediction.reportText;
  $("analysis-json-source").href = caseConfig.analysisUrl;
  $("analysis-json-source").hidden = false;
  $("save-status").textContent = saved ? "Restored local showcase review" : "Illustrative analysis · no saved edits";
  render();
}

start().catch((error) => {
  $("save-status").textContent = "Demo could not load";
  $("export-csv").disabled = true;
  $("download-json").disabled = true;
  notify(`${error.message} No export is available.`);
});
