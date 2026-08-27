import unittest

from app.analytics.classifier import (
    CandidateState,
    candidate_state,
    confirm_candidate_history,
    evidence_strength,
)


class ClassifierTests(unittest.TestCase):
    def test_candidate_rule_priority_and_turning_direction(self) -> None:
        self.assertEqual(
            candidate_state(0.02, -0.005),
            CandidateState("turning", "weak_to_strong"),
        )
        self.assertEqual(
            candidate_state(-0.02, 0.005),
            CandidateState("turning", "strong_to_weak"),
        )
        self.assertEqual(candidate_state(0.02, 0.01).code, "up")
        self.assertEqual(candidate_state(-0.02, -0.01).code, "down")
        self.assertEqual(candidate_state(0.005, 0.002).code, "sideways")

    def test_exact_one_percent_does_not_cross_strict_directional_thresholds(self) -> None:
        self.assertEqual(candidate_state(0.01, 0.005).code, "sideways")
        self.assertEqual(candidate_state(-0.01, -0.005).code, "sideways")

    def test_confirmation_requires_two_equal_candidates_and_retains_prior_confirmation(self) -> None:
        history = [CandidateState("up", ""), CandidateState("up", "")]
        result = confirm_candidate_history(history)
        self.assertEqual(result.confirmed, "up")
        self.assertFalse(result.pending)

        pending = confirm_candidate_history(history + [CandidateState("down", "")])
        self.assertEqual(pending.confirmed, "up")
        self.assertTrue(pending.pending)

        opposite_turns = confirm_candidate_history([
            CandidateState("turning", "weak_to_strong"),
            CandidateState("turning", "strong_to_weak"),
        ])
        self.assertIsNone(opposite_turns.confirmed)
        self.assertTrue(opposite_turns.pending)

    def test_evidence_quality_and_interval_caps(self) -> None:
        high = dict(
            confirmed=True,
            periods=12,
            directional_agreement=True,
            supporting_signal=True,
            has_quality_issue=False,
            has_irregular_interval=False,
        )
        self.assertEqual(evidence_strength(**high), "high")
        self.assertEqual(evidence_strength(**(high | {"has_irregular_interval": True})), "medium")
        self.assertEqual(evidence_strength(**(high | {"has_quality_issue": True})), "low")
        self.assertEqual(evidence_strength(**(high | {"confirmed": False})), "low")
        self.assertEqual(evidence_strength(**(high | {"periods": 8})), "medium")
