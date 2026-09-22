"""Pipeline: an unavailable RCA must never turn into a remediation proposal."""

from core.pipeline.runner import _fallback_rca, rca_is_actionable
from schemas.rca import RCA


class _Ev:
    def __init__(self, i):
        self.id = i


def _rca(**kw):
    base = dict(
        root_cause="OOMKilled: container exceeded 512Mi limit",
        evidence_ids=["e1"],
        affected_components=["api"],
        alternative_hypotheses=[],
        recommended_action="restart_pod",
        insufficient_evidence=False,
        model="test",
        prompt_version="v1",
    )
    base.update(kw)
    return RCA(**base)


def test_fallback_rca_recommends_no_action():
    rca = _fallback_rca([_Ev("e1")])
    assert rca.root_cause is None
    assert rca.recommended_action is None
    assert rca_is_actionable(rca) is False


def test_valid_rca_is_actionable():
    assert rca_is_actionable(_rca()) is True


def test_insufficient_evidence_is_not_actionable():
    assert rca_is_actionable(_rca(root_cause=None, insufficient_evidence=True)) is False


def test_rca_without_action_is_not_actionable():
    assert rca_is_actionable(_rca(recommended_action=None)) is False
