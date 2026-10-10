"""Register the training-free vision delivery plan, without executing research."""
import json
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/scitaste/src"))


def main():
    from scitaste.project import ProjectManifest, ProjectRuntime
    from scitaste.project.deadlines import ProjectVenueSchedule, assign_project_venue_schedule
    from scitaste.project.submission_plan import SubmissionPlanDraft, save_submission_plan
    program = json.loads((ROOT / "data/cvpr_program.json").read_text())
    runtime = ProjectRuntime(ROOT / "outputs")
    pid = program["project_id"]
    project = ROOT / "outputs/projects" / pid
    if (project / "PROJECT.json").exists():
        snapshot = runtime.open(pid)
        extra = snapshot.manifest.model_extra or {}
        if extra.get("training_free_program") != program:
            raise SystemExit("Existing project differs; retained without overwrite")
        if extra.get("submission_plan"):
            print("Existing plan retained; no jobs launched")
            return
    else:
        snapshot = runtime.create(ProjectManifest(project_id=pid, title=program["title"],
            research_direction=program["objective"], target_domain="training-free-visual-reasoning",
            target_venue="CVPR 2027", status="planning", stage_semantics="native-research-lifecycle",
            training_free_program=program))
    calendar = program["calendar"]
    milestones = []
    for key, kind in [("registration", "abstract-registration"), ("paper", "paper-submission"), ("supplement", "supplementary-submission")]:
        milestones.append({"milestone_id":"cvpr2027-"+key, "kind":kind,
            "deadline_at": calendar[key]+"T23:59:59-12:00", "hard_deadline":True,
            "source_id":"cvpr2027-official", "required_outcomes":[key]})
    schedule = ProjectVenueSchedule.create(schedule_id="cvpr2027-official-20261010", venue_id="cvpr2027",
        venue_name="CVPR 2027", deadline_timezone="AoE (UTC-12)",
        sources=[{"source_id":"cvpr2027-official", "role":"authoritative", "url":calendar["source_url"], "checked_at":"2026-10-10T00:00:00+08:00"}], milestones=milestones)
    snapshot = assign_project_venue_schedule(runtime, project_id=pid, schedule=schedule, expected_revision=snapshot.revision)
    specs = [
        ("benchmark-freeze", "核验 benchmark 与当前强基线，冻结评分/划分/资源", "benchmark", "idea", 11, (), ("当前固定型号与官方 scorer 的诊断", "基线 commit、许可、同预算和图像分组划分", "若饱和或无可识别错误则换题")),
        ("method-freeze", "冻结一个 training-free 视觉机制及最近邻区别", "scientific-contract", "idea", 12, ("benchmark-freeze",), ("可证伪的错误机制与方法假设", "同工具/总预算强对照与停止门槛")),
        ("development", "完成开发集对照与失败诊断", "experiment", "experiments", 14, ("method-freeze",), ("逐例输出与官方 scorer 重放", "配对效应、置信区间、调用/token/费用/显存", "没有稳定增量则停止扩展")),
        ("confirmation", "冻结候选后完成独立确认和关键消融", "experiment", "experiments", 15, ("development",), ("未用于选方法的图像/场景分组确认", "关键机制消融与完整负证据")),
        ("manuscript", "用结果证据组装完整研究初稿", "manuscript", "writing", 16, ("confirmation",), ("每项 claim 对应结果或明确未验证标签", "引用、图表、LaTeX/PDF 与复现条件可核查")),
        ("review-transfer", "独立评审、修订并提炼可复验的产品改进", "verification", "review", 17, ("manuscript",), ("审稿问题与证据驱动修订 diff", "实验/写作流程修复登记，下一个独立题目复验", "科学效果不足时保留失败稿，不伪造投稿就绪")),
    ]
    work = [{"work_id":wid,"title":title,"kind":kind,"phase":phase,"owner":"FastResearch / SciTaste",
        "due_at":f"2026-10-{day:02}T23:59:00+08:00", "prerequisite_ids":sorted(prereq),
        "claim_critical":True,"submission_blocking":True,"estimated_hours":8,
        "expected_evidence_gain":1,"acceptance":accept,"state":"pending"}
        for wid,title,kind,phase,day,prereq,accept in specs]
    draft=SubmissionPlanDraft(plan_id="training-free-vision-week1", project_id=pid, venue_name="CVPR 2027",
        objective=program["objective"],internal_deadline_at=datetime.fromisoformat("2026-10-17T23:59:00+08:00"),
        deadline_basis="project-internal-target",deadline_note="一周研究初稿的内部目标；科学证据达标后才讨论投稿。官方截止独立维护。",
        work_items=work,scope_rules=program["scope_rules"])
    snapshot=save_submission_plan(runtime,draft,expected_revision=snapshot.revision,
        author="FastResearch",reason="用户指定 training-free CVPR 论文迭代实验与写作能力",
        recorded_at=datetime.fromisoformat("2026-10-10T00:00:00+08:00"))
    print(json.dumps({"project_id":pid,"revision":snapshot.revision,"state":"planning","research_jobs_started":0}))


if __name__ == "__main__":
    main()
