"""Report-3 behavior at the source-bundle and central interpretation boundaries."""
import copy
import json

import pytest

from central.inputs import load_report
from central.candidates import build_candidates
from central.lesions import build_interpretation, text_sectors
from central.matching import match, observed, location, pair_score
from central_fixtures import write_case


def case(tmp_path):
    report_path, drawing_path = write_case(tmp_path)
    return report_path, json.loads(report_path.read_text()), json.loads(drawing_path.read_text())


def record(report, subject, prop, value):
    obs = next(o for o in report['extraction']['observations'] if o['subject_id'] == subject and o['property'] == prop)
    obs.update(status='recorded', value=value, evidence_ids=['e1'])
    obs.pop('unavailable_reason', None)
    return obs


def presence(value):
    return {'type': 'presence', 'value': value, 'original_wording': 'NE' if value == 'absent' else 'ANO'}


def interpret(report, drawing):
    candidates = build_candidates(drawing)
    return build_interpretation(report, drawing, candidates, match(report, candidates))


def test_report3_accepts_conflicts_without_selecting_a_list_order_winner(tmp_path):
    path, report, drawing = case(tmp_path)
    left = next(o for o in report['extraction']['observations'] if o['id'] == 'f1-laterality')
    right = copy.deepcopy(left)
    right.update(id='opposite-side', value={'type': 'location', 'laterality': 'left', 'original_wording': 'vlevo'})
    report['extraction']['observations'].append(right)
    report['extraction']['issues'].append({'id': 'conflict', 'kind': 'internal_conflict', 'summary': 'Two sides stated.',
        'subject_id': 'f1', 'property': 'laterality', 'observation_ids': [left['id'], right['id']], 'evidence_ids': ['e1']})
    path.write_text(json.dumps(report))
    report = load_report(path)
    assert observed(report, 'f1', 'laterality') is None
    assert location(report, 'f1')['laterality'] == set()
    result = interpret(report, drawing)
    props = [p for p in result['lesions'][0]['properties'] if p['property'] == 'laterality']
    assert len(props) == 1
    assert props[0]['disposition'] == 'unresolved'
    assert {c['value']['laterality'] for c in props[0]['candidates']} == {'right', 'left'}
    assert next(i for i in result['issues'] if i['kind'] == 'internal_conflict')['source_issue']['id'] == 'conflict'


def test_exact_zones_survive_matching_and_text_only_proposals(tmp_path):
    from central.candidates import crosswalk_rows
    _, report, drawing = case(tmp_path)
    record(report, 'f1', 'zone', {'type': 'location', 'zones': ['pzpl'], 'original_wording': 'PZpl'})
    candidates = build_candidates(drawing)
    assert candidates[0]['exact_zones'] == ['pzpl']
    assert pair_score(report, report['extraction']['subjects'][1], candidates[0])[1][2]['outcome'] == 'agreement'
    assert text_sectors(report, 'f1', crosswalk_rows()) == ['pzpl_mid_rs']
    record(report, 'f1', 'zone', {'type': 'location', 'zones': ['pza'], 'original_wording': 'PZa'})
    assert pair_score(report, report['extraction']['subjects'][1], candidates[0])[1][2]['outcome'] == 'conflict'
    assert location(report, 'f1')['anteroposterior'] == {'anterior'}


def test_specimen_negative_is_an_inference_and_preserves_focus_contradiction(tmp_path):
    _, report, drawing = case(tmp_path)
    source = record(report, 'specimen', 'extraprostatic_extension', presence('absent'))
    record(report, 'f1', 'extraprostatic_extension', presence('present'))
    original = copy.deepcopy(report)
    result = interpret(report, drawing)
    assert report == original
    p1 = next(p for p in result['lesions'][0]['properties'] if p['property'] == 'extraprostatic_extension')
    assert p1['disposition'] == 'unresolved'
    assert {c['value']['value'] for c in p1['candidates']} == {'present', 'absent'}
    p2 = next(p for p in result['lesions'][1]['properties'] if p['property'] == 'extraprostatic_extension')
    assert p2['value']['value'] == 'absent'
    assert p2['basis'] == 'inferred' and p2['review_status'] == 'needs_review'
    assert 'report:' + source['id'] in p2['supports']
    assert any(i['kind'] == 'specimen_inference' for i in result['issues'])
    assert any(i['kind'] == 'internal_conflict' for i in result['issues'])


def test_specimen_positive_with_multiple_lesions_has_no_default(tmp_path):
    _, report, drawing = case(tmp_path)
    record(report, 'specimen', 'perineural_invasion', presence('present'))
    result = interpret(report, drawing)
    assert any(i['kind'] == 'specimen_attribution' for i in result['issues'])
    assert all(next(p for p in l['properties'] if p['property'] == 'perineural_invasion')['status'] == 'not reported'
               for l in result['lesions'])


def test_old_contract_refused(tmp_path):
    path, report, _ = case(tmp_path)
    report['extraction']['output_contract_version'] = 'report-2'
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        load_report(path)


def test_total_only_gleason_does_not_invent_patterns(tmp_path):
    path, report, _ = case(tmp_path)
    record(report, 'f1', 'gleason_score', {'type':'gleason_score','total':6,'original_wording':'GS 6'})
    path.write_text(json.dumps(report))
    loaded=load_report(path)
    score=observed(loaded,'f1','gleason_score')['value']
    assert score['total']==6 and score.get('primary_pattern') is None and score.get('secondary_pattern') is None
