"""Qualitative certainty with explanations and source dependence retained."""
from .rules import HIGH_MARGIN, MEDIUM_MARGIN, SEVERE_SIGNALS


def matching_confidence(best: float, runner_up: float | None, explicit: bool) -> str:
    # No competing assignment exists when there are no report foci.
    if runner_up is None:
        return "high" if explicit else "medium"
    margin = best - runner_up
    if margin >= HIGH_MARGIN and explicit:
        return "high"
    if margin >= MEDIUM_MARGIN:
        return "medium"
    return "low"


def confidence(level: str, explanation: str) -> dict:
    return {"rules": level, "final": level, "explanations": [explanation]}


def text_confidence(observation: dict) -> dict:
    certainty = observation.get("certainty", {})
    levels = [certainty.get("extraction", "unassessed"), certainty.get("interpretation", "unassessed")]
    rank = {"unassessed": 0, "low": 1, "medium": 2, "high": 3}
    level = min(levels, key=lambda item: rank[item])
    result = confidence(level, certainty.get("explanation") or "Retained report certainty; the drawing provides no independent confirmation.")
    result["source_certainty"] = dict(certainty)
    return result


def sector_confidence(matching: str, side_agrees: bool, explicit: bool,
                      signals: list[dict], conflict: bool = False, text_only: bool = False) -> dict:
    if conflict:
        return confidence("conflict", "Report and drawing disagree on side or anteroposterior location; both source values are retained.")
    if text_only:
        return confidence("low", "Sectors are inferred from report location without matched drawing evidence.")
    if matching == "low" or any(signal["kind"] in SEVERE_SIGNALS for signal in signals):
        return confidence("low", "Assignment ambiguity or a drawing disagreement limits the sector set.")
    severe_flag = any(signal.get("suggestion") == "would flag" for signal in signals)
    if matching == "high" and side_agrees and explicit and not signals:
        return confidence("high", "High matching certainty, explicit orientation and agreeing report side support the sectors.")
    if matching == "high" and side_agrees and explicit and not severe_flag:
        return confidence("medium" if signals else "high", "Side agrees; drawing signals limit confidence.")
    if severe_flag:
        return confidence("low", "A drawing signal would flag a contributing mark for review.")
    return confidence("medium", "Orientation, matching certainty or single-source location limits confidence; agreement is not independent verification.")
