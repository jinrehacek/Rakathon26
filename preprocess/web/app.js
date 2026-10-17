"use strict";

const $ = (id) => document.getElementById(id);
const ui = {
  form: $("upload-form"), files: $("files"), acknowledgment: $("artificial-data"),
  upload: $("upload-button"), refresh: $("refresh-button"), progress: $("progress"),
  error: $("error"), batches: $("batch-select"), summary: $("batch-summary"),
  release: $("release-button"), excluded: $("excluded-section"),
  excludedSummary: $("excluded-summary"), excludedList: $("excluded-list"),
  cases: $("case-list"), panel: $("case-panel"),
  pendingCount: $("pending-count"), clearSelection: $("clear-selection"),
};
let state = { busy: false, progress: "", error: null, batches: [] };
let loaded = false;
let requesting = false;
let reading = false;
let pollingFailed = false;
let batchId = null;
let caseId = null;
let pollTimer = null;
let renderedCase = "";
let zoom = "fit";
const drafts = new Map();
const pendingFiles = new Map();

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function showError(message) {
  ui.error.textContent = message || "";
  ui.error.hidden = !message;
}

function currentBatch() {
  return state.batches.find((batch) => batch.id === batchId);
}

function currentCase() {
  return currentBatch()?.cases.find((item) => item.id === caseId);
}

function isReady(item) {
  return item.decision === "pending" || item.decision === "approved";
}

function reviewLabel(item) {
  return {
    pending: "Unreviewed · ready",
    approved: "Manually reviewed · ready",
    held: "Held · excluded",
  }[item.decision];
}

function draftKey() {
  return JSON.stringify([batchId, caseId]);
}

function currentDraft() {
  const key = draftKey();
  if (!drafts.has(key)) {
    const item = currentCase();
    drafts.set(key, {
      note: item.note || "",
      checks: {
        pairing: item.checks?.pairing === true,
        redaction: item.checks?.redaction === true,
        quality: item.checks?.quality === true,
      },
    });
  }
  return drafts.get(key);
}

function locked() {
  return !loaded || state.busy || requesting || reading;
}

function updateControls() {
  const disabled = locked();
  ui.files.disabled = disabled;
  ui.acknowledgment.disabled = disabled;
  ui.pendingCount.textContent = `${pendingFiles.size} ${pendingFiles.size === 1 ? "file" : "files"} pending`;
  ui.clearSelection.disabled = disabled || !pendingFiles.size;
  ui.upload.disabled = disabled || !pendingFiles.size || !ui.acknowledgment.checked;
  ui.refresh.disabled = reading || requesting || (state.busy && !pollingFailed);
  ui.batches.disabled = disabled || !state.batches.length;
  ui.release.disabled = disabled || !currentBatch()?.cases.some(isReady);
  ui.cases.querySelectorAll("button").forEach((button) => { button.disabled = disabled; });
  ui.panel.querySelectorAll("input, textarea, select, button").forEach((control) => {
    control.disabled = disabled;
  });
  if (currentCase()) {
    const draft = currentDraft();
    const approve = $("approve-button");
    const hold = $("hold-button");
    if (approve) approve.disabled = disabled || !Object.values(draft.checks).every(Boolean);
    if (hold) hold.disabled = disabled || !draft.note.trim();
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options, credentials: "same-origin", mode: "same-origin", redirect: "error", cache: "no-store",
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`The local server returned an unreadable response (HTTP ${response.status}).`);
  }
  if (!response.ok) throw new Error(result.error || `Request failed (HTTP ${response.status}).`);
  return result;
}

function imageUrl(value) {
  if (typeof value !== "string" || !value) throw new Error("An image URL is missing.");
  const url = new URL(value, location.href);
  if (url.origin !== location.origin || !["http:", "https:"].includes(url.protocol)) {
    throw new Error("An image URL was rejected: only local, same-origin images are allowed.");
  }
  return url.href;
}

function fullSizeLink(value, label) {
  try {
    const link = element("a", label);
    link.href = imageUrl(value);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  } catch (error) {
    return element("span", error.message, "error");
  }
}

function applyZoom(image) {
  if (zoom === "fit") {
    image.style.width = "auto";
    image.style.maxWidth = "100%";
  } else {
    image.style.maxWidth = "none";
    image.style.width = `${image.naturalWidth * Number(zoom)}px`;
  }
}

function imageCard(url, label) {
  const card = element("figure");
  card.append(element("figcaption", label), fullSizeLink(url, "Open full-size image ↗"));
  const viewport = element("div", undefined, "image-viewport");
  viewport.tabIndex = 0;
  viewport.setAttribute("aria-label", `${label}, scroll to inspect zoomed image`);
  try {
    const image = element("img");
    image.alt = label;
    image.loading = "lazy";
    image.addEventListener("load", () => applyZoom(image));
    image.addEventListener("error", () => {
      viewport.replaceChildren(element("p", "Image could not be loaded. Try its full-size link or refresh.", "error"));
    });
    image.src = imageUrl(url);
    viewport.append(image);
  } catch (error) {
    viewport.append(element("p", error.message, "error"));
  }
  card.append(viewport);
  return card;
}

function renderCase() {
  const item = currentCase();
  const signature = JSON.stringify([batchId, item || null]);
  if (signature === renderedCase) return;
  renderedCase = signature;
  ui.panel.replaceChildren();
  if (!item) {
    ui.panel.append(element("p", "No paired cases in this batch. Include both reports and drawings together in the same upload, matched by printed ID. Separate batches do not combine automatically. Inspect skipped inputs and issue counts."));
    return;
  }
  ui.panel.append(
    element("h2", `Case ${item.id}`),
    element("p", `Original printed ID: ${item.originalId}`),
    element("p", `Review status: ${reviewLabel(item)}`, `decision ${item.decision}`),
  );
  const zoomLabel = element("label", "Image zoom ");
  const zoomSelect = element("select");
  zoomSelect.setAttribute("aria-label", "Image zoom");
  [["fit", "Fit width"], ["0.5", "50% (actual pixels)"], ["1", "100% (actual pixels)"], ["1.5", "150% (actual pixels)"]]
    .forEach(([value, text]) => {
      const option = element("option", text);
      option.value = value;
      zoomSelect.append(option);
    });
  zoomSelect.value = zoom;
  zoomSelect.addEventListener("change", () => {
    zoom = zoomSelect.value;
    ui.panel.querySelectorAll("img").forEach(applyZoom);
  });
  zoomLabel.append(zoomSelect);
  ui.panel.append(zoomLabel);
  for (const [key, title] of [["report", "Report"], ["drawing", "Drawing"]]) {
    const source = item.sources[key];
    const section = element("section", undefined, "source");
    section.append(element("h3", title), element("p", `Export rotation: ${source.rotation}° clockwise.`, "muted"));
    const comparison = element("div", undefined, "comparison");
    comparison.append(
      imageCard(source.originalUrl, `${title} · original`),
      imageCard(source.redactedUrl, `${title} · redacted`),
    );
    section.append(comparison);
    ui.panel.append(section);
  }
  const form = element("form", undefined, "decision-form");
  const fieldset = element("fieldset");
  fieldset.append(element("legend", "Optional manual review — all three checks required to Mark reviewed"));
  const draft = currentDraft();
  for (const [key, label] of [
    ["pairing", "Pairing correct"],
    ["redaction", "IDs covered / remaining identifiers checked"],
    ["quality", "Orientation and annotations preserved"],
  ]) {
    const wrapper = element("label", undefined, "check");
    const input = element("input");
    input.type = "checkbox";
    input.checked = draft.checks[key];
    input.addEventListener("change", () => {
      draft.checks[key] = input.checked;
      updateControls();
    });
    wrapper.append(input, element("span", label));
    fieldset.append(wrapper);
  }
  const noteLabel = element("label", "Review note (required to hold)");
  noteLabel.htmlFor = "decision-note";
  const note = element("textarea");
  note.id = "decision-note";
  note.rows = 3;
  note.value = draft.note;
  note.addEventListener("input", () => {
    draft.note = note.value;
    updateControls();
  });
  const actions = element("div", undefined, "actions");
  const approve = element("button", "Mark reviewed");
  approve.id = "approve-button";
  approve.type = "button";
  approve.addEventListener("click", () => saveDecision("approved"));
  const hold = element("button", "Hold pair");
  hold.id = "hold-button";
  hold.type = "button";
  hold.addEventListener("click", () => saveDecision("held"));
  actions.append(approve, hold);
  form.addEventListener("submit", (event) => event.preventDefault());
  form.append(fieldset, noteLabel, note, actions,
    element("p", "Mark reviewed records an actual human review, not a guarantee of anonymity. These checks are not required to download an unreviewed ready pair. Hold excludes the pair. There are no manual masks or pair repairs in this tool.", "muted"));
  ui.panel.append(form);
}

function render() {
  ui.progress.textContent = state.busy
    ? `Processing locally… ${state.progress || "Please wait."}`
    : state.progress || "Ready. Manual review is optional.";
  ui.progress.classList.toggle("busy", state.busy);
  ui.batches.replaceChildren();
  for (const batch of state.batches) {
    const option = element("option", `${batch.createdAt} · ${batch.id}`);
    option.value = batch.id;
    ui.batches.append(option);
  }
  if (!state.batches.length) ui.batches.append(element("option", "No batches yet"));
  ui.batches.value = batchId || "";
  const batch = currentBatch();
  ui.summary.replaceChildren();
  ui.cases.replaceChildren();
  ui.excludedList.replaceChildren();
  ui.excluded.hidden = !batch?.excluded.length;
  if (batch) {
    const counts = { pending: 0, approved: 0, held: 0 };
    batch.cases.forEach((item) => { counts[item.decision] += 1; });
    ui.summary.append(element("p",
      `${batch.inputCount} inputs · ${batch.pairs} pairs · ${counts.pending + counts.approved} ready · ${counts.pending} unreviewed · ${counts.approved} manually reviewed · ${counts.held} held (excluded)`));
    const issues = Object.entries(batch.issueCounts || {}).map(([name, count]) => `${name}: ${count}`);
    ui.summary.append(element("p", `Issue counts: ${issues.length ? issues.join(" · ") : "none"}`, "muted"));
    ui.excludedSummary.textContent = `Skipped inputs (${batch.excluded.length})`;
    for (const input of batch.excluded) {
      const row = element("li");
      row.append(element("span", `${input.name} (${input.id}) — ${input.reason} `),
        fullSizeLink(input.originalUrl, "View original ↗"));
      ui.excludedList.append(row);
    }
    for (const item of batch.cases) {
      const row = element("li");
      const button = element("button");
      button.type = "button";
      button.className = item.id === caseId ? "selected" : "";
      button.setAttribute("aria-pressed", String(item.id === caseId));
      button.append(element("strong", item.id), element("span", `Printed ID: ${item.originalId}`),
        element("span", reviewLabel(item), `decision ${item.decision}`));
      button.addEventListener("click", () => { caseId = item.id; render(); });
      row.append(button);
      ui.cases.append(row);
    }
    if (!batch.cases.length) ui.cases.append(element("li", "No pairs available."));
  }
  renderCase();
  updateControls();
}

async function refreshState() {
  clearTimeout(pollTimer);
  pollTimer = null;
  if (reading) return;
  reading = true;
  pollingFailed = false;
  updateControls();
  try {
    const next = await api("/api/state");
    if (!Array.isArray(next.batches) || typeof next.busy !== "boolean") {
      throw new Error("The local server returned an invalid batch state.");
    }
    state = next;
    loaded = true;
    if (!currentBatch()) batchId = state.batches[0]?.id || null;
    if (!currentCase()) caseId = currentBatch()?.cases[0]?.id || null;
    showError(state.error);
    render();
    if (state.busy) pollTimer = setTimeout(refreshState, 800);
  } catch (error) {
    pollingFailed = true;
    showError(`Could not refresh: ${error.message} Existing review data has been kept. Use Refresh to retry.`);
    ui.progress.textContent = "Status unavailable. Automatic polling paused.";
  } finally {
    reading = false;
    updateControls();
  }
}

async function saveDecision(decision) {
  if (locked() || !currentCase()) return;
  const draft = currentDraft();
  if (decision === "approved" && !Object.values(draft.checks).every(Boolean)) {
    showError("Complete all three checks before marking this pair reviewed.");
    return;
  }
  if (decision === "held" && !draft.note.trim()) {
    showError("Write a reason before holding this pair.");
    return;
  }
  requesting = true;
  updateControls();
  showError("");
  let saved = false;
  try {
    const result = await api("/api/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batchId, caseId, decision, note: draft.note, checks: { ...draft.checks } }),
    });
    if (result.saved !== true) throw new Error("The server did not confirm the saved decision.");
    saved = true;
  } catch (error) {
    showError(`Decision not saved: ${error.message} Your checks and note have been kept.`);
  } finally {
    requesting = false;
    updateControls();
  }
  if (saved) await refreshState();
}

ui.files.addEventListener("change", () => {
  const files = Array.from(ui.files.files);
  if (files.some((file) => !/\.jpe?g$/i.test(file.name))) {
    showError("Choose JPG / JPEG files only. This selection was not added; previously added files have been kept.");
  } else {
    for (const file of files) {
      const key = JSON.stringify([file.name, file.size, file.lastModified]);
      if (!pendingFiles.has(key)) pendingFiles.set(key, file);
    }
  }
  ui.files.value = "";
  updateControls();
});
ui.clearSelection.addEventListener("click", () => {
  if (locked()) return;
  pendingFiles.clear();
  ui.files.value = "";
  updateControls();
});
ui.acknowledgment.addEventListener("change", updateControls);
ui.refresh.addEventListener("click", refreshState);
ui.batches.addEventListener("change", () => {
  batchId = ui.batches.value;
  caseId = currentBatch()?.cases[0]?.id || null;
  render();
});
ui.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (locked() || !ui.form.reportValidity()) return;
  const files = Array.from(pendingFiles.values());
  if (!files.length || !ui.acknowledgment.checked) return;
  if (files.some((file) => !/\.jpe?g$/i.test(file.name))) {
    showError("Choose JPG / JPEG files only.");
    return;
  }
  const data = new FormData();
  files.forEach((file) => data.append("files", file));
  data.append("artificial_data", "yes");
  requesting = true;
  ui.progress.textContent = "Uploading to the local processor…";
  showError("");
  updateControls();
  let accepted = false;
  try {
    const result = await api("/api/upload", { method: "POST", body: data });
    if (result.accepted !== true) throw new Error("The server did not confirm the upload.");
    accepted = true;
    pendingFiles.clear();
    ui.form.reset();
    batchId = null;
    caseId = null;
  } catch (error) {
    showError(`Upload failed: ${error.message} Your pending files have been kept.`);
    ui.progress.textContent = "Upload not confirmed. Existing batches have been kept.";
  } finally {
    requesting = false;
    updateControls();
  }
  if (accepted) await refreshState();
});

ui.release.addEventListener("click", async () => {
  if (locked() || !currentBatch()?.cases.some(isReady)) {
    showError("No ready pairs to download. Held cases and uncertain or excluded inputs are not included.");
    return;
  }
  requesting = true;
  updateControls();
  showError("");
  let objectUrl;
  try {
    const response = await fetch(`/api/release/${encodeURIComponent(batchId)}`, {
      credentials: "same-origin", mode: "same-origin", redirect: "error", cache: "no-store",
    });
    if (!response.ok) {
      let result;
      try { result = await response.json(); }
      catch { throw new Error(`Download failed (HTTP ${response.status}).`); }
      throw new Error(result.error || `Download failed (HTTP ${response.status}).`);
    }
    objectUrl = URL.createObjectURL(await response.blob());
    const link = element("a");
    link.href = objectUrl;
    link.download = `ready-pairs-${batchId}.zip`;
    document.body.append(link);
    link.click();
    link.remove();
  } catch (error) {
    showError(`Release download failed: ${error.message}`);
  } finally {
    if (objectUrl) setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
    requesting = false;
    updateControls();
  }
});

refreshState();
