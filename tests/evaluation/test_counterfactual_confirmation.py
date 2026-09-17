from scitaste.evaluation.counterfactual_confirmation import (
    _exact_two_sided_sign_test,
    _exhaustive_cluster_bootstrap,
)


def test_exhaustive_cluster_bootstrap_and_sign_test_are_deterministic() -> None:
    interval, samples = _exhaustive_cluster_bootstrap((1.0, -1.0))

    assert samples == 4
    assert interval == (-1.0, 1.0)
    assert _exact_two_sided_sign_test(1, 2) == 1.0
    assert _exact_two_sided_sign_test(0, 0) is None
