from __future__ import annotations

from dataclasses import dataclass

RULE_VERSION = "trend-v1"


@dataclass(frozen=True)
class CandidateState:
    code: str
    detail: str


@dataclass(frozen=True)
class Confirmation:
    confirmed: str | None
    confirmed_detail: str
    candidate: str
    candidate_detail: str
    pending: bool


def candidate_state(r4: float, r8: float) -> CandidateState:
    if r4 * r8 < 0 and abs(r4 - r8) >= 0.01:
        detail = "weak_to_strong" if r4 > 0 else "strong_to_weak"
        return CandidateState("turning", detail)
    if r4 > 0.01 and r8 > 0:
        return CandidateState("up", "")
    if r4 < -0.01 and r8 < 0:
        return CandidateState("down", "")
    return CandidateState("sideways", "")


def confirm_candidate_history(history: list[CandidateState]) -> Confirmation:
    confirmed: CandidateState | None = None
    for index in range(1, len(history)):
        if history[index] == history[index - 1]:
            confirmed = history[index]
    current = history[-1]
    pending = len(history) < 2 or history[-2] != current
    return Confirmation(
        confirmed.code if confirmed else None,
        confirmed.detail if confirmed else "",
        current.code,
        current.detail,
        pending,
    )


def evidence_strength(
    *,
    confirmed: bool,
    periods: int,
    directional_agreement: bool,
    supporting_signal: bool,
    has_quality_issue: bool,
    has_irregular_interval: bool,
) -> str:
    if not confirmed or has_quality_issue:
        return "low"
    strength = "medium"
    if periods >= 12 and directional_agreement and supporting_signal:
        strength = "high"
    return "medium" if has_irregular_interval and strength == "high" else strength
