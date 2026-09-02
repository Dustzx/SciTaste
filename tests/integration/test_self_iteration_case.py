from __future__ import annotations

from scitaste.discovery.loop import DiscoveryLoop, load_discovery_scenario


def test_self_iteration_selects_external_adapter_without_forking(tmp_path) -> None:
    scenario = load_discovery_scenario("configs/cases/scitaste_phase75_self_iteration.yaml")

    summary = DiscoveryLoop(seed=7).run(scenario, output_dir=tmp_path / "self-iteration")

    assert summary["primary_idea_id"] == "idea-01-system-level"
    assert summary["probe_count"] == 1
    assert summary["final_stage"] == "PILOT"
