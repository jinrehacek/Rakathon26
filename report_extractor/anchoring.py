"""Turn model quotations into immutable transcript anchors and assign source-ordered IDs."""
from __future__ import annotations

from copy import deepcopy

from .models import TextLayer


def quotation_spans(text: str, quotation: str) -> list[dict]:
    if not isinstance(quotation, str) or not quotation.strip():
        return []

    def find_all(haystack, needle):
        start = 0
        while (start := haystack.find(needle, start)) >= 0:
            yield start, start + len(needle)
            start += 1

    spans = list(find_all(text, quotation))
    if not spans:
        indices = [i for i, char in enumerate(text) if not char.isspace()]
        compact = ''.join(text[i] for i in indices)
        needle = ''.join(char for char in quotation if not char.isspace())
        spans = [(indices[start], indices[end - 1] + 1) for start, end in find_all(compact, needle)]
    return [{'start_offset': start, 'end_offset': end} for start, end in spans]


def anchor_response(response: dict, layer: TextLayer) -> dict:
    if not isinstance(response, dict) or set(response) != {'handwriting', 'extraction'}:
        raise ValueError('Response requires handwriting and extraction.')
    if not isinstance(response['handwriting'], list):
        raise ValueError('Handwriting must be an array.')
    payload = deepcopy(response['extraction'])
    if payload.get('source_text_sha256') != layer.text_sha256:
        raise ValueError('Response is bound to different source text.')
    evidence = payload['evidence']
    issues = payload['issues']
    observations = payload['observations']
    # Generated IDs are reserved against every model-supplied collection.
    used = {item['id'] for key in ('evidence', 'subjects', 'coverage', 'observations', 'issues') for item in payload[key]}

    def new_id(prefix):
        number = 1
        while f'{prefix}-{number}' in used:
            number += 1
        ident = f'{prefix}-{number}'
        used.add(ident)
        return ident

    failed = {}
    ambiguous = {}
    for anchor in evidence:
        anchor['text_layer_id'] = layer.id
        quote = anchor.get('quotation')
        if quote is None:
            anchor.pop('start_offset', None)
            anchor.pop('end_offset', None)
            continue
        spans = quotation_spans(layer.text, quote)
        if spans:
            span = spans[0]
            anchor.update(span)
            anchor['quotation'] = layer.text[span['start_offset']:span['end_offset']]
            if len(spans) > 1:
                ambiguous[anchor['id']] = spans
        else:
            failed[anchor['id']] = quote
            anchor['quotation'] = None
            anchor.pop('start_offset', None)
            anchor.pop('end_offset', None)

    anchor_index = {a['id']: a for a in evidence}
    for obs in observations:
        obs['review_status'] = 'unreviewed'
        refs = obs.get('evidence_ids', [])
        unavailable = [ref for ref in refs if ref in failed]
        if unavailable and obs.get('status') == 'recorded':
            proposed = obs.pop('value')
            # Failed quotation evidence stays image-only, never a selected value.
            for ref in unavailable:
                issues.append({'id': new_id('unanchored'), 'kind': 'unanchored_evidence',
                    'summary': 'Proposed value could not be anchored in transcript.',
                    'subject_id': obs['subject_id'], 'property': obs['property'],
                    'proposed_value': proposed, 'proposed_quotation': failed[ref],
                    'failure_reason': 'No exact or whitespace-insensitive quotation match.',
                    'image_region': anchor_index[ref].get('image_region'), 'evidence_ids': [ref]})
            obs.update(status='unreadable', unavailable_reason='Proposed quotation is not in the immutable transcript.')
        for ref in refs:
            if ref in ambiguous:
                issues.append({'id': new_id('ambiguous'), 'kind': 'ambiguous_evidence',
                    'summary': 'Quotation occurs more than once; review the first source span.',
                    'subject_id': obs['subject_id'], 'property': obs['property'], 'evidence_ids': [ref],
                    'candidate_spans': ambiguous[ref], 'selected_span': ambiguous[ref][0]})

    for item in response['handwriting']:
        region = item['image_region']
        eid = new_id('handwriting-image')
        evidence.append({'id': eid, 'text_layer_id': layer.id, 'image_region': region})
        issues.append({'id': new_id('handwriting'), 'kind': 'handwriting_present',
                       'summary': item['explanation'], 'evidence_ids': [eid], 'image_region': region})

    def source_order(subject):
        anchors = [anchor_index[ref] for ref in subject['evidence_ids']]
        offsets = [a['start_offset'] for a in anchors if a.get('start_offset') is not None]
        if not offsets:
            supporting = [ref for obs in observations if obs['subject_id'] == subject['id']
                          for ref in obs.get('evidence_ids', [])
                          if ref in anchor_index and anchor_index[ref].get('start_offset') is not None]
            if supporting:
                first = min(supporting, key=lambda ref: anchor_index[ref]['start_offset'])
                subject['evidence_ids'].append(first)
                offsets = [anchor_index[first]['start_offset']]
            else:
                # Guessing IDs from response order would break saved review targets.
                raise ValueError(f"Subject {subject['id']} requires anchored source-order evidence.")
        return min(offsets)

    def letters(number):
        result = ''
        while number >= 0:
            result = chr(97 + number % 26) + result
            number = number // 26 - 1
        return result

    subjects = payload['subjects']
    mapping = {}
    for kind, prefix in (('specimen', 'specimen'), ('tumour_focus', 'focus'), ('other_finding', 'other')):
        ordered = sorted((s for s in subjects if s['kind'] == kind), key=source_order)
        positions = [source_order(s) for s in ordered]
        if len(positions) != len(set(positions)):
            raise ValueError('Subjects of the same kind require distinct first-appearance anchors.')
        for number, subject in enumerate(ordered):
            mapping[subject['id']] = 'specimen' if kind == 'specimen' and number == 0 else f'{prefix}-{letters(number)}'
    for subject in subjects:
        subject['id'] = mapping.get(subject['id'], subject['id'])
        if subject.get('parent_id'):
            subject['parent_id'] = mapping.get(subject['parent_id'], subject['parent_id'])
    for item in payload['observations'] + payload['coverage'] + issues:
        if item.get('subject_id'):
            item['subject_id'] = mapping.get(item['subject_id'], item['subject_id'])
        if 'alternative_subject_ids' in item:
            item['alternative_subject_ids'] = [mapping.get(ref, ref) for ref in item['alternative_subject_ids']]
    # Subject array follows source order too; observation IDs remain model-local references.
    payload['subjects'] = sorted(subjects, key=lambda s: (s['kind'] != 'specimen', source_order(s)))
    return payload
