"""Synthetic OCR/model responses exercise the same publisher central consumes."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from central.inputs import load_report
from central.pipeline import run_case
from central_fixtures import write_case
from report_extractor.anchoring import quotation_spans
from report_extractor.gemini import GeminiExtractor
from report_extractor.models import TextLayer
from report_extractor.pipeline import run_extraction

REGION = {'x': 1, 'y': 2, 'width': 10, 'height': 10}


def prepared(tmp_path):
    path, _ = write_case(tmp_path)
    report = json.loads(path.read_text())
    source = Path(report['document']['source_path'])
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'\xff\xd8synthetic image for injected transport')
    layer = TextLayer.model_validate({**report['text_layer'], 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'input_kind': 'image', 'extraction_method': 'tesseract', 'tool': 'synthetic-tsv', 'language': 'ces',
        'image_width': 100, 'image_height': 100})
    payload = {key: copy.deepcopy(report['extraction'][key]) for key in ('evidence','subjects','coverage','observations','issues')}
    payload['source_text_sha256'] = layer.text_sha256
    payload['evidence'] = [{'id': 'e1', 'quotation': 'Syntetický vzorek.', 'image_region': REGION},
        {'id':'focus-first', 'quotation':'Ložisko A', 'image_region':REGION},
        {'id':'focus-second', 'quotation':'Ložisko B', 'image_region':REGION}]
    for subject in payload['subjects']:
        if subject['id']=='f1': subject['evidence_ids']=['focus-first']
        if subject['id']=='f2': subject['evidence_ids']=['focus-second']
    payload['subjects'].reverse()
    return path, layer, {'handwriting': [], 'extraction': payload}


def response(payload):
    return {'candidates': [{'finishReason':'STOP', 'content': {'parts':[{'text':json.dumps(payload)}]}}]}


def test_combined_call_publishes_report3_and_central_pins_exact_run(tmp_path):
    path, layer, raw = prepared(tmp_path)
    raw['handwriting']=[{'image_region':REGION,'explanation':'Synthetic handwritten annotation.'}]
    raw['extraction']['issues']=[{'id':'ocr-note','kind':'ocr_disagreement','summary':'Image reading differs.',
        'evidence_ids':['e1'],'image_region':REGION,'image_reading':'Alternate image reading'}]
    calls=[]
    def transport(body,key):
        calls.append(body)
        return response(raw)
    run=run_extraction(layer,GeminiExtractor(key='synthetic-key',transport=transport),path.parent)
    bundle=load_report(path)
    assert len(calls)==1
    assert calls[0]['generationConfig']['temperature']==0
    assert calls[0]['generationConfig']['thinkingConfig']=={'thinkingLevel':'low'}
    assert len([p for p in calls[0]['contents'][0]['parts'] if 'inlineData' in p])==1
    assert bundle['extraction']['model_id']=='gemini-3.8-flash'
    assert [s['id'] for s in bundle['extraction']['subjects']]==['specimen','focus-a','focus-b']
    assert next(o for o in bundle['extraction']['observations'] if o['id']=='f1-laterality')['subject_id']=='focus-a'
    assert bundle['text_layer']['text']==layer.text
    assert path.is_symlink() and path.resolve()==run/'report.json'
    assert sorted(p.name for p in run.iterdir())==['report.json','result.json','review.html','text-layer.json']
    combined=json.loads(run_case('synthetic-case',root=tmp_path,use_llm=False).read_text())
    assert combined['inputs']['report']['path']==str(run/'report.json')
    assert combined['inputs']['report']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert {'handwriting_present','ocr_disagreement'} <= {i['kind'] for i in combined['issues']}


def test_invalid_value_gets_one_retry_with_immutable_inputs(tmp_path):
    path, layer, raw = prepared(tmp_path)
    invalid=copy.deepcopy(raw)
    invalid['extraction']['observations'][0]['property']='unknown-property'
    calls=[]
    def transport(body,key):
        calls.append(body)
        return response(invalid if len(calls)==1 else raw)
    run=run_extraction(layer,GeminiExtractor(key='key',transport=transport),path.parent)
    assert len(calls)==2
    assert calls[0]['contents'][0]['parts']==calls[1]['contents'][0]['parts'][:-1]
    assert 'Validation errors' in calls[1]['contents'][0]['parts'][-1]['text']
    assert load_report(run/'report.json')['extraction']['complete'] is True


def test_failed_retry_keeps_previous_complete_link_and_quarantine(tmp_path):
    path, layer, raw = prepared(tmp_path)
    run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    previous=path.resolve()
    invalid=copy.deepcopy(raw)
    invalid['extraction']['observations'][0]['property']='unknown-property'
    calls=[]
    def transport(body,key):
        calls.append(body)
        return response(invalid)
    failed=run_extraction(layer,GeminiExtractor(key='key',transport=transport),path.parent)
    bundle=json.loads((failed/'report.json').read_text())
    assert len(calls)==2
    assert not bundle['extraction']['complete'] and bundle['quarantine'] and bundle['validation_errors']
    assert path.resolve()==previous
    with pytest.raises(ValueError): load_report(failed/'report.json')


def test_unanchored_value_is_unreadable_with_proposal_only_in_issue(tmp_path):
    path, layer, raw = prepared(tmp_path)
    raw['extraction']['evidence'].append({'id':'not-in-ocr','quotation':'not present in OCR','image_region':REGION})
    obs=next(o for o in raw['extraction']['observations'] if o['id']=='f1-laterality')
    obs['evidence_ids']=['not-in-ocr']
    run=run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    bundle=load_report(run/'report.json')
    obs=next(o for o in bundle['extraction']['observations'] if o['id']=='f1-laterality')
    assert obs['status']=='unreadable' and obs['value'] is None
    issue=next(i for i in bundle['extraction']['issues'] if i['kind']=='unanchored_evidence')
    assert issue['proposed_value']['laterality']=='right' and issue['subject_id']=='focus-a'
    anchor=next(e for e in bundle['extraction']['evidence'] if e['id']=='not-in-ocr')
    assert anchor['quotation'] is None and anchor['start_offset'] is None


def test_missing_image_context_fails_instead_of_inventing_offsets(tmp_path):
    path, layer, raw = prepared(tmp_path)
    raw['extraction']['evidence'].append({'id':'bad','quotation':'not present'})
    next(o for o in raw['extraction']['observations'] if o['id']=='f1-laterality')['evidence_ids']=['bad']
    run=run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    assert not json.loads((run/'report.json').read_text())['extraction']['complete']
    assert not path.is_symlink()


def test_whitespace_matching_uses_original_unicode_offsets_and_flags_repetition(tmp_path):
    assert quotation_spans('Žluťoučký\n  kůň', 'Žluťoučký kůň')==[{'start_offset':0,'end_offset':15}]
    path, layer, raw=prepared(tmp_path)
    raw['extraction']['evidence'][0]['quotation']='Ložisko'
    raw['extraction']['evidence'][0]['start_offset']=999  # Model offsets have no authority.
    run=run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    bundle=load_report(run/'report.json')
    issue=next(i for i in bundle['extraction']['issues'] if i['kind']=='ambiguous_evidence')
    assert len(issue['candidate_spans'])==2
    for anchor in bundle['extraction']['evidence']:
        if anchor['quotation'] is not None:
            assert layer.text[anchor['start_offset']:anchor['end_offset']]==anchor['quotation']


def test_transport_or_parse_failure_cannot_publish_complete_output(tmp_path):
    path, layer, raw=prepared(tmp_path)
    calls=[]
    def transport(body,key):
        calls.append(body)
        return {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'secret raw content'}]}}]}
    run=run_extraction(layer,GeminiExtractor(key='key',transport=transport),path.parent)
    assert len(calls)==2
    serialized=(run/'report.json').read_text()
    assert not json.loads(serialized)['extraction']['complete']
    assert 'secret raw content' not in serialized


def test_manual_probe_is_preserved_before_live_link_publication(tmp_path):
    path, layer, raw = prepared(tmp_path)
    original=path.read_bytes()
    run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    reference=tmp_path/'Other/output/central-eval/synthetic-case/report-reference.json'
    assert reference.read_bytes()==original
    assert (reference.parent/'report-reference-original.json').read_bytes()==original
    assert path.is_symlink()


def test_image_only_evidence_cannot_support_a_recorded_value(tmp_path):
    path, layer, raw=prepared(tmp_path)
    raw['extraction']['evidence'].append({'id':'image-only','image_region':REGION})
    next(o for o in raw['extraction']['observations'] if o['id']=='f1-laterality')['evidence_ids']=['image-only']
    run=run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    data=json.loads((run/'report.json').read_text())
    assert not data['extraction']['complete']
    assert 'anchored text evidence' in ' '.join(data['validation_errors'])


def test_invalid_issue_payload_and_old_contract_never_replace_good_output(tmp_path):
    path, layer, raw=prepared(tmp_path)
    raw['extraction']['issues']=[{'id':'bad-issue','kind':'ocr_disagreement','summary':'Missing image reading.',
        'evidence_ids':['e1'],'image_region':REGION}]
    run=run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    bundle=json.loads((run/'report.json').read_text())
    assert not bundle['extraction']['complete'] and any(i['item_type']=='issue' for i in bundle['quarantine'])


def test_source_order_can_use_a_subjects_anchored_observation(tmp_path):
    path,layer,raw=prepared(tmp_path)
    raw['extraction']['evidence'][1]['quotation']='unanchored identification reading'
    raw['extraction']['evidence'].append({'id':'grounded-first','quotation':'vpravo','image_region':REGION})
    for obs in raw['extraction']['observations']:
        if obs['subject_id']=='f1' and obs['status']=='recorded':obs['evidence_ids']=['grounded-first']
    run=run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    bundle=load_report(run/'report.json')
    assert [s['id'] for s in bundle['extraction']['subjects']]==['specimen','focus-a','focus-b']
    assert next(o for o in bundle['extraction']['observations'] if o['id']=='f1-laterality')['subject_id']=='focus-a'


def test_model_cannot_claim_doctor_review(tmp_path):
    path,layer,raw=prepared(tmp_path)
    for obs in raw['extraction']['observations']:obs['review_status']='accepted'
    run=run_extraction(layer,GeminiExtractor(key='key',transport=lambda b,k:response(raw)),path.parent)
    bundle=load_report(run/'report.json')
    assert {o['review_status'] for o in bundle['extraction']['observations']}=={'unreviewed'}


def test_provider_schema_uses_enum_discriminators():
    from report_extractor.gemini import response_schema
    schema=response_schema()
    assert schema['$defs']['CodedValue']['properties']['type']['enum']==['coded']
    encoded=json.dumps(schema)
    assert '"const"' not in encoded and '"oneOf"' not in encoded
