// Run in the prepared combined case. Original storage is restored afterwards.
export async function runCombinedUiTests() {
  const $ = selector => document.querySelector(selector);
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const originalConfirm = window.confirm;
  const originalClick = HTMLAnchorElement.prototype.click;
  const originalUrl = URL.createObjectURL;
  const keys = Object.keys(localStorage).filter(k => k.startsWith('prostapaper.review.combined.v1.'));
  const backup = new Map(keys.map(k => [k, localStorage.getItem(k)]));
  let blob, passed = 0;
  const state = () => {
    const current = Object.keys(localStorage).find(k => k.startsWith('prostapaper.review.combined.v1.') && !backup.has(k)) || Object.keys(localStorage).find(k => k.startsWith('prostapaper.review.combined.v1.') && localStorage.getItem(k) !== backup.get(k));
    return JSON.parse(localStorage.getItem(current));
  };
  const change = (selector, value) => {
    const input = $(selector); assert(input && !input.disabled, `Unavailable control ${selector}`);
    input.value = value; input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const submit = () => {
    $('#change-reason').value = 'Automated UI probe, not a clinical review.';
    if (!$('#change-evidence').hidden) $('#change-quote').value = $('#analysis-report').textContent.slice(0, 30);
    $('#change-form').requestSubmit();
    assert(!$('#change-dialog').open, $('#change-error').textContent || 'Decision failed');
  };
  try {
    window.confirm = () => true;
    HTMLAnchorElement.prototype.click = function () { if (!this.download) originalClick.call(this); };
    URL.createObjectURL = value => { blob = value; return originalUrl.call(URL, value); };
    assert(document.querySelectorAll('.region-map [data-region]').length === 41, 'All 41 sectors must be clickable');
    assert(!$('#central-review').hidden && !$('#surgery-panel').hidden && $('#export-csv').disabled, 'Central review must load with export blocked');
    assert($('.map-panel').getBoundingClientRect().top < $('#central-review').getBoundingClientRect().top, 'Sector editor must precede the case queue');
    passed++;
    $('#reviewer').value = 'UI test reviewer';
    change('#record-id', 'TEST-COMBINED-UI');
    const activeId = $('#lesion-list .active').dataset.lesion;
    const before = structuredClone(state());
    const code = $('.region-map [data-region]').dataset.region;
    $('.region-map [data-region]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    assert(state().lesions.find(l => l.id === activeId).regions.includes(code) !== before.lesions.find(l => l.id === activeId).regions.includes(code), 'Sector click must toggle the active lesion only');
    assert(JSON.stringify(state().lesions.filter(l => l.id !== activeId)) === JSON.stringify(before.lesions.filter(l => l.id !== activeId)), 'Other lesions must remain unchanged');
    assert($('#confirm-lesion').disabled && $('#export-csv').disabled, 'Undocumented edits must block confirmation and export');
    $('#undo-region').click();
    passed++;
    const question = $('#case-issues [data-resolution]');
    const id = question.dataset.resolution;
    change(`[data-resolution="${CSS.escape(id)}"]`, 'Inspected case-wide fixture question.');
    change(`[data-disposition="${CSS.escape(id)}"]`, 'resolved');
    assert(state().caseIssues.find(i => i.id === id).resolved, 'Global questions must be resolvable');
    passed++;
    change('[data-surgery-field="surgery_date"]', '2026-10-16'); submit();
    assert(state().surgery.values.surgery_date === '2026-10-16' && !state().surgery.reviewed, 'Surgery entry must save a reason and require confirmation');
    passed++;
    $('#download-json').click();
    const review = JSON.parse(await blob.text());
    assert(review.sourceAnalysis.schema_version === 'combined-1' && review.sourceReport.extraction && review.sourceDrawing.extraction, 'Private review must retain pinned inputs');
    passed++;
    // Drive the complete review/export gate through the actual controls.
    const lesionIds = state().lesions.map(l => l.id);
    for (const lesionId of lesionIds) {
      $(`[data-lesion="${CSS.escape(lesionId)}"]`).click();
      for (const [field, value] of [['hist_type_sur', '2'], ['extracaps_ext', '4'], ['perineural_inv_sur', '4']]) {
        const input = $(`[data-field="${field}"]`);
        if (input.value) continue;
        change(`[data-field="${field}"]`, value);
        if (value === '4') change('#change-source', 'absent');
        submit();
      }
      for (const issueId of [...document.querySelectorAll('#issues [data-resolution]')].map(n => n.dataset.resolution)) {
        change(`[data-resolution="${CSS.escape(issueId)}"]`, 'Synthetic export-gate check, not a clinical decision.');
        change(`[data-disposition="${CSS.escape(issueId)}"]`, 'resolved');
      }
    }
    const surgeryValues = { surgery_date: '2026-10-16', surgery_type: '2', total_number_lesion_surg: String(lesionIds.length), lymphadenectomy: '2', classify_r_surg: '1', classify_l_surg: '1', vascular_inv: '1', histol_post_surg: '1' };
    for (const [field, value] of Object.entries(surgeryValues)) {
      if ($(`[data-surgery-field="${field}"]`).value === value) continue;
      change(`[data-surgery-field="${field}"]`, value); submit();
    }
    for (const issueId of [...document.querySelectorAll('#case-issues [data-resolution]')].map(n => n.dataset.resolution)) {
      change(`[data-resolution="${CSS.escape(issueId)}"]`, 'Synthetic export-gate check, not a clinical decision.');
      change(`[data-disposition="${CSS.escape(issueId)}"]`, 'resolved');
    }
    for (const lesionId of lesionIds) {
      $(`[data-lesion="${CSS.escape(lesionId)}"]`).click();
      if (!$('#confirm-lesion').checked) $('#confirm-lesion').click();
    }
    if (!$('#confirm-surgery').checked) $('#confirm-surgery').click();
    assert(!$('#export-csv').disabled, $('#export-errors').textContent || 'Completed review should allow CSV');
    $('#export-csv').click();
    const csv = await blob.text();
    assert(csv.includes('surgery_c61_complete') && csv.includes('surgery_date') && csv.trimEnd().split('\r\n').length === lesionIds.length + 2, 'Browser CSV must contain one surgery row and each reviewed lesion');
    passed++;
    const assignment = $('[data-mark-assignment]');
    change(`[data-mark-assignment="${CSS.escape(assignment.dataset.markAssignment)}"]`, assignment.options[1].value);
    submit();
    assert(state().needsRerun && $('#export-csv').disabled, 'Matching changes must block stale CSV');
    $('#download-decisions').click();
    const decisions = JSON.parse(await blob.text());
    assert(decisions.schema_version === 'decisions-1' && decisions.decisions.some(d => d.kind === 'assign_mark'), 'Matching export must use the central decisions schema');
    assert(decisions.decisions.some(d => d.kind === 'resolve_issue' && d.target.issue === id), 'Case question IDs must survive export');
    passed++;
    return { passed, reloadRequired: true };
  } finally {
    window.confirm = originalConfirm;
    HTMLAnchorElement.prototype.click = originalClick;
    URL.createObjectURL = originalUrl;
    for (const key of Object.keys(localStorage)) if (key.startsWith('prostapaper.review.combined.v1.') && !backup.has(key)) localStorage.removeItem(key);
    for (const [key, value] of backup) localStorage.setItem(key, value);
  }
}
