"""One CPU-only exercise of the actual tensor exchange boundary."""

import json

import numpy as np
import pytest

from scitaste.evaluation.unlearning_exchange import (
    IsolatedUnlearningMethod,
    load_tensor_snapshot,
    write_tensor_snapshot,
)


def test_tensor_exchange_and_rejection(tmp_path):
    torch = pytest.importorskip("torch")
    net = torch.nn.Linear(2, 1)

    def launch(replica, seed, original, output):
        assert replica == 0 and seed == 42
        with np.load(original, allow_pickle=False) as archive:
            state = {name: torch.from_numpy(archive[name].copy()) + 1 for name in archive}
        write_tensor_snapshot(output, state)

    before = net.weight.detach().clone()
    method = IsolatedUnlearningMethod(tmp_path / "exchange", launch)
    method.run(net, None, None, None)
    assert torch.equal(net.weight, before + 1)
    assert not net.training
    receipt = json.loads((tmp_path / "exchange/replica-00/RECEIPT.json").read_text())
    assert receipt["candidate_python_imported_in_scorer"] is False
    bad = tmp_path / "bad.npz"
    np.savez(bad, weight=np.zeros((100, 100)), bias=np.zeros(1))
    with pytest.raises(ValueError, match="metadata"):
        load_tensor_snapshot(bad, net.state_dict())
    link = tmp_path / "link.npz"
    link.symlink_to(bad)
    with pytest.raises(OSError):
        load_tensor_snapshot(link, net.state_dict())
