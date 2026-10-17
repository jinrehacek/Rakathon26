"""Semantic report-3 checks shared by the extractor and central loader."""
from .models import PROPERTY_VALUE_TYPES

FOCUS_PROPERTIES = frozenset("reported_label dominant laterality level zone anteroposterior textual_location dimensions gleason_patterns gleason_score grade_group extraprostatic_extension perineural_invasion histology_type".split())
SPECIMEN_PROPERTIES = frozenset("classification_pt classification_pn classification_pm classification_r classification_l classification_v grade_group reported_lesion_count multifocality histology icd_o seminal_vesicle_invasion extraprostatic_extension perineural_invasion procedure lymph_nodes_examined lymph_nodes_positive conclusion_text".split())
OTHER_PROPERTIES = frozenset("finding_type laterality level zone textual_location".split())
REQUIRED_PROPERTIES = {"specimen": SPECIMEN_PROPERTIES, "tumour_focus": FOCUS_PROPERTIES, "other_finding": OTHER_PROPERTIES}
ALLOWED_PROPERTIES = {**REQUIRED_PROPERTIES, "specimen": SPECIMEN_PROPERTIES | {"gleason_patterns", "gleason_score"}}
LOCATION_COMPONENTS = {"laterality": "laterality", "level": "levels", "zone": "zones", "anteroposterior": "anteroposterior", "textual_location": "description"}
CODE_DOMAINS = {"grade_group": {"1", "2", "3", "4", "5"}, "histology_type": set("1234567"),
                "histology": set("123456"), "multifocality": {"multifocal", "unifocal"}}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _index(items, label):
    result = {}
    for item in items:
        _require(item.id and item.id not in result, f"empty or duplicate {label} ID: {item.id}")
        result[item.id] = item
    return result


def _refs(refs, index, label):
    _require(len(refs) == len(set(refs)), f"duplicate {label} reference")
    _require(all(ref in index for ref in refs), f"missing {label} reference")


def _acyclic(graph, label):
    done, active = set(), set()
    def visit(node):
        _require(node not in active, f"{label} cycle")
        if node in done:
            return
        active.add(node)
        for child in graph.get(node, ()):
            visit(child)
        active.remove(node)
        done.add(node)
    for node in graph:
        visit(node)


def validate_content(layer, extraction):
    evidence = _index(extraction.evidence, "evidence")
    subjects = _index(extraction.subjects, "subject")
    observations = _index(extraction.observations, "observation")
    _index(extraction.coverage, "coverage")
    _index(extraction.issues, "issue")
    all_ids = [x.id for collection in
               (extraction.evidence, extraction.subjects, extraction.observations, extraction.coverage, extraction.issues) for x in collection]
    _require(len(all_ids) == len(set(all_ids)), "duplicate report ID across collections")
    for anchor in evidence.values():
        _require(anchor.text_layer_id == layer.id, "evidence text layer identity mismatch")
        _require(anchor.quotation is None or (anchor.start_offset < anchor.end_offset <= len(layer.text)
                 and layer.text[anchor.start_offset:anchor.end_offset] == anchor.quotation),
                 "evidence quotation does not match exact code-point offsets")
        if anchor.image_region:
            region = anchor.image_region
            _require(layer.input_kind == "image" and region.x + region.width <= layer.image_width
                     and region.y + region.height <= layer.image_height, "evidence image region outside source")
    specimens = [s for s in subjects.values() if s.kind == "specimen"]
    _require(len(specimens) == 1, "report requires exactly one specimen")
    specimen = specimens[0]
    for subject in subjects.values():
        _require(subject.kind in REQUIRED_PROPERTIES, "unsupported report-3 subject kind")
        _refs(subject.evidence_ids, evidence, "subject evidence")
        if subject.kind == "specimen":
            _require(subject.parent_id is None, "specimen cannot have a parent")
        else:
            _require(subject.parent_id == specimen.id, "finding must belong to the specimen")
            _require(subject.identification_basis == "explicit", "report findings must be explicit")
    _acyclic({s.id: [s.parent_id] if s.parent_id else [] for s in subjects.values()}, "subject containment")
    coverage = set()
    for check in extraction.coverage:
        _require(check.subject_id in subjects, "coverage references missing subject")
        _require(check.property in ALLOWED_PROPERTIES[subjects[check.subject_id].kind], "coverage property outside subject scope")
        _require(check.checked and check.source_complete and bool(check.rationale.strip()), "incomplete property coverage")
        pair = (check.subject_id, check.property)
        _require(pair not in coverage, "duplicate property coverage")
        coverage.add(pair)
    seen = set()
    pairs = {}
    for obs in observations.values():
        _require(obs.subject_id in subjects, "observation references missing subject")
        _require(obs.property in ALLOWED_PROPERTIES[subjects[obs.subject_id].kind], "observation property outside subject scope")
        _refs(obs.evidence_ids, evidence, "observation evidence")
        _refs(obs.derived_from, observations, "derived observation")
        pair = (obs.subject_id, obs.property)
        pairs.setdefault(pair, []).append(obs)
        seen.add(pair)
        if obs.status == "recorded":
            _require(any(evidence[eid].quotation is not None for eid in obs.evidence_ids), "recorded value requires anchored text evidence")
        if obs.status == "not reported":
            _require((obs.subject_id, obs.property) in coverage, "not reported requires complete coverage")
        value = obs.value
        if value is None:
            continue
        if obs.property in LOCATION_COMPONENTS:
            component = LOCATION_COMPONENTS[obs.property]
            _require(getattr(value, component) not in (None, "", ()), "location lacks its property component")
            _require(all(getattr(value, other) is None for other in LOCATION_COMPONENTS.values() if other != component),
                     "location sets another property's component")
            for items in (value.levels, value.zones):
                if items:
                    _require(len(items) == len(set(items)), "duplicate location component")
        if obs.property == "gleason_patterns":
            _require(value.primary is not None and value.secondary is not None, "report-3 requires nested Gleason patterns")
        if obs.property in CODE_DOMAINS:
            _require(value.code in CODE_DOMAINS[obs.property], f"invalid {obs.property} code")
        if obs.property in {"histology_type", "histology", "multifocality"}:
            _require(bool(value.original_wording), "coded finding requires original wording")
        if obs.property in {"reported_lesion_count", "lymph_nodes_examined", "lymph_nodes_positive"}:
            _require(value.value.is_integer() and value.unit is None and not value.approximate,
                     "reported lesion count must be an explicit unitless integer")
    _acyclic({o.id: o.derived_from for o in observations.values()}, "observation derivation")
    for subject in subjects.values():
        _require(all((subject.id, prop) in seen for prop in REQUIRED_PROPERTIES[subject.kind]),
                 f"missing required property observation for {subject.id}")
    for issue in extraction.issues:
        _refs(issue.evidence_ids, evidence, "issue evidence")
        _refs(issue.alternative_subject_ids, subjects, "issue alternative subject")
        if issue.subject_id:
            _require(issue.subject_id in subjects, "issue references missing subject")
        _refs(issue.observation_ids, observations, "issue observation")
        if issue.image_region:
            region = issue.image_region
            _require(layer.input_kind == "image" and region.x + region.width <= layer.image_width
                     and region.y + region.height <= layer.image_height, "issue image region outside source")
        if issue.kind == "internal_conflict":
            expected = {o.id for o in pairs.get((issue.subject_id, issue.property), [])}
            _require(set(issue.observation_ids) == expected, "internal conflict must reference every conflicting observation")
            _require(all(o.status == "recorded" for o in pairs.get((issue.subject_id, issue.property), [])),
                     "conflict alternatives must be recorded")
            _require(all(set(observations[oid].evidence_ids) <= set(issue.evidence_ids) for oid in expected),
                     "internal conflict must retain each value's evidence")
        if issue.kind == "ocr_disagreement":
            _require(any(evidence[eid].quotation is not None for eid in issue.evidence_ids), "OCR disagreement requires OCR evidence")
        if issue.kind == "unanchored_evidence":
            _require(any(o.status == "unreadable" for o in pairs.get((issue.subject_id, issue.property), [])),
                     "unanchored property must be unreadable")
            _require(issue.proposed_value.type in PROPERTY_VALUE_TYPES[issue.property],
                     "unanchored proposal type does not match property")
        if issue.kind == "ambiguous_evidence":
            spans = [(span.start_offset, span.end_offset) for span in issue.candidate_spans]
            _require(spans == sorted(set(spans)) and all(end <= len(layer.text) for start, end in spans), "invalid ambiguous evidence spans")
            selected = issue.selected_span
            _require(any(evidence[eid].start_offset == selected.start_offset and evidence[eid].end_offset == selected.end_offset
                         for eid in issue.evidence_ids), "selected evidence span is not anchored")
    for pair, alternatives in pairs.items():
        if len(alternatives) > 1:
            _require(any(issue.kind == "internal_conflict" and (issue.subject_id, issue.property) == pair
                         for issue in extraction.issues), "duplicate subject property requires an internal_conflict issue")
