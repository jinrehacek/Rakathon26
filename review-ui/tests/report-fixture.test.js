import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runAnalysisTests } from './analysis.test.js';

test('documented report-only demo keeps its compatible legacy fixture', async () => {
  const raw = JSON.parse(await readFile(new URL('../../fixtures/synthetic_response.json', import.meta.url), 'utf8'));
  const text = await readFile(new URL('../../fixtures/synthetic_report.txt', import.meta.url), 'utf8');
  const sectors = JSON.parse(await readFile(new URL('../assets/sectors.json', import.meta.url), 'utf8'));
  const result = await runAnalysisTests(raw, text, sectors);
  assert.ok(result.passed > 0);
});
