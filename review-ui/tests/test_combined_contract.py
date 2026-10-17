"""Round trip real central contracts through the JavaScript review projection."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('central_fixtures', ROOT / 'tests/central_fixtures.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class CombinedContractTests(unittest.TestCase):
    def test_real_central_output_and_ui_decisions_round_trip_without_model_calls(self):
        from central.pipeline import run_case
        from central.decisions import Decisions
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, drawing = fixtures.write_case(root)
            combined = run_case('synthetic-case', root=root, use_llm=False)
            script = r'''
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
const [repo, combinedPath, reportPath, drawingPath, decisionPath] = process.argv.slice(2);
const load = name => import(pathToFileURL(`${repo}/review-ui/${name}`));
const { adaptCombined } = await load('combined-analysis.js');
const { buildCentralDecisions } = await load('central-decisions.js');
const sectors = JSON.parse(await readFile(`${repo}/review-ui/assets/sectors.json`));
const raw = JSON.parse(await readFile(combinedPath));
const state = await adaptCombined(raw, sectors, { reportBytes: await readFile(reportPath), drawingBytes: await readFile(drawingPath) });
if (state.lesions.length !== 2 || state.sourceReport.extraction.output_contract_version !== 'report-3') throw Error('Wrong central projection');
const lesion = state.lesions[0];
lesion.values.extracaps_ext = '3';
lesion.valueEvidence = { extracaps_ext: { reason: 'Synthetic review selection.', quotation: state.reportText } };
lesion.regionEvidence = { [lesion.regions[0]]: { reason: 'Synthetic sector review.' } };
state.caseIssues[0].resolved = true;
state.caseIssues[0].resolution = 'Synthetic review decision.';
const output = buildCentralDecisions(state, { reviewer: 'Integration test' });
await writeFile(decisionPath, JSON.stringify(output));
console.log(JSON.stringify({ lesions: state.lesions.length, decisions: output.decisions.length }));
'''
            decisions = root / 'decisions.json'
            result = subprocess.run(['node', '--input-type=module', '-', str(ROOT), str(combined), str(report), str(drawing), str(decisions)], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['lesions'], 2)
            parsed = Decisions.model_validate_json(decisions.read_bytes())
            self.assertTrue(any(d.kind == 'set_value' and d.target.property == 'sectors' for d in parsed.decisions))
            new_path = run_case('synthetic-case', root=root, decisions_path=decisions, previous_path=combined, use_llm=False)
            new = json.loads(new_path.read_bytes())
            prop = next(p for p in new['lesions'][0]['properties'] if p['property'] == 'extraprostatic_extension')
            self.assertEqual(prop['value']['value'], 'absent')
            self.assertEqual(prop['review_status'], 'accepted')
            self.assertEqual([l['order'] for l in new['lesions']], [1, 2])
