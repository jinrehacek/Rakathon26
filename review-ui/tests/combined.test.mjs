import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { adaptCombined, digest } from '../combined-analysis.js';
import { buildLesionCsv, validateReview } from '../redcap.js';
import { validateSurgery } from '../surgery.js';
import { buildCentralDecisions } from '../central-decisions.js';
import { validSavedReview } from '../review-state.js';

const sectors = JSON.parse(await readFile(new URL('../assets/sectors.json', import.meta.url)));
async function fixture() {
  const text = 'Ložisko vpravo. Bez perineurální invaze. Gleason 3+4. 😀';
  const evidence = { id: 'e1', quotation: text, start_offset: 0, end_offset: [...text].length };
  const prop = (property, value, extra = {}) => ({ property, status: 'recorded', basis: 'explicit', disposition: 'adopted', supports: ['report:o1'], value, confidence: { final: 'high', explanations: ['Fixture'] }, ...extra });
  const report = { document: { source_sha256: 'a'.repeat(64) }, text_layer: { text, text_sha256: await digest(text) }, extraction: { id: 'extract-1', output_contract_version: 'report-3', complete: true, evidence: [evidence], subjects: [{ id: 'f1', kind: 'tumour_focus', label: 'Focus A' }], observations: [{ id: 'o1', evidence_ids: ['e1'] }] } };
  const drawing = { extraction: { case_id: 'case-1', schema_version: 'drawing-1', source_sha256: 'b'.repeat(64) }, marks: [{ id: 'mid.m1', redcap: ['pzpl_mid_rs'] }] };
  const reportBytes = JSON.stringify(report), drawingBytes = JSON.stringify(drawing);
  const properties = [prop('histology_type', { type: 'coded', code: '2' }), prop('perineural_invasion', { type: 'presence', value: 'absent' }), prop('extraprostatic_extension', { type: 'presence', value: 'absent' }, { basis: 'inferred', requires_confirmation: true }), prop('gleason_patterns', { type: 'gleason_patterns', primary: { pattern: 3, percent: 65 }, secondary: { pattern: 4, percent: 35 }, original_wording: '3+4' })];
  const raw = { schema_version: 'combined-1', case_id: 'case-1', pairing: { case_id: 'case-1', assessment: 'supported' }, inputs: { report: { sha256: await digest(reportBytes), extraction_id: 'extract-1' }, drawing: { sha256: await digest(drawingBytes) } }, candidates: [{ id: 'c1', marks: ['mid.m1'] }], matching: { hypotheses: [{ id: 'h1', focus: 'f1' }] }, lesions: [{ id: 'L1', order: 3, kind: 'tumour focus', focus: 'f1', hypothesis: 'h1', marks: ['mid.m1'], candidates: ['c1'], properties, sectors: { in: ['pzpl_mid_rs'], maybe: ['pzpm_mid_rs'], confidence: { final: 'medium' } } }], specimen: { properties: [prop('classification_pt', { type: 'classification', original_code: 'pT2' }), prop('classification_r', { type: 'classification', original_code: 'R0' }), prop('grade_group', { type: 'coded', code: '2' })] }, issues: [{ id: 'q1', kind: 'unmatched_candidate', severity: 'question', context: ['missing-mark'], explanation: 'Unmatched ink' }, { id: 'info1', kind: 'llm_missing', severity: 'info', context: [] }], details: [], other_findings: [], brains: {} };
  const adapt = () => adaptCombined(raw, sectors, { reportBytes, drawingBytes });
  return { raw, report, drawing, reportBytes, drawingBytes, adapt, prop };
}
function approve(state) {
  state.recordId = 'TEST-REVIEW';
  for (const lesion of state.lesions) { lesion.reviewed = true; for (const issue of lesion.issues) Object.assign(issue, { resolved: true, resolution: 'Reviewed fixture', disposition: 'resolved' }); }
  for (const issue of state.caseIssues) if (issue.severity === 'question') Object.assign(issue, { resolved: true, resolution: 'Reviewed fixture', disposition: 'resolved' });
  state.surgery = { ...state.surgery, reviewed: true, values: { surgery_date: '2026-10-16', surgery_type: '2', total_number_lesion_surg: '1', lymphadenectomy: '2', classify_r_surg: '1', classify_l_surg: '1', vascular_inv: '1', histol_post_surg: '1' } };
  return state;
}

test('combined input pins, scope, uncertainty, and stable repeat order survive projection', async () => {
  const f = await fixture(), before = JSON.stringify(f.raw), state = await f.adapt();
  assert.equal(JSON.stringify(f.raw), before);
  assert.equal(state.lesions[0].instance, 3);
  assert.equal(state.lesions[0].values.hist_type_sur, '2');
  assert.equal(state.lesions[0].values.perineural_inv_sur, '3');
  assert.equal(state.lesions[0].values.gleason_prim_perc, '65');
  assert.equal(state.lesions[0].values.gleason_sec_grade, '4');
  assert.deepEqual(state.lesions[0].regions, ['pzpl_mid_rs']);
  assert.deepEqual(state.lesions[0].maybeRegions, ['pzpm_mid_rs']);
  assert.equal(state.surgery.values.pt_surg, undefined, 'plain pT2 must not become pT2a/b/c');
  assert.equal(state.surgery.values.isup, '2');
  assert.equal(state.lesions[0].values.isup, undefined);
  assert.equal(state.caseIssues[0].id, 'q1', 'unmatched global questions remain reviewable');
  assert.ok(validateReview(state, sectors).length > 0);
  assert.throws(() => buildLesionCsv(state, sectors), /Cannot export/);
});

test('changed extraction bytes and invalid case pairing fail closed', async () => {
  const f = await fixture();
  await assert.rejects(adaptCombined(f.raw, sectors, { reportBytes: f.reportBytes + ' ', drawingBytes: f.drawingBytes }), /SHA-256/);
  f.raw.pairing.case_id = 'wrong';
  await assert.rejects(f.adapt(), /pairing/);
});

test('unknown sectors and orphaned focus cannot become export records', async () => {
  const f = await fixture(); f.raw.lesions[0].sectors.in = ['invented']; await assert.rejects(f.adapt(), /sector/);
  f.raw.lesions[0].sectors.in = []; f.raw.lesions[0].focus = 'missing'; await assert.rejects(f.adapt(), /focus/);
});

test('availability states stay distinct and unresolved candidates supply no selected value', async () => {
  for (const status of ['not reported', 'unreadable', 'not assessed', 'not applicable']) {
    const f = await fixture(), p = f.raw.lesions[0].properties[1];
    delete p.value; p.status = status; p.disposition = 'unavailable';
    const state = await f.adapt();
    assert.equal(state.lesions[0].sourceObservations[1].status, status);
    assert.equal(state.lesions[0].values.perineural_inv_sur, status === 'not reported' ? '4' : undefined);
  }
  const f = await fixture(), p = f.raw.lesions[0].properties[0];
  p.disposition = 'unresolved'; p.candidates = [{ value: p.value }]; delete p.value;
  assert.equal((await f.adapt()).lesions[0].values.hist_type_sur, undefined);
});

test('inferred specimen attribution has a blocking question even without upstream issue', async () => {
  const state = await (await fixture()).adapt();
  assert.ok(state.lesions[0].issues.some(i => i.id.includes('extraprostatic_extension') && !i.resolved));
});

test('single CSV writer emits surgery plus stable lesion rows with explicit checkbox values', async () => {
  const state = approve(await (await fixture()).adapt());
  const csv = buildLesionCsv(state, sectors), rows = csv.trimEnd().split('\r\n').map(r => r.split(','));
  const field = name => rows[0].indexOf(name);
  assert.equal(rows.length, 3);
  assert.equal(rows[1][field('redcap_repeat_instrument')], '');
  assert.equal(rows[1][field('surgery_date')], '2026-10-16');
  assert.equal(rows[2][field('redcap_repeat_instance')], '3');
  assert.equal(rows[2][field('sur_prostate_regions___pzpl_mid_rs')], '1');
  assert.equal(rows[2][field('sur_prostate_regions___pzpm_mid_rs')], '0');
  assert.equal(rows[1][field('surgery_c61_complete')], '0');
  assert.equal(rows[2][field('surgery_c61_resected_lesion_complete')], '0');
  assert.ok(rows.every(r => r.length === rows[0].length));
  state.caseIssues[0].resolved = false;
  assert.throws(() => buildLesionCsv(state, sectors), /Case question/);
});

test('information notices do not block export, unresolved checkbox questions do', async () => {
  const state = approve(await (await fixture()).adapt());
  assert.deepEqual(validateReview(state, sectors), []);
  state.caseIssues[0].regionCodes = ['pzpl_mid_rs']; state.caseIssues[0].disposition = 'reviewed_unknown';
  assert.ok(validateReview(state, sectors).some(e => e.includes('sector uncertainty')));
});

test('surgery branching, dates, node counts, and spreadsheet content are validated', () => {
  const state = approve({ lesions: [], caseIssues: [], surgery: {} });
  assert.deepEqual(validateSurgery(state.surgery), []);
  state.surgery.values.surgery_date = '2026-02-30';
  state.surgery.values.lymphadenectomy = '1';
  state.surgery.values.node_no_surgery = '1'; state.surgery.values.node_positive_no_surgery = '2';
  state.surgery.values.surgery_text = '=HYPERLINK("evil")';
  const errors = validateSurgery(state.surgery);
  assert.ok(errors.some(e => e.includes('valid date')));
  assert.ok(errors.some(e => e.includes('exceed')));
  assert.ok(errors.some(e => e.includes('spreadsheet')));
});

test('matching changes block CSV and decisions use central schema with original issue IDs', async () => {
  const state = approve(await (await fixture()).adapt());
  state.needsRerun = true;
  state.centralDecisions.push({ id: 'review-1', kind: 'assign_mark', target: { focus: 'f1', mark: 'mid.m1' }, value: null, reason: 'Fixture', reviewer: 'Tester', timestamp: new Date().toISOString() });
  assert.throws(() => buildLesionCsv(state, sectors), /rerun central/);
  assert.throws(() => buildCentralDecisions(state), /reviewer/);
  const result = buildCentralDecisions(state, { reviewer: 'Tester' });
  assert.equal(result.schema_version, 'decisions-1');
  assert.ok(result.decisions.some(d => d.kind === 'resolve_issue' && d.target.issue === 'q1'));
});

test('saved global questions and source provenance cannot disappear across reloads', async () => {
  const prediction = await (await fixture()).adapt(), state = structuredClone(prediction);
  assert.equal(validSavedReview(state, prediction, sectors, {}), true);
  state.caseIssues = [];
  assert.equal(validSavedReview(state, prediction, sectors, {}), false);
});

test('retaining uncertainty cannot approve an inferred negative as a known finding', async () => {
  const state = approve(await (await fixture()).adapt());
  const issue = state.lesions[0].issues.find(i => i.property === 'extraprostatic_extension');
  issue.disposition = 'reviewed_unknown';
  assert.ok(validateReview(state, sectors).some(e => e.includes('despite a reviewed-unknown')));
  state.lesions[0].values.extracaps_ext = '2';
  assert.deepEqual(validateReview(state, sectors), []);
});
