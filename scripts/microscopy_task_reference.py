"""Fixed computational restoration controls; no neural fit or scientific novelty."""

import argparse
import json

import numpy as np
from scipy.ndimage import gaussian_filter

METHODS = {"identity": 0.0, "gaussian_half": 0.5, "gaussian_one": 1.0, "oversmooth_two": 2.0}


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads((args.data / "QUERY.json").read_text())
    with np.load(args.data / request["query_file"], allow_pickle=False) as data:
        ids, images = data["fov_id"], data["images"]
    args.output.mkdir(parents=True, exist_ok=False)
    for method, sigma in METHODS.items():
        restored = (
            np.stack([gaussian_filter(image, sigma) for image in images])
            if sigma
            else images.copy()
        )
        filename = f"{request['modality']}--b{request['budget']}--{method}.npz"
        with (args.output / filename).open("xb") as stream:
            np.savez_compressed(stream, fov_id=ids, restored=restored)
    print(json.dumps({"methods": list(METHODS), "fov_count": len(ids), **request}), flush=True)


if __name__ == "__main__":
    main()
