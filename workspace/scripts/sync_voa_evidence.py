#!/usr/bin/env python3
"""Project accepted, small VOA evidence into the local SciTaste UI. No inference.

Only explicit summaries and review assets are read. Source experiments, closed
TEST data, model weights and annotations are never modified or copied.
"""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
VOA = Path('/home/good/zfx/papers/VOA')
REPORTS = VOA / 'voa_perceptual_20260927_v1/reports'
DEST = ROOT / 'web/assets/projects/voa'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    sources = []

    def source(path, name, key):
        target = DEST / 'evidence' / (key + path.suffix)
        target.parent.mkdir(exist_ok=True)
        # Explicit small evidence only; never broaden this to recursive sync.
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f'Not a small reviewed artifact: {path.name}')
        shutil.copyfile(path, target)
        sources.append({'id': key, 'label': name, 'locator': str(path.relative_to(VOA)),
                        'sha256': digest(path), 'url': '/assets/projects/voa/evidence/' + target.name,
                        'modified_at': datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo('Asia/Shanghai')).isoformat()})
        return json.loads(path.read_text()) if path.suffix == '.json' else None

    test = source(REPORTS/'fresh_test_v81_eval/SUMMARY.json', 'v82 · 新独立500 TEST汇总（v81评测）', 'independent500')
    dev = source(REPORTS/'onpolicy_binding_v82/SUMMARY.json', 'v82 · 暴露DEV200与训练验收', 'v82')
    count = source(REPORTS/'count_binding_v86_recovery1/SUMMARY.json', 'v86 · 数量分层四臂终点', 'v86')
    prompt = source(REPORTS/'count_prompt_control_v87/SUMMARY.json', 'v87 · 同模板双／三目标诊断', 'v87')
    decode = source(REPORTS/'count_decoding_v90/SUMMARY.json', 'v90 · 零更新解码诊断', 'v90')
    s1 = source(REPORTS/'all_S1_targets_v79/SUMMARY.json', 'v79 · S1任务／S2末自由评测', 's1')
    source(VOA/'report/VOA_GROUP_MEETING.md', '研究主文档 · idea、近邻与当前决策', 'main')
    source(VOA/'voa_perceptual_20260927_v1/docs/experiment.md', '详细方法实现', 'method')
    cases = source(VOA/'report/assets/v82_cases/CASES.json', '六类真实DEV案例与选择规则', 'cases')
    source(VOA/'report/assets/v82_cases/METHOD_AUDIT.json', '参数及训练配置审核', 'method-audit')
    # CASES is already a small review export, not raw annotations/attention tensors.
    image_names = set()
    for case in cases['cases']:
        image_names.add(case['image'])
        for model in case['models'].values():
            image_names.update(p['file'] for p in model['panels'])
            image_names.update(f['panel'] for f in model.get('followups', []))
    (DEST/'cases').mkdir(exist_ok=True)
    for name in sorted(image_names):
        if Path(name).name != name or not name.endswith('.jpg'):
            raise ValueError('Unsafe review image name')
        shutil.copyfile(VOA/'report/assets/v82_cases'/name, DEST/'cases'/name)
    for name in ['voa_v82_method.svg', 'voa_v82_independent500.svg', 'voa_v82_independent500.csv']:
        shutil.copyfile(VOA/'report/assets'/name, DEST/name)

    def table(columns, rows):
        return {'columns': columns, 'rows': rows}

    def chart(title, labels, series):
        return {'title': title, 'labels': labels, 'series': [{'name': n, 'values': v} for n, v in series]}

    tm = test['metrics']
    test_rows = []
    for name, key in [('strong v40 · 强起点', 'strong'), ('规范目标接续 · +4096', 'matched'), ('v82 · 生成码名绑定', 'candidate')]:
        m = tm[key]
        test_rows.append([name, *[m[k]['f1'] for k in ['single', 'multi', 'positive']],
                          m['negative']['correct']/500, f"{m['native_history']['strict_closed']}/421"])
    versions = [{
        'id': 'v82', 'label': 'v82 · 当前保留', 'badge': '冻结主结果', 'adopted': True,
        'title': '生成码名的空间绑定', 'stage': 'S2任务 · 接续4096末 · 无约束自由生成',
        'scope': '新独立500 TEST · A/B各250图 · 1000正例＋500负例；历史421对图',
        'method': '从历史强v40及Adam接续；3072普通定位＋1024真实历史，3315不同TRAIN图。合法、数量匹配的自由生成组经TRAIN GT一对一空间匹配后施加CE＋范围hinge；失败回退规范目标。此轮无S1回放。',
        'finding': '正例F1比强起点提高9.91pp，配对图像95%区间[7.94, 11.85]。这是当前保留模型，不以其他诊断集的最高裸分重新选模。',
        'limits': '单seed、同域固定子集，非完整官方benchmark；rollout算力及目标长度与规范对照不同。无目标正确率87.6%→81.0%；3目标60例、4+目标33例（互斥分层）严格完整均0；只出现3种对象码组／4个原子地址。',
        'tables': [{'title': '同图、同评分的独立测试对照', **table(['方法', '单目标 F1', '多目标 F1', '正例 F1', '无目标正确率', '历史闭环'], test_rows), 'formats': ['text', 'percent', 'percent', 'percent', 'percent', 'text']}],
        'charts': [chart('独立500 · 自由定位F1', ['单目标', '多目标', '正例整体'], [(name, [tm[key][k]['f1'] for k in ['single', 'multi', 'positive']]) for name,key in [('strong v40','strong'), ('规范接续','matched'), ('v82','candidate')]])],
        'notes': ['F1为注意力范围命中后的一对一实例F1，不是mask IoU或编码exact。', '历史闭环：首轮绑定＋两条独立回指分支均正确；两分支从同一首轮出发，不是连续三轮。全部421图含首轮失败。', '位置打乱／均匀注意力：正例F1 2.21%／0.88%。模型与协议事前冻结；评完关闭，不用于新选模。'],
        'sources': ['independent500', 'v82']
    }]
    cm = count['metrics']
    arms = [('规范目标', 'canonical'), ('生成绑定', 'onpolicy'), ('部分修复', 'partial'), ('修复／无自模仿CE', 'partial_no_selfce')]
    versions.append({
        'id': 'v86', 'label': 'v86 · 数量分层', 'badge': '新修改不采用', 'adopted': False,
        'title': '提高3+目标覆盖，分离空间修复与自模仿', 'stage': 'S2任务 · 四臂各接续2560末 · 无约束自由生成',
        'scope': '暴露DEV200 · 873正例；另69图派生104个3+请求（含35个4+）',
        'method': '同strong v40起点，每臂2048普通定位＋512真实历史，共2305 TRAIN图；普通定位中负／单／双各512，三／四+各256。四臂比较规范目标、原生成绑定、部分空间修复及取消自模仿CE。GT修复仅在TRAIN。',
        'finding': '原生成绑定相对规范对照正例+16.79pp，复现S2收益。部分修复的3+增益区间跨0，4+变差且保持门未过，两项新修改均不采用。',
        'limits': '3+占普通定位25%，是压力分布；实际共享表达池3+仅0.79%。四臂4+严格完整均0/35。不要以局部F1最高把“部分修复”选为当前最佳。',
        'tables': [{'title': '开发集与派生压力集分别列项', **table(['方法', 'DEV正例 F1', 'DEV多目标 F1', '派生3+ F1', '派生4+ F1', '3+严格完整 /104', 'DEV历史 /52'], [[name, cm[k]['strata']['positive']['f1'], cm[k]['strata']['multi']['f1'], cm[k]['strata']['3+']['f1'], cm[k]['strata']['4+']['f1'], str(cm[k]['strata']['3+']['strict_all_correct']), f"{round(cm[k]['closed52']*52)}/52"] for name,k in arms]), 'formats': ['text','percent','percent','percent','percent','text','text']}],
        'charts': [chart('暴露DEV200 · 正例整体F1', ['正例整体'], [(name,[cm[k]['strata']['positive']['f1']]) for name,k in arms]), chart('派生104请求 · 3+与4+目标F1', ['3+目标', '4+目标'], [(name,[cm[k]['strata']['3+']['f1'],cm[k]['strata']['4+']['f1']]) for name,k in arms])],
        'notes': ['开发选模与独立确认不能混为一张跨版本排名。各actor的rollout和目标长度会分歧，不是同FLOPs的纯机制消融。', '四臂终点及恢复均已完成；无新训练／监听。'], 'sources': ['v86']
    })
    pm = prompt['metrics']
    versions.append({
        'id':'v87', 'label':'v87 · 同模板诊断', 'badge':'零更新诊断', 'adopted':False,
        'title':'相同提示模板下的双目标到三目标变化', 'stage':'S2任务 · 冻结v82等终点 · 无约束自由生成 · 0更新',
        'scope':'已暴露69 DEV图 · 每模型两／三目标各69请求',
        'method':'固定复合提示模板与图像，比较双目标和三目标请求；目标难度仍随目标数变化。',
        'finding':'v82计数67/69→66/69，但F1 76.92%→56.30%，完整44/69→12/69；单纯数对目标数不足以形成正确空间身份。',
        'limits':'提示陌生度不是唯一解释；难度与数量耦合，不能声称纯数量因果隔离。不是新独立测试。',
        'tables':[{'title':'冻结模型／同图同模板', **table(['模型','双目标 F1','三目标 F1','双目标计数 /69','三目标计数 /69','三目标完整 /69'], [[name,pm[k]['two']['f1'],pm[k]['three']['f1'],str(pm[k]['two']['count_correct']),str(pm[k]['three']['count_correct']),str(pm[k]['three']['strict_all_correct'])] for name,k in [('strong v40','strong'),('v82','v82'),('v86生成绑定','onpolicy')]]), 'formats':['text','percent','percent','text','text','text']}],
        'charts':[chart('69 DEV图 · 双／三目标F1', ['双目标','三目标'], [(name,[pm[k]['two']['f1'],pm[k]['three']['f1']]) for name,k in [('strong v40','strong'),('v82','v82'),('v86生成绑定','onpolicy')]])],
        'notes':['不是新训练版本；本页保留诊断结果，默认模型仍为v82。'], 'sources':['v87']
    })
    dm = decode['metrics']
    decoders = [('v82 · 语法约束', 'v82_syntax'), ('v82 · 防重名约束', 'v82_unique'), ('v86生成绑定 · 语法约束','onpolicy_syntax'), ('v86生成绑定 · 防重名约束','onpolicy_unique')]
    versions.append({
        'id':'v90', 'label':'v90 · 推理解码', 'badge':'保持评测未完成', 'adopted':False,
        'title':'推理时避免重复对象码组', 'stage':'S2任务 · 冻结v82／v86 · 首轮约束解码，后续自由生成 · 0更新',
        'scope':'69已暴露DEV图派生104个3+请求；其中35个4+请求',
        'method':'比较既有FormatGrammar与UniqueGroupGrammar；仅首轮强制合法／唯一组，随后基于真实生成历史连续回指，不用GT目录或修复。',
        'finding':'v82的3+ F1提高8.02pp；4+完整0→1/35，闭环3→5/104。说明防碰撞有帮助，仍远未解决高数量身份。',
        'limits':'既有解码规则，不是新解码器或模型内化；自然200任务保持尚未运行，未采用为默认，也未开启TEST。',
        'tables':[{'title':'同一冻结权重下的推理干预', **table(['模型／解码','3+ F1','4+ F1','严格完整 /104','4+完整 /35','连续历史闭环 /104'], [[name,dm[k]['all']['f1'],dm[k]['four_plus']['f1'],str(dm[k]['all']['strict_complete']),str(dm[k]['four_plus']['strict_complete']),str(dm[k]['closed'])] for name,k in decoders]), 'formats':['text','percent','percent','text','text','text']}],
        'charts':[chart('约束推理诊断 · 3+目标F1', ['3+目标'],[(name,[dm[k]['all']['f1']]) for name,k in decoders])],
        'notes':['历史协议与独立500的分支回指不同：此处是连续追加生成历史。', '416首轮及416历史均已重放验收；诊断门通过不等于正式采用。'], 'sources':['v90']
    })
    sm = s1['partial_free200']['models']
    versions.append({
        'id':'s1', 'label':'S1 · v79全图辨析', 'badge':'负结果', 'adopted':False,
        'title':'增加S1注意力目标是否改善全图表达', 'stage':'S1任务 · S2接续末检查点 · 自由生成；非S2 F1',
        'scope':'已暴露200 DEV图 · 完整目录失败全部保留',
        'method':'同1792更新、完整CE与任务流；每步至多32个注意力目标对比全部S1目标。独立测S1固定规范原子绑定，不能以S2收益替代S1学习。',
        'finding':'部分规范绑定1.24%→1.11%，完整目录均0/200；扩监督目标没有修复全图辨析，此分支不扩训。',
        'limits':'部分绑定仅是机制诊断；完整目标辨析、S1→S2迁移及四色优于普通ID尚未成立。',
        'tables':[{'title':'同一S1任务的自由评测', **table(['S1注意力预算','部分规范绑定','位置打乱','均匀注意力','目录exact /200','结束 /200'], [[name,m['controls']['native']['coverage_image_mean'],m['controls']['shuffled']['coverage_image_mean'],m['controls']['uniform']['coverage_image_mean'],str(m['inventory_exact']),str(m['ended'])] for name,m in [('至多32目标',sm['baseline']),('全部目标',sm['all'])]]), 'formats':['text','percent','percent','percent','text','text']}],
        'charts':[chart('S1 · 部分规范原子绑定率（不是S2 F1）',['至多32目标','全部目标'],[(label,[sm[k]['controls'][key]['coverage_image_mean'] for k in ['baseline','all']]) for label,key in [('原图注意力','native'),('打乱位置','shuffled'),('均匀注意力','uniform')]])],
        'notes':['v78早期S1末32 DEV：部分绑定3.48%、目录0/32，仍是有限诊断，不与本200图跨池直接相减。'], 'sources':['s1']
    })
    dossier = {
        'schema_version':1, 'project_id':'voa', 'title':'VOA · 可引用的视觉对象地址',
        'reviewed_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
        'default_version':'v82', 'default_reason':'保留已通过开发门且完成事前冻结独立500测试的v82；不跨数据集按裸分选优。',
        'checkpoint':{'version':'v82', 'locator':'runs_onpolicy_binding_v82_onpolicy/training/step4096', 'sha256':'8851288c90dfa56b6052e73251dbb2769d0ffd229cda3da256a874765d66d0aa', 'parameters':250368, 'base':'Qwen3-VL-4B'},
        'idea':'让MLLM学习少量符号组成的对象地址，在图像中建立空间所指，并在后续对话中复用。四色／二进制原子不自带坐标或类别；物体可由多个原子组成。',
        'claim':'已验证S2局部定位与分支回指收益；S1全图辨析、原子组合及四色结构的增量仍未证实。',
        'runtime':'本地已验收汇总 · 当前源记录无本轮训练或监听；网页不查询远端、不启动模型',
        'versions':versions, 'cases':cases['cases'], 'sources':sources,
        'next_steps':[
            {'title':'保持已成立的主任务', 'detail':'以单／双目标、无目标与真实历史为主；冻结v82，两套500关闭。3+单列泛化边界，不主导剩余预算。', 'state':'当前优先'},
            {'title':'证明结构必要性', 'detail':'匹配长度、词频、参数与数据的普通ID／四色，S2-only／S1→S2；重命名、交换及图像反事实检验身份。', 'state':'待验证'},
            {'title':'补标准任务与自然指向接口', 'detail':'补官方定位指标、区域问答和真实连续对话；名称＋编码候选需先打通自然文本训练路径并通过能力保持。', 'state':'待实施'}
        ],
        'timeline':[
            {'version':'早期几何模块', 'state':'历史诊断', 'method':'边界／区域辅助的分区实验', 'result':'学习分区优于随机，但四色辅助没有稳定增量；oracle分区不代表MLLM语义定位。'},
            {'version':'v26／v27', 'state':'未采用', 'method':'自然名称与编码的生成接口', 'result':'v27旧16 DEV单目标62.30%→46.15%，闭环2→1/16；当前“名称＋指向”仍为候选，非已有通用QA。'},
            {'version':'v78／v79 · S1', 'state':'未学成', 'method':'全图生成CE＋完整编码组注意力；增加监督覆盖', 'result':'v79 S1自由任务完整目录0/200；目标覆盖扩大不构成迁移收益。'},
            {'version':'v40 → v82 · S2', 'state':'当前保留', 'method':'少量定位Q-head适配＋生成码名空间绑定', 'result':'独立500正例F1 58.92%→68.83%，分支历史闭环191→290/421。'},
            {'version':'v86／v87', 'state':'新修改不采用', 'method':'数量分层、部分修复／CE消融及同模板诊断', 'result':'原绑定收益复现；修复未过保持门，数对目标数仍不等于绑定正确。'},
            {'version':'v90', 'state':'诊断完成／未采用', 'method':'零更新防重名约束', 'result':'派生3+ F1提高；自然任务保持未测，4+完整仍仅1/35。'}
        ]
    }
    (DEST/'dossier.json').write_text(json.dumps(dossier, ensure_ascii=False, indent=2)+'\n')
    manifest = {'sources':sources, 'images':{name:digest(DEST/'cases'/name) for name in sorted(image_names)}, 'dossier_sha256':digest(DEST/'dossier.json'), 'scope':'read-only source-bound UI projection; zero new inference/training/TEST access'}
    (DEST/'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'versions':len(versions),'case_images':len(image_names),'sources':len(sources),'sha256':manifest['dossier_sha256']}))


if __name__ == '__main__':
    main()
