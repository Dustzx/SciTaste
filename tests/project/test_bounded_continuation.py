import hashlib
import json

from scitaste.project.bounded_continuation import continuation_decision


def test_continuation_policy_does_not_extend_or_reuse_reserved_budget(tmp_path, monkeypatch):
    import scitaste.project.bounded_continuation as module

    execution = tmp_path / "run"
    (execution / "loop").mkdir(parents=True)
    (execution / "loop/TRAJECTORY.jsonl").write_text("{}\n")
    contract = {
        "plan_sha256": "plan",
        "controller_owner": "scitaste-native",
        "max_turns": 3,
        "execution_api_liability_usd": 6.5,
        "plan": {"resource_envelope": {"wall_seconds": 300}},
    }
    (execution / "CONTRACT.json").write_text(json.dumps(contract))
    result = {
        "controller_owner": "scitaste-native",
        "status": "native-workspace-interrupted",
        "error_type": "JSONDecodeError",
        "duration_seconds": 50,
    }
    (execution / "RESULT.json").write_text(json.dumps(result))
    accounting = {"unresolved_reservations": 0, "liability_usd": 1, "calls": 2}
    monkeypatch.setattr(module, "provider_ledger_accounting", lambda *a: accounting.copy())

    def decide(**kwargs):
        return continuation_decision(execution, plan_sha256="plan", taste_binding=None, **kwargs)

    assert decide()["eligible"] is True
    assert decide()["budget_extension"] is False
    accounting["unresolved_reservations"] = 1
    assert decide()["reason"] == "provider-request-unresolved"
    accounting["unresolved_reservations"] = 0
    accounting["liability_usd"] = 6.5
    assert decide()["reason"] == "execution-api-budget-exhausted"
    accounting["liability_usd"] = 1
    claims = tmp_path / "continuation_claims"
    claims.mkdir()
    child = tmp_path / "owner"
    (claims / (hashlib.sha256(str(execution).encode()).hexdigest() + ".json")).write_text(
        json.dumps({"child": str(child)})
    )
    assert decide()["reason"] == "remaining-budget-already-claimed"
    assert decide(expected_child=child)["eligible"] is True
    result.update(status="controller-finished", score=0)
    (execution / "RESULT.json").write_text(json.dumps(result))
    assert decide(expected_child=child)["eligible"] is False
