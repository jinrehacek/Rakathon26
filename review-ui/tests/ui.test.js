import { adaptAnalysis } from "../analysis.js";
import { validSavedReview } from "../review-state.js";
import { atlasLabel, sectorName } from "../map-labels.js";

// Run on the prepared showcase. Saved storage is restored, but reload afterwards
// to replace the in-memory test edits. No scan contents or case values are logged.
export async function runUiTests() {
  const $ = selector => document.querySelector(selector);
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const sectors = await (await fetch("assets/sectors.json")).json();
  const caseConfig = await (await fetch(".local-data/case.json")).json();
  const raw = await (await fetch(caseConfig.analysisUrl)).json();
  const reportText = await (await fetch(caseConfig.reportTextUrl)).text();
  const prediction = await adaptAnalysis(raw, sectors, {
    caseId: caseConfig.caseId, reportText, showcase: true, demoAssignments: caseConfig.demoAssignments,
  });
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify({
    raw, caseConfig, adapter: prediction.schemaVersion,
  })));
  const fingerprint = [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  const key = `prostapaper.review.v2.${caseConfig.caseId}.${fingerprint}`;
  const backup = localStorage.getItem(key);
  const originalConfirm = window.confirm;
  const originalObjectUrl = URL.createObjectURL;
  const originalClick = HTMLAnchorElement.prototype.click;
  let confirmResult = true, downloaded, passed = 0;
  const stored = () => JSON.parse(localStorage.getItem(key));
  const current = () => stored().lesions.find(lesion => lesion.id === $("#lesion-list .active").dataset.lesion);
  const change = (selector, value) => {
    const input = $(selector);
    assert(input && !input.disabled, `Control unavailable: ${selector}`);
    if (input.type === "checkbox") input.checked = value;
    else input.value = value;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const quotation = [...reportText].slice(0, 80).join("");
  const confirmChange = ({ absent = false } = {}) => {
    assert($("#change-dialog").open, "Every clinical edit must open a confirmation dialog");
    $("#change-reason").value = "Synthetic UI test decision, not a clinical assessment.";
    if (!$("#change-evidence").hidden) {
      if (absent) change("#change-source", "absent");
      else $("#change-quote").value = quotation;
    }
    $("#change-form").requestSubmit();
    assert(!$("#change-dialog").open, $("#change-error").textContent || "Confirmation should apply");
  };
  try {
    window.confirm = () => confirmResult;
    URL.createObjectURL = blob => { downloaded = blob; return originalObjectUrl.call(URL, blob); };
    HTMLAnchorElement.prototype.click = function () {
      if (!this.download) originalClick.call(this);
    };
    if (raw.schema_version === "doctor-review-showcase-v1" && backup === null) {
      const initialActiveId = $("#lesion-list .active").dataset.lesion;
      for (const lesion of raw.lesions) {
        $(`#lesion-list [data-lesion="${lesion.id}"]`).click();
        for (const [field, proposed] of Object.entries(lesion.fields)) {
          assert($(`[data-field="${field}"]`).value === proposed.value,
            `First-load ${field} must match the input JSON without manual entry`);
          assert($(`[data-field-origin="${field}"]`).textContent === "From analysis",
            "Analysis-prefilled properties must be visibly distinguished from doctor corrections");
        }
        assert($("#prefill-summary").textContent.includes("12 of 12") &&
          !$("#confirm-lesion").checked && $("#export-csv").disabled,
          "Autofill is a draft, not automatic review or export approval");
      }
      $(`#lesion-list [data-lesion="${initialActiveId}"]`).click();
      assert(localStorage.getItem(key) === null, "Inspecting prefilled properties must not create doctor edits");
      passed++;
    }
    confirmResult = false;
    const originalId = $("#record-id").value;
    change("#record-id", "TEST-CANCELLED");
    assert($("#record-id").value === originalId && localStorage.getItem(key) === backup,
      "Cancelling record identity must preserve state/storage");
    confirmResult = true;
    change("#record-id", "TEST-UI-REVIEW");
    passed++;

    const activeId = $("#lesion-list .active").dataset.lesion;
    const beforeNavigation = localStorage.getItem(key);
    assert(document.querySelectorAll(".region-map polygon[data-region]").length === 41 &&
      document.querySelectorAll(".region-map image").length === 0 &&
      document.querySelectorAll("[data-level-nav], #profile-views").length === 0,
      "Keep all 41 editing controls once; front/side anatomy belongs in the read-only reference");
    assert(!document.querySelector("#region-directory, .region-directory") &&
      [...document.querySelectorAll(".region-map polygon[data-region]")].every(region =>
        region.getAttribute("tabindex") === "0" && region.getAttribute("aria-label")),
      "Remove the duplicate region list while retaining labelled, keyboard-focusable map regions");
    assert(!$("#technical-details").open && $("#technical-details").contains($("#download-json")) &&
      $("#technical-details").contains($("#analysis-json-source")) &&
      !$(".properties").contains($("#analysis-json-source")) && !$(".atlas-context").open,
      "Raw JSON tools and read-only front/side anatomy must be collapsed outside clinical properties");
    assert(document.querySelectorAll("#atlas-overview [data-overview-region]").length === 41 &&
      !$("#atlas-overview [data-region], #atlas-overview [tabindex]"),
      "The optional full atlas must show context without duplicating editable region controls");
    for (const sector of sectors) {
      const polygon = $(`.region-map [data-region="${sector.code}"]`);
      assert(polygon.getAttribute("points") ===
        sector.points.map(point => point.join(",")).join(" "),
      "Sharper rendering must preserve the original selection geometry and region-code mapping");
      assert(polygon.getAttribute("aria-label").startsWith(`${sectorName(sector)} (${sector.code})`) &&
        polygon.querySelector("title").textContent === `${sectorName(sector)} (${sector.code})`,
        "Every map control and tooltip must use verified names, not misspelled upstream titles");
      const text = polygon.nextElementSibling;
      if (text?.matches("text.sector-label")) {
        assert(text.textContent === atlasLabel(sector), "On-map text must match the atlas, including AFS and mixed casing");
      }
    }
    assert(document.querySelectorAll(".linked-view").length === 5, "Include all three axial levels, vesicles and urethra");
    assert($('.linked-view[data-level=urethra] h3').textContent.startsWith("Urethra (atlas)") &&
      $(".terminology-warning").textContent.includes("Naming needs clinical confirmation"),
      "Keep the atlas/source-title disagreement visible instead of treating two names as interchangeable");
    for (const role of ["report", "text", "drawing"]) {
      $(`#tab-${role}`).click();
      assert(!$(`#view-${role}`).hidden &&
        document.querySelectorAll(".source-viewport [role=tabpanel]:not([hidden])").length === 1,
        "Exactly one full-size source should be visible");
    }
    $("#tab-drawing").dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    assert($("#tab-report").getAttribute("aria-selected") === "true", "Source tabs must support keyboard navigation");
    $("#tab-drawing").click();
    change("#source-zoom", "200");
    assert($("#source-drawing").style.width === "200%", "Source zoom must enlarge the scan");
    change("#source-zoom", "100");
    assert(localStorage.getItem(key) === beforeNavigation, "Source navigation must not change clinical state");
    const sourceWidth = $(".sources").getBoundingClientRect().width;
    const rightWidth = $(".review-workspace").getBoundingClientRect().width;
    assert(Math.abs(sourceWidth - rightWidth) < 2, "Sources and interactive workspace must have equal widths");
    passed++;

    $(".atlas-context").open = true;
    $("#atlas-overview [data-overview-region]").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    $(".atlas-context").open = false;
    const chip = $("#selected-regions [data-inspect-region]");
    assert(chip, "The prepared synthetic lesion must have an inspectable region");
    const expectedLevel = ["base", "mid", "apex"].find(level =>
      !chip.dataset.inspectRegion.startsWith("sv_") && chip.dataset.inspectRegion.includes(`_${level}_`));
    chip.click();
    assert(expectedLevel ? $("#linked-views .current")?.dataset.level === expectedLevel : !$("#linked-views .current"),
      "A region chip must inspect its axial level without editing findings or projecting onto front/side anatomy");
    $("#download-json").click();
    const inspected = JSON.parse(await downloaded.text());
    const originalReview = JSON.parse(beforeNavigation);
    assert(JSON.stringify(inspected.lesions) === JSON.stringify(originalReview.lesions) &&
      JSON.stringify(inspected.reviewLog) === JSON.stringify(originalReview.reviewLog) &&
      localStorage.getItem(key) === beforeNavigation,
      "Read-only atlas and region inspection must preserve clinical state and decision history exactly");
    assert(JSON.stringify(inspected.sourceConfig.sourceIdentity) === JSON.stringify(caseConfig.sourceIdentity),
      "Reviewed JSON must preserve the selected source identity without substituting a REDCap target");
    passed++;

    for (const lesion of stored().lesions) {
      $(`#lesion-list [data-lesion="${lesion.id}"]`).click();
      assert(document.querySelectorAll(".region-map polygon.assigned").length === (lesion.excluded ? 0 : lesion.regions.length),
        "Every region of the selected lesion must be highlighted");
      for (const code of lesion.regions) assert($("#selected-regions").textContent.includes(code),
        "Active lesion summary must show every assigned REDCap region code");
    }
    const multiRegion = stored().lesions.find(lesion => !lesion.excluded && lesion.regions.length > 1);
    assert(multiRegion, "The synthetic demo must exercise a single lesion with multiple segments");
    $(`#lesion-list [data-lesion="${multiRegion.id}"]`).click();
    assert(document.querySelectorAll(".region-map polygon.assigned").length === multiRegion.regions.length &&
      document.querySelectorAll("#atlas-overview polygon.assigned").length === multiRegion.regions.length,
      "Every segment of one lesion must highlight in both the compact editor and read-only reference");
    passed++;
    $(`#lesion-list [data-lesion="${activeId}"]`).click();
    passed++;

    const otherRegion = sectors.find(sector => !current().regions.includes(sector.code)).code;
    const otherLesions = JSON.stringify(stored().lesions.filter(lesion => lesion.id !== activeId));
    const region = () => $(`.region-map [data-region="${otherRegion}"]`);
    region().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    assert(current().regions.includes(otherRegion) && !$("#change-dialog").open &&
      Object.keys(current().pendingRegionEdits).length === 1 && $("#export-csv").disabled &&
      $("#confirm-lesion").disabled, "A click must stage an immediate assignment, blocking export until evidenced");
    assert(JSON.stringify(stored().lesions.filter(lesion => lesion.id !== activeId)) === otherLesions,
      "Editing the active lesion must not alter any other lesion");
    $("#undo-region").click();
    assert(!current().regions.includes(otherRegion) && Object.keys(current().pendingRegionEdits).length === 0,
      "Undo must restore the prior assignment without fabricating evidence");
    region().focus();
    region().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    assert(current().regions.includes(otherRegion) && document.activeElement.dataset.region === otherRegion,
      "Keyboard selection must edit and retain focus");
    region().dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true }));
    assert(!current().regions.includes(otherRegion), "Space must remove an already assigned region");
    region().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const beforeCancel = localStorage.getItem(key);
    $("#document-regions").click();
    $("#cancel-change").click();
    assert(localStorage.getItem(key) === beforeCancel && !$("#document-regions").disabled,
      "Cancelling evidence documentation must preserve the staged edits");
    $("#document-regions").click();
    confirmChange();
    assert(current().regions.includes(otherRegion) && Object.keys(current().pendingRegionEdits).length === 0 &&
      current().regionEvidence[otherRegion].quotation === quotation && !current().reviewed,
      "Grouped documentation must retain evidence, clear pending edits and still require review");
    passed++;

    const issueId = $("[data-disposition]").dataset.disposition;
    change(`[data-resolution="${issueId}"]`, "Synthetic reviewed uncertainty remains unknown.");
    change(`[data-disposition="${issueId}"]`, "reviewed_unknown");
    assert(current().issues.find(issue => issue.id === issueId).disposition === "reviewed_unknown",
      "Retained uncertainty needs an explicit saved disposition");
    passed++;

    const value = current().values.hist_type_sur === "2" ? "1" : "2";
    const beforeField = localStorage.getItem(key);
    change('[data-field="hist_type_sur"]', value);
    $("#change-reason").value = "Synthetic invalid quote check.";
    $("#change-quote").value = "THIS IS NOT IN THE SYNTHETIC REPORT";
    $("#change-form").requestSubmit();
    assert($("#change-dialog").open && !$("#change-error").hidden &&
      localStorage.getItem(key) === beforeField, "Invalid evidence must not apply a change");
    $("#change-basis").value = "inferred";
    confirmChange();
    assert(current().values.hist_type_sur === value && current().valueEvidence.hist_type_sur.basis === "inferred",
      "Confirmed field changes must retain evidence and inference basis");
    assert($("#doctor-observations").textContent.includes("Doctor inferences"),
      "Inferred decisions must be displayed separately from explicit findings");
    const reopened = current().issues.find(issue => issue.id === issueId);
    assert(!current().reviewed && !reopened.resolved && reopened.resolution.includes("remains unknown"),
      "Edits reopen issues, retain reasons and invalidate confirmation");
    passed++;

    const beforeNumber = localStorage.getItem(key);
    change('[data-field="lesion_x_mm"]', "-1");
    assert(localStorage.getItem(key) === beforeNumber && !$("#notice").hidden,
      "Out-of-range dimensions must be rejected with a visible error");
    passed++;

    const initialCount = stored().lesions.length;
    for (let i = 0; i < 3; i++) {
      $("#add-lesion").click();
      assert(![...$("#change-source").options].some(option => option.value === "drawing-image"),
        "A drawing alone must not create a lesion");
      if (i === 0) {
        change("#change-source", "report-image");
        const image = $("#change-scan");
        if (!image.complete || !image.naturalWidth) {
          await new Promise((resolve, reject) => {
            image.addEventListener("load", resolve, { once: true });
            image.addEventListener("error", () => reject(new Error("Evidence source failed to load")), { once: true });
          });
        }
        assert($("#change-quote-label").hidden && !$("#change-crop").hidden,
          "Image evidence must replace the quotation input");
        const frame = $("#crop-frame");
        const rect = image.getBoundingClientRect();
        const capture = Object.getOwnPropertyDescriptor(frame, "setPointerCapture");
        // Synthetic events have no native active pointer to capture.
        frame.setPointerCapture = () => {};
        try {
          frame.dispatchEvent(new PointerEvent("pointerdown", {
            button: 0, pointerId: 7, clientX: rect.left + rect.width * .1, clientY: rect.top + rect.height * .1,
          }));
          frame.dispatchEvent(new PointerEvent("pointermove", {
            pointerId: 7, clientX: rect.left + rect.width * .3, clientY: rect.top + rect.height * .3,
          }));
          frame.dispatchEvent(new PointerEvent("pointerup", { pointerId: 7 }));
        } finally {
          if (capture) Object.defineProperty(frame, "setPointerCapture", capture);
          else delete frame.setPointerCapture;
        }
      }
      confirmChange();
      if (i === 0) {
        const evidence = current().creationEvidence;
        const image = $("#source-report img");
        assert(evidence.kind === "image_crop" && evidence.bounds[0] === Math.round(image.naturalWidth * .1) &&
          evidence.bounds[2] === Math.round(image.naturalWidth * .3) - Math.round(image.naturalWidth * .1),
          "Pointer selection must record original-image pixel bounds, not displayed pixels");
        passed++;
      }
    }
    assert(stored().lesions.length === initialCount + 3 && stored().lesions.length > 4,
      "The repeating surgery form must support more than four lesions");
    assert(Object.keys(current().values).length === 0 && current().regions.length === 0 &&
      !current().reviewed && current().creationEvidence.source === "report",
      "Doctor additions must have report evidence and no fabricated clinical defaults");
    const addedId = current().id, instance = current().instance;
    passed++;

    change("#assign-region", true);
    $("#document-regions").click();
    confirmChange();
    const chosenRegions = [...current().regions];
    $("#exclude-lesion").click();
    confirmChange();
    assert(current().excluded && current().regions.join() === chosenRegions.join() &&
      $(".region-map .assigned") === null && $('[data-field="hist_type_sur"]').disabled,
      "Exclusion preserves findings but removes highlighting and prevents editing");
    $("#exclude-lesion").click();
    confirmChange();
    assert(!current().excluded && current().instance === instance && !current().reviewed &&
      current().regions.join() === chosenRegions.join(), "Restoration preserves the stable instance and requires review");
    passed++;

    for (const lesion of stored().lesions.filter(lesion => lesion.id !== addedId && !lesion.excluded)) {
      $(`#lesion-list [data-lesion="${lesion.id}"]`).click();
      $("#exclude-lesion").click();
      confirmChange();
    }
    $(`#lesion-list [data-lesion="${addedId}"]`).click();
    change('[data-field="hist_type_sur"]', "2");
    confirmChange();
    for (const field of ["extracaps_ext", "perineural_inv_sur"]) {
      change(`[data-field="${field}"]`, "4");
      confirmChange({ absent: true });
    }
    assert($("#export-csv").disabled, "Complete fields without explicit lesion review must still block export");
    $("#confirm-lesion").click();
    assert(!$("#export-csv").disabled, "Confirmed, fully answered included lesion should enable export");
    $("#export-csv").click();
    const csv = await downloaded.text();
    const lines = csv.trimEnd().split("\r\n");
    assert(lines.length === 2 && lines[0].split(",").length === 58 &&
      lines[1].split(",")[2] === String(instance), "CSV must emit one 58-column included row with its unchanged instance");
    passed++;

    $("#download-json").click();
    const review = JSON.parse(await downloaded.text());
    assert(review.lesions.length === initialCount + 3 &&
      JSON.stringify(review.originalPrediction) === JSON.stringify(prediction) &&
      review.exportPurpose === "first_import_lesion_draft", "Review JSON must retain exclusions and immutable original proposals");
    const imageSizes = Object.fromEntries(["report", "drawing"].map(role => {
      const image = $(`#source-${role} img`);
      return [role, { width: image.naturalWidth, height: image.naturalHeight }];
    }));
    assert(validSavedReview(stored(), prediction, sectors, { reportText, sources: caseConfig.sources, imageSizes }),
      "The actual edited/excluded/added review must pass restoration validation");
    passed++;
    return { passed, reloadRequired: true };
  } finally {
    window.confirm = originalConfirm;
    URL.createObjectURL = originalObjectUrl;
    HTMLAnchorElement.prototype.click = originalClick;
    if (backup === null) localStorage.removeItem(key);
    else localStorage.setItem(key, backup);
  }
}
