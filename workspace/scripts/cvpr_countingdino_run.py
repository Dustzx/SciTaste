"""CPU-only CountingDINO reference adapter; no target labels enter inference.

The upstream entry point imports absent src.helpers. We redirect that import to
the same published functions in src.utils, and load a pinned local DINO source
and weights rather than an unpinned torch.hub remote. Counting math is unchanged.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace
import zipfile

os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['XFORMERS_DISABLED'] = '1'

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'outputs/projects/fastresearch-cvpr2027/research/counting/fsc147'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-samples', type=int, default=32)
    args = parser.parse_args()
    assert 1 <= args.max_samples <= 32
    os.chdir(ROOT)
    run = BASE / 'runs/countingdino_vitl14reg_cpu_v1'
    run.mkdir(exist_ok=True)
    source = BASE / 'sources/CountingDINO_archive/CountingDINO-main'
    dino = BASE / 'sources/dinov2_source/dinov2-main'
    weights = BASE / 'sources/dinov2_vitl14_reg4_pretrain.pth'
    receipt = json.loads((BASE / 'sources/DINO_WEIGHT_RECEIPT.json').read_text())
    assert digest(weights) == receipt['sha256']
    ids = json.loads((BASE / 'data/screen_ids.json').read_text())
    inputs = {r['id']: r for r in map(json.loads, (BASE / 'data/development_inputs.jsonl').read_text().splitlines())}
    legal = json.loads((run / 'LEGAL_EXEMPLARS.json').read_text())
    config = dict(divide_et_impera=True, divide_et_impera_twice=True,
                  exemplar_avg=False, cosine_similarity=False, normalize_features=False,
                  normalize_only_biggest_bbox=False, use_threshold=False, use_roi_norm=True,
                  roi_norm_after_mean=True, use_minmax_norm=True, remove_bbox_intersection=False,
                  correct_bbox_resize=True, scaling_coeff=1.0, fixed_norm_coeff=None,
                  filter_background=True, ellipse_normalization=True,
                  ellipse_kernel_cleaning=True, num_exemplars=None)
    protocol = dict(model='dinov2_vitl14_reg', arms=['countingdino'], sample_ids=ids, config=config,
                    countingdino_commit=zipfile.ZipFile(BASE / 'sources/CountingDINO_main.zip').comment.decode(),
                    dinov2_commit=zipfile.ZipFile(BASE / 'sources/dinov2_main.zip').comment.decode(),
                    source_sha256={str(p.relative_to(ROOT)): digest(p) for p in
                                   [source/'convolutional_counting.py', source/'src/model.py',
                                    source/'src/utils.py', Path(__file__), run/'LEGAL_EXEMPLARS.json']},
                    weights=receipt, device='cpu', cpu_threads=8, precision='float32',
                    resize_dim=840, backbone_batch=16,
                    changes=['redirect absent src.helpers import to existing src.utils',
                             'resolve original backbone through pinned local source/weights',
                             'dummy gt_count=0 used only to satisfy return_maps guard; no labels loaded'],
                    information_difference='Original exemplar box locations and full scene feature map; VLM uses 128px reference crops. Auxiliary published-protocol reference, not matched-information/compute control.',
                    scope='Same 32 exposed official-val development groups; no model fitting or parameter selection; not a full FSC test reproduction',
                    confirmation_evaluated=False, license='CountingDINO repository has no root license; local reference only, no redistribution claim. DINOv2 Apache-2.0.')
    if (run / 'PROTOCOL.json').exists():
        assert json.loads((run / 'PROTOCOL.json').read_text()) == protocol
    else:
        save(run / 'PROTOCOL.json', protocol)
    import torch
    import torchvision.transforms as T
    import numpy as np
    torch.set_num_threads(8)
    torch.set_num_interop_threads(1)
    torch.manual_seed(2710)
    assert not torch.cuda.is_available()
    sys.path[:0] = [str(source), str(dino)]
    from src.model import VisualBackbone
    from dinov2.hub.backbones import dinov2_vitl14_reg

    class PinnedBackbone(VisualBackbone):
        def _setup_dino_model(self, model_name):
            assert model_name == 'dinov2_vitl14_reg'
            self.is_vit = self.is_dinov2 = True
            self.feature_extractor = dinov2_vitl14_reg(pretrained=False)
            self.feature_extractor.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True), strict=True)

    raw = (source / 'convolutional_counting.py').read_text()
    assert raw.count('from src.helpers import (') == 1
    patched = raw.replace('from src.helpers import (', 'from src.utils import (')
    (run / 'ENTRY_COMPAT.py').write_text(patched)
    spec = importlib.util.spec_from_file_location('countingdino_reference', run / 'ENTRY_COMPAT.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.device = 'cpu'
    started = time.monotonic()
    model = PinnedBackbone('dinov2_vitl14_reg', img_size=840).to('cpu').eval()
    loaded = time.monotonic() - started
    transform = T.Compose([T.Resize((840, 840), interpolation=T.InterpolationMode.BICUBIC), T.ToTensor(),
                           T.Normalize(mean=(.485,.456,.406), std=(.229,.224,.225))])
    rows = json.loads((run/'PREDICTIONS.json').read_text()) if (run/'PREDICTIONS.json').exists() else []
    assert len({r['id'] for r in rows}) == len(rows)
    completed = {r['id'] for r in rows}
    assert completed <= set(ids)
    save(run/'STATUS.json', dict(state='running', pid=os.getpid(), completed_samples=len(rows),
                                planned_samples=32, model_load_seconds=loaded, local_gpu=False))
    for idx, uid in enumerate(ids[:args.max_samples]):
        if uid in completed:
            continue
        inp = inputs[uid]
        assert inp['partition'] == 'development' and inp['source_split'] == 'val'
        assert digest(ROOT/inp['image']['path']) == inp['image']['sha256']
        t = time.monotonic()
        _, density = module.process_example(idx, inp['source_name'], legal[uid], model, transform,
                                            ['vit_out'], str(BASE/'data/images'), None,
                                            SimpleNamespace(**config), return_maps=True, gt_count=0)
        pred = density.sum().item()
        assert np.isfinite(pred)
        dst = run/f'{uid}_density.npy'
        np.save(dst, density.detach().cpu().numpy())
        row = dict(id=uid, arm='countingdino', image_group=inp['image_group'], answer=pred, valid=True,
                   elapsed_seconds=time.monotonic()-t, density_path=str(dst.relative_to(ROOT)),
                   density_sha256=digest(dst), peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
        rows.append(row)
        save(run/'PREDICTIONS.json', rows)
        save(run/'STATUS.json', dict(state='running', pid=os.getpid(), completed_samples=len(rows),
                                    planned_samples=32, model_load_seconds=loaded, local_gpu=False))
        print(json.dumps({k:v for k,v in row.items() if k not in ['answer','density_path','density_sha256']}), flush=True)
    save(run/'STATUS.json', dict(state='completed_predictions' if len(rows)==32 else 'checkpoint_predictions',
                                completed_samples=len(rows), planned_samples=32, local_gpu=False,
                                model_load_seconds=loaded, elapsed_seconds_this_session=time.monotonic()-started))


if __name__ == '__main__':
    main()
