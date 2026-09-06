const tokenInput = document.getElementById("bearer-token");
const connectButton = document.getElementById("connect");
const projectSelect = document.getElementById("project-select");
const loadButton = document.getElementById("load-project");
const connectionStatus = document.getElementById("connection-status");
const freshness = document.getElementById("freshness");
const workspace = document.getElementById("workspace");
const proposalResult = document.getElementById("proposal-result");
const artifactResult = document.getElementById("artifact-result");
const viewButtons = Array.from(document.querySelectorAll(".view-button"));
const runSelect = document.getElementById("run-select");
const openRunButton = document.getElementById("open-run");
const paperSelect = document.getElementById("paper-select");
const openPaperButton = document.getElementById("open-paper");
const comparisonControls = document.getElementById("comparison-controls");
const baselineRun = document.getElementById("baseline-run");
const candidateRun = document.getElementById("candidate-run");
const compareRunsButton = document.getElementById("compare-runs");
const quickIntents = document.getElementById("quick-intents");
const intentForm = document.getElementById("intent-form");
const intentQuestion = document.getElementById("intent-question");
const generateWorkspaceButton = document.getElementById("generate-workspace");
const intentResult = document.getElementById("intent-result");

const workspaceViews = Object.freeze(new Set([
  "project-progress",
  "project-overview",
  "run-stage-explorer",
  "paper-evidence",
  "run-comparison",
  "blockers",
  "pending-proposals",
]));
const responseCache = new Map();
let currentDocument = null;
let runCatalog = [];
let paperCatalog = [];
let quickIntentCatalog = null;
let activeProjectId = "";
let eventCounter = 0;
let artifactObjectUrl = null;

function appendText(parent, value) {
  parent.appendChild(document.createTextNode(formatValue(value)));
}

function formatValue(value) {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return String(value);
}

function fixedFields(data, names) {
  const list = document.createElement("dl");
  list.className = "field-list";
  for (const name of names) {
    if (!Object.hasOwn(data, name)) {
      continue;
    }
    const term = document.createElement("dt");
    appendText(term, name.replaceAll("_", " "));
    const description = document.createElement("dd");
    appendText(description, data[name]);
    list.append(term, description);
  }
  return list;
}

function fixedRows(rows, names) {
  const list = document.createElement("ul");
  list.className = "record-list";
  for (const row of rows || []) {
    const item = document.createElement("li");
    item.appendChild(fixedFields(row, names));
    list.appendChild(item);
  }
  return list;
}

function titledSection(title, content) {
  const section = document.createElement("section");
  section.className = "nested-section";
  const heading = document.createElement("h3");
  appendText(heading, title);
  section.append(heading, content);
  return section;
}

const progressStateLabels = Object.freeze({
  observed_completed: "Observed complete",
  current_work: "Current work",
  blocked: "Blocked",
  failed: "Failed",
  candidate: "Candidate",
  unavailable: "Unavailable",
  unknown: "Unknown",
});

function readableCode(value) {
  return formatValue(value).replaceAll("_", " ").replaceAll("-", " ");
}

function compactRunLabel(runId) {
  const parts = String(runId).split("__");
  if (parts.length >= 3) {
    return `${readableCode(parts[2])} · ${parts[1]}`;
  }
  return readableCode(runId);
}

function progressPill(state, label = null) {
  const pill = document.createElement("span");
  pill.className = `progress-pill state-${state}`;
  appendText(pill, label || progressStateLabels[state] || readableCode(state));
  return pill;
}

function evidenceDisclosure(refIds, fields = null) {
  const details = document.createElement("details");
  details.className = "evidence-disclosure";
  const summary = document.createElement("summary");
  const references = Array.from(new Set(refIds || []));
  appendText(summary, `${references.length} evidence ${references.length === 1 ? "record" : "records"}`);
  details.appendChild(summary);
  if (fields) {
    details.appendChild(fixedFields(fields.data, fields.names));
  }
  if (references.length > 0) {
    const list = document.createElement("ul");
    list.className = "evidence-ref-list";
    for (const reference of references) {
      const item = document.createElement("li");
      const code = document.createElement("code");
      appendText(code, reference);
      item.appendChild(code);
      list.appendChild(item);
    }
    details.appendChild(list);
  }
  return details;
}

function progressMetric(label, value, note, tone = "neutral") {
  const card = document.createElement("div");
  card.className = `progress-metric tone-${tone}`;
  const number = document.createElement("strong");
  number.className = "progress-metric-value";
  appendText(number, value);
  const name = document.createElement("span");
  name.className = "progress-metric-label";
  appendText(name, label);
  const context = document.createElement("small");
  appendText(context, note);
  card.append(number, name, context);
  return card;
}

function progressSection(title, subtitle = null) {
  const section = document.createElement("section");
  section.className = "progress-section";
  const header = document.createElement("div");
  header.className = "progress-section-header";
  const heading = document.createElement("h3");
  appendText(heading, title);
  header.appendChild(heading);
  if (subtitle) {
    const description = document.createElement("p");
    appendText(description, subtitle);
    header.appendChild(description);
  }
  section.appendChild(header);
  return section;
}

function renderRunDistribution(counts) {
  const section = progressSection(
    "Registered run outcomes",
    "Exact record distribution · this is not a project completion percentage.",
  );
  const definitions = [
    ["observed_completed", "Completed", counts.runs_completed],
    ["current_work", "Active", counts.runs_active],
    ["candidate", "Candidate", counts.runs_candidates],
    ["blocked", "Blocked", counts.runs_blocked],
    ["failed", "Failed", counts.runs_failed],
    ["unavailable", "Unavailable", counts.runs_unavailable],
    ["unknown", "Unknown", counts.runs_unknown],
  ];
  const distribution = document.createElement("div");
  distribution.className = "run-distribution";
  distribution.setAttribute("role", "img");
  distribution.setAttribute("aria-label", definitions
    .filter(([, , count]) => count > 0)
    .map(([, label, count]) => `${label}: ${count}`)
    .join(", "));
  const legend = document.createElement("ul");
  legend.className = "run-distribution-legend";
  for (const [state, label, count] of definitions) {
    if (count <= 0) {
      continue;
    }
    const segment = document.createElement("span");
    segment.className = `distribution-segment state-${state}`;
    segment.style.flexGrow = String(count);
    distribution.appendChild(segment);
    const item = document.createElement("li");
    const marker = document.createElement("span");
    marker.className = `distribution-marker state-${state}`;
    marker.setAttribute("aria-hidden", "true");
    const labelText = document.createElement("span");
    appendText(labelText, label);
    const value = document.createElement("strong");
    appendText(value, count);
    item.append(marker, labelText, value);
    legend.appendChild(item);
  }
  section.append(distribution, legend);
  return section;
}

function renderAttentionItem(item) {
  const card = document.createElement("article");
  card.className = "attention-item";
  const header = document.createElement("div");
  header.className = "compact-row-header";
  const title = document.createElement("strong");
  appendText(title, compactRunLabel(item.run_id));
  header.append(title, progressPill(item.classification));
  card.appendChild(header);
  if (item.recorded_reasons.length > 0) {
    const reasons = document.createElement("ul");
    reasons.className = "reason-list";
    for (const reason of item.recorded_reasons) {
      const reasonItem = document.createElement("li");
      appendText(reasonItem, reason);
      reasons.appendChild(reasonItem);
    }
    card.appendChild(reasons);
  } else {
    const unavailable = document.createElement("p");
    unavailable.className = "muted compact-copy";
    appendText(unavailable, "No recorded reason is available for this run.");
    card.appendChild(unavailable);
  }
  card.appendChild(evidenceDisclosure(item.support_ref_ids, {
    data: {run_id: item.run_id, source_locator: item.source_locator},
    names: ["run_id", "source_locator"],
  }));
  return card;
}

function renderMilestoneItem(item) {
  const row = document.createElement("li");
  row.className = "milestone-item";
  const marker = document.createElement("span");
  marker.className = `timeline-marker state-${item.observed_state}`;
  marker.setAttribute("aria-hidden", "true");
  const content = document.createElement("div");
  const header = document.createElement("div");
  header.className = "compact-row-header";
  const date = document.createElement("time");
  date.dateTime = item.recorded_on;
  appendText(date, item.recorded_on);
  header.append(date, progressPill(item.observed_state));
  const decision = document.createElement("p");
  decision.className = "milestone-decision";
  appendText(decision, item.decision);
  const identity = document.createElement("small");
  identity.className = "muted identity-caption";
  appendText(identity, readableCode(item.milestone_id));
  content.append(header, decision, identity, evidenceDisclosure(item.support_ref_ids, {
    data: {
      evidence_binding: item.evidence_binding,
      evidence_locator: item.evidence_locator,
      reported_status: item.reported_status,
    },
    names: ["evidence_binding", "evidence_locator", "reported_status"],
  }));
  row.append(marker, content);
  return row;
}

function renderActivityItem(item) {
  const row = document.createElement("li");
  row.className = "activity-item";
  const header = document.createElement("div");
  header.className = "compact-row-header";
  const title = document.createElement("strong");
  appendText(title, compactRunLabel(item.run_id));
  header.append(title, progressPill(item.observed_state));
  const metadata = document.createElement("p");
  metadata.className = "activity-meta";
  appendText(metadata, `${item.provider} · ${item.model_name}`);
  row.append(header, metadata);
  if (item.selected) {
    const selected = document.createElement("span");
    selected.className = "selection-badge";
    appendText(selected, "Selected current run");
    row.appendChild(selected);
  }
  row.appendChild(evidenceDisclosure(item.support_ref_ids, {
    data: {run_id: item.run_id, evidence_scope: item.evidence_scope},
    names: ["run_id", "evidence_scope"],
  }));
  return row;
}

function requestCandidateWorkspace(candidateId) {
  const descriptor = quickIntentCatalog?.intents.find(
    (item) => item.quick_intent_id === candidateId,
  );
  if (!descriptor) {
    showError(intentResult, new Error("Reload this project's current intent catalog."));
    return;
  }
  generateWithIntent({
    schema_version: "1.0",
    kind: "quick",
    project_id: quickIntentCatalog.snapshot.project_id,
    snapshot_revision: quickIntentCatalog.snapshot.snapshot_revision,
    snapshot_sha256: quickIntentCatalog.snapshot.snapshot_sha256,
    quick_intent_id: descriptor.quick_intent_id,
  });
}

function renderRunStageExplorer(data) {
  const container = document.createElement("div");
  const runList = document.createElement("ul");
  runList.className = "selection-list";
  for (const run of data.runs) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = run.selected ? "identity-button selected" : "identity-button";
    appendText(button, `${run.run_id} · ${run.outcome}`);
    button.addEventListener("click", () => {
      loadWorkspace({
        view: "run-stage-explorer",
        project_id: currentProjectId(),
        run_id: run.run_id,
      });
    });
    item.append(button, fixedFields(run, [
      "provider",
      "model_name",
      "condition",
      "seed",
      "status",
      "evidence_scope",
      "summary_code",
    ]));
    runList.appendChild(item);
  }
  container.appendChild(titledSection("Registered runs", runList));

  if (data.stages.length > 0) {
    const stages = document.createElement("ol");
    stages.className = "stage-list";
    for (const stage of data.stages) {
      const item = document.createElement("li");
      const heading = document.createElement("strong");
      appendText(heading, `Stage ${stage.stage} · ${stage.label_en} · ${stage.label_zh}`);
      item.append(heading, fixedFields(stage, [
        "status",
        "artifact_count",
        "output_locator",
        "summary_code",
      ]));
      stages.appendChild(item);
    }
    container.appendChild(titledSection("Authoritative stage outputs", stages));
  } else {
    container.appendChild(fixedFields(data, ["stage_state"]));
  }
  return container;
}

function renderEvidenceInventory(data) {
  const list = document.createElement("ul");
  list.className = "evidence-list";
  for (const evidence of data.items) {
    const item = document.createElement("li");
    const kind = document.createElement("strong");
    appendText(kind, evidence.kind);
    const hash = document.createElement("code");
    appendText(hash, evidence.sha256);
    item.append(kind, fixedFields(evidence, ["label", "locator"]), hash);
    list.appendChild(item);
  }
  return list;
}

function renderComparison(data) {
  const container = document.createElement("div");
  container.className = "comparison-grid";
  container.append(
    titledSection("Baseline", fixedFields(data.baseline, [
      "run_id", "status", "provider", "model_name", "condition", "seed", "evidence_scope",
    ])),
    titledSection("Candidate", fixedFields(data.candidate, [
      "run_id", "status", "provider", "model_name", "condition", "seed", "evidence_scope",
    ])),
    titledSection("Comparable metrics", fixedFields(data, [
      "metrics_state", "metrics_reason_code", "metrics",
    ])),
  );
  return container;
}

function renderArtifactViewer(data) {
  const container = document.createElement("div");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inspect-button";
  appendText(button, "Inspect verified preview");
  button.addEventListener("click", () => inspectArtifact(data.artifact_ref_id));
  container.append(
    fixedFields(data, ["artifact_path", "media_type", "artifact_ref_id"]),
    button,
  );
  return container;
}

function renderProjectSummary(data) {
  const container = document.createElement("div");
  container.className = "project-summary-card";
  const status = document.createElement("div");
  status.className = "compact-row-header";
  const statusLabel = document.createElement("span");
  statusLabel.className = "card-label";
  appendText(statusLabel, "Recorded project status");
  status.append(statusLabel, progressPill(data.project_status, readableCode(data.project_status)));
  const focus = document.createElement("p");
  focus.className = "project-focus-copy";
  appendText(focus, data.current_focus);
  const publication = document.createElement("p");
  publication.className = "availability-note";
  appendText(publication, data.publication_ready
    ? "A publication-ready paper is registered."
    : "No publication-ready paper is registered.");
  container.append(status, focus, publication, evidenceDisclosure([data.project_ref_id]));
  return container;
}

function renderRunHealth(data) {
  const container = document.createElement("div");
  container.className = "run-health-summary";
  const state = ["complete", "completed", "succeeded", "success"].includes(data.run_status)
    ? "observed_completed"
    : data.run_status;
  container.appendChild(progressPill(state, readableCode(data.run_status)));
  const facts = document.createElement("div");
  facts.className = "health-facts";
  const factValues = [
    ["Failure stage", data.failure_stage],
    ["Retry safe", data.retry_safe],
    ["Schema valid", data.schema_valid],
  ];
  for (const [label, value] of factValues) {
    const fact = document.createElement("div");
    const factLabel = document.createElement("small");
    appendText(factLabel, label);
    const factValue = document.createElement("strong");
    appendText(factValue, value);
    fact.append(factLabel, factValue);
    facts.appendChild(fact);
  }
  container.append(facts, evidenceDisclosure([data.run_ref_id]));
  return container;
}

function renderRunBlockers(data) {
  const container = document.createElement("div");
  container.className = "generated-blocker-summary";
  const summary = document.createElement("p");
  summary.className = "component-lede";
  appendText(summary, `${data.blockers.length} registered runs require attention.`);
  const list = document.createElement("div");
  list.className = "generated-blocker-list";
  for (const blocker of data.blockers) {
    const item = document.createElement("article");
    item.className = "generated-blocker-item";
    const header = document.createElement("div");
    header.className = "compact-row-header";
    const title = document.createElement("strong");
    appendText(title, compactRunLabel(blocker.run_id));
    header.append(title, progressPill(blocker.classification));
    const reason = document.createElement("p");
    reason.className = "blocker-reason";
    if (blocker.recorded_reasons.length > 0) {
      appendText(reason, blocker.recorded_reasons[0]);
    } else {
      appendText(reason, "No recorded reason is available.");
    }
    item.append(header, reason);
    if (blocker.recorded_reasons.length > 1) {
      const moreReasons = document.createElement("ul");
      moreReasons.className = "reason-list";
      for (const recordedReason of blocker.recorded_reasons.slice(1)) {
        const reasonItem = document.createElement("li");
        appendText(reasonItem, recordedReason);
        moreReasons.appendChild(reasonItem);
      }
      item.appendChild(moreReasons);
    }
    item.appendChild(evidenceDisclosure([blocker.run_ref_id], {
      data: {run_id: blocker.run_id, source_locator: blocker.source_locator},
      names: ["run_id", "source_locator"],
    }));
    list.appendChild(item);
  }
  container.append(summary, list);
  return container;
}

function renderProjectProgress(data) {
  const container = document.createElement("div");
  container.className = "progress-board";

  const attentionCount = data.counts.runs_blocked + data.counts.runs_failed;
  const hero = document.createElement("section");
  hero.className = `progress-hero state-${data.project_state}`;
  const heroTop = document.createElement("div");
  heroTop.className = "progress-hero-top";
  const heroLabel = document.createElement("p");
  heroLabel.className = "eyebrow dark";
  appendText(heroLabel, "Canonical evidence snapshot");
  heroTop.append(heroLabel, progressPill(data.project_state));
  const summary = document.createElement("p");
  summary.className = "progress-summary";
  const candidateClause = data.counts.runs_candidates === 1
    ? "1 remains a candidate"
    : `${data.counts.runs_candidates} remain candidates`;
  const paperClause = data.counts.papers_registered === 1
    ? "1 paper is registered"
    : `${data.counts.papers_registered} papers are registered`;
  appendText(
    summary,
    `${data.counts.runs_completed} of ${data.counts.runs_registered} registered run records have observed completion. `
      + `${attentionCount} need attention; ${candidateClause}. ${paperClause}.`,
  );
  const generationHint = document.createElement("p");
  generationHint.className = "generation-hint";
  appendText(
    generationHint,
    "Use an evidence prompt or free question to recompose this workspace around a specific goal.",
  );
  hero.append(heroTop, summary, generationHint, evidenceDisclosure(data.summary_ref_ids, {
    data: {
      recorded_project_status: data.project_status,
      publication_ready: data.publication_ready,
    },
    names: ["recorded_project_status", "publication_ready"],
  }));

  const metrics = document.createElement("div");
  metrics.className = "progress-metrics";
  metrics.append(
    progressMetric("Registered runs", data.counts.runs_registered, "authoritative records"),
    progressMetric("Observed complete", data.counts.runs_completed, "run records", "positive"),
    progressMetric("Need attention", attentionCount, "blocked or failed", attentionCount ? "warning" : "positive"),
    progressMetric("Candidates", data.counts.runs_candidates, "not yet accepted", "candidate"),
    progressMetric("Completed stages", data.counts.completed_stages, "where stage semantics apply"),
    progressMetric("Papers", data.counts.papers_registered, "registered artifacts"),
  );
  container.append(hero, metrics, renderRunDistribution(data.counts));

  const direction = progressSection("Current direction", "Recorded focus, selection, and next gate.");
  const directionGrid = document.createElement("div");
  directionGrid.className = "direction-grid";
  const focus = document.createElement("article");
  const focusLabel = document.createElement("span");
  focusLabel.className = "card-label";
  appendText(focusLabel, "Current focus");
  const focusValue = document.createElement("strong");
  appendText(focusValue, readableCode(data.focus));
  const focusStatus = document.createElement("small");
  appendText(focusStatus, readableCode(data.focus_status));
  focus.append(focusLabel, focusValue, focusStatus, evidenceDisclosure(data.focus_ref_ids));
  const gate = document.createElement("article");
  const gateLabel = document.createElement("span");
  gateLabel.className = "card-label";
  appendText(gateLabel, "Next evidence gate");
  const gateValue = document.createElement("strong");
  appendText(gateValue, data.next_gate || "No next gate is recorded.");
  gate.append(gateLabel, gateValue);
  directionGrid.append(focus, gate);
  if (data.current_run_id) {
    const currentRun = document.createElement("article");
    currentRun.className = "current-run-card";
    const runCopy = document.createElement("div");
    const runLabel = document.createElement("span");
    runLabel.className = "card-label";
    appendText(runLabel, "Selected run · selection is not execution");
    const runValue = document.createElement("strong");
    appendText(runValue, compactRunLabel(data.current_run_id));
    runCopy.append(runLabel, runValue, evidenceDisclosure(data.current_run_ref_ids, {
      data: {run_id: data.current_run_id, recorded_status: data.current_run_status},
      names: ["run_id", "recorded_status"],
    }));
    const openRun = document.createElement("button");
    openRun.type = "button";
    openRun.className = "secondary-button";
    appendText(openRun, "Open run stages");
    openRun.addEventListener("click", () => loadWorkspace({
      view: "run-stage-explorer",
      project_id: currentProjectId(),
      run_id: data.current_run_id,
    }));
    currentRun.append(runCopy, progressPill(data.current_run_state), openRun);
    directionGrid.appendChild(currentRun);
  }
  direction.appendChild(directionGrid);
  container.appendChild(direction);

  const standing = document.createElement("div");
  standing.className = "progress-columns";
  if (data.attention.length > 0) {
    const attention = progressSection("Needs attention", `${data.attention.length} registered runs are blocked or failed.`);
    const attentionList = document.createElement("div");
    attentionList.className = "attention-list";
    for (const item of data.attention) {
      attentionList.appendChild(renderAttentionItem(item));
    }
    attention.appendChild(attentionList);
    standing.appendChild(attention);
  }

  const milestones = progressSection(
    "Decision timeline",
    data.milestones.length > 0
      ? `${data.milestones.length} declared milestones in recorded order.`
      : "No project milestone is available.",
  );
  if (data.milestones.length > 0) {
    const timeline = document.createElement("ol");
    timeline.className = "milestone-timeline";
    for (const item of data.milestones) {
      timeline.appendChild(renderMilestoneItem(item));
    }
    milestones.appendChild(timeline);
  } else {
    milestones.appendChild(evidenceDisclosure([], {
      data: {state: data.milestone_state, reason: data.milestone_reason_code},
      names: ["state", "reason"],
    }));
  }
  standing.appendChild(milestones);
  container.appendChild(standing);

  const activityAndNext = document.createElement("div");
  activityAndNext.className = "progress-columns lower-grid";
  const activity = progressSection(
    "Recent registered activity",
    `${data.activity_total} run records · latest manifest entries shown first.`,
  );
  const visibleActivity = document.createElement("ul");
  visibleActivity.className = "activity-list";
  for (const item of data.recent_activity.slice(0, 4)) {
    visibleActivity.appendChild(renderActivityItem(item));
  }
  activity.appendChild(visibleActivity);
  if (data.recent_activity.length > 4) {
    const more = document.createElement("details");
    more.className = "more-activity";
    const moreSummary = document.createElement("summary");
    appendText(moreSummary, `Show ${data.recent_activity.length - 4} more registered runs`);
    const remainder = document.createElement("ul");
    remainder.className = "activity-list";
    for (const item of data.recent_activity.slice(4)) {
      remainder.appendChild(renderActivityItem(item));
    }
    more.append(moreSummary, remainder);
    activity.appendChild(more);
  }
  if (data.activity_truncated) {
    const truncated = document.createElement("p");
    truncated.className = "muted compact-copy";
    appendText(truncated, "The server bounded this activity list; open Runs & stages for the full catalog.");
    activity.appendChild(truncated);
  }
  activityAndNext.appendChild(activity);

  const nextSteps = progressSection(
    "Explore next",
    "These evidence-supported options generate another read-only workspace; they do not start work.",
  );
  const candidateLabels = {
    review_progress: "Review this progress",
    diagnose_blockers: "Diagnose blockers",
    compare_runs: "Compare recent runs",
    review_paper_evidence: "Review paper evidence",
    review_next_gate: "Explore the next gate",
  };
  const candidateList = document.createElement("div");
  candidateList.className = "candidate-list";
  for (const candidate of data.next_step_candidates) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "candidate-button";
    const label = document.createElement("strong");
    appendText(label, candidateLabels[candidate.kind] || readableCode(candidate.label_code));
    const note = document.createElement("small");
    appendText(note, `${candidate.target_ids.length} bound targets · ${candidate.support_ref_ids.length} evidence records`);
    button.append(label, note);
    button.addEventListener("click", () => requestCandidateWorkspace(candidate.candidate_id));
    candidateList.appendChild(button);
  }
  nextSteps.appendChild(candidateList);

  const availability = document.createElement("div");
  availability.className = "availability-note";
  if (data.stages.length > 0) {
    appendText(availability, `${data.stages.length} stage records are available in Runs & stages.`);
  } else if (data.stage_semantics === "self-development-milestones-not-autoresearchclaw-stages") {
    appendText(availability, "This self-development project uses decision milestones instead of AutoResearchClaw stage progress.");
  } else {
    appendText(availability, `Stage evidence is ${readableCode(data.stage_state)}.`);
  }
  if (data.papers.length > 0) {
    appendText(availability, ` ${data.papers.length} registered papers are available in Papers & evidence.`);
  } else {
    appendText(availability, " No paper is currently registered.");
  }
  nextSteps.appendChild(availability);
  activityAndNext.appendChild(nextSteps);
  container.appendChild(activityAndNext);
  return container;
}

const componentRenderers = Object.freeze({
  ProjectSummaryCard: renderProjectSummary,
  StageTimeline: (data) => fixedRows(data.stages, ["stage", "status", "stage_ref_id"]),
  BlockerList: (data) => fixedRows(
    data.blockers,
    ["blocker_id", "severity", "status", "summary", "blocker_ref_id"],
  ),
  RunHealth: renderRunHealth,
  BudgetMeter: (data) => fixedRows(data.resources, ["resource", "used", "limit", "unit"]),
  DecisionComparison: (data) => fixedFields(data, Object.keys(data)),
  EvidenceGraph: (data) => {
    const container = document.createElement("div");
    container.appendChild(fixedRows(data.nodes, ["kind", "label", "evidence_ref_id"]));
    container.appendChild(fixedRows(data.edges, ["relation", "source_ref_id", "target_ref_id"]));
    return container;
  },
  ClaimMatrix: (data) => fixedRows(
    data.claims,
    ["statement", "status", "claim_ref_id", "evidence_ref_ids"],
  ),
  ReviewerQueue: (data) => fixedRows(data.reviews, ["status", "summary", "review_ref_id"]),
  ArtifactViewer: renderArtifactViewer,
  PaperPreview: (data) => fixedFields(
    data,
    ["paper_title", "paper_status", "publication_ready", "excerpt", "paper_ref_id"],
  ),
  AvailabilityNotice: (data) => fixedFields(
    data,
    ["subject", "state", "reason_code", "project_ref_id"],
  ),
  RunStageExplorer: renderRunStageExplorer,
  EvidenceInventory: renderEvidenceInventory,
  RunComparisonPanel: renderComparison,
  RunBlockerPanel: renderRunBlockers,
  PendingProposalList: (data) => fixedRows(
    data.proposals,
    ["event_id", "action_id", "status", "next_boundary", "execution_authority"],
  ),
  ProjectProgressBoard: renderProjectProgress,
});

function renderWorkspace(documentValue) {
  const renderer = documentValue.renderer;
  const generated = documentValue.status === "generated";
  const placements = new Map((documentValue.placements || []).map(
    (item) => [item.component_id, item],
  ));
  workspace.classList.toggle("generated-workspace", generated);
  workspace.replaceChildren();
  proposalResult.replaceChildren();
  clearArtifactPreview();
  if (generated) {
    workspace.appendChild(renderGenerationSummary(documentValue));
  }
  const title = document.createElement("h2");
  title.className = "workspace-title";
  appendText(title, renderer.title);
  workspace.appendChild(title);
  const cards = new Map();
  for (const component of renderer.components) {
    const renderComponent = componentRenderers[component.renderer];
    if (typeof renderComponent !== "function") {
      throw new Error("The server selected an unknown receiver component.");
    }
    const card = document.createElement("section");
    card.className = "component-card";
    const placement = placements.get(component.component_id);
    if (placement) {
      card.classList.add(`plan-group-${placement.group}`);
      card.classList.add(`plan-emphasis-${placement.emphasis}`);
    }
    const heading = document.createElement("h2");
    appendText(heading, component.title);
    card.append(heading, renderComponent(component.data));
    if (placement) {
      const explanation = document.createElement("p");
      explanation.className = "placement-explanation";
      appendText(explanation, placement.explanation);
      card.appendChild(explanation);
    }
    workspace.appendChild(card);
    cards.set(component.component_id, card);
  }
  for (const action of renderer.actions) {
    const card = cards.get(action.component_id);
    if (!card) {
      throw new Error("The server returned an action without a receiver component.");
    }
    let actions = card.querySelector(".component-actions");
    if (!actions) {
      actions = document.createElement("div");
      actions.className = "component-actions";
      card.appendChild(actions);
    }
    const button = document.createElement("button");
    button.type = "button";
    appendText(button, action.label);
    button.addEventListener("click", () => submitAction(action));
    actions.appendChild(button);
  }
  updateCatalogs(documentValue);
  updateFreshness(documentValue);
  updateActiveView(generated ? null : documentValue.query.view);
  workspace.setAttribute("aria-busy", "false");
  workspace.focus({preventScroll: true});
}

function renderGenerationSummary(documentValue) {
  const summary = document.createElement("section");
  summary.className = "generation-summary";
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow dark";
  appendText(eyebrow, "Validated generated workspace");
  const heading = document.createElement("h2");
  appendText(heading, documentValue.intent.goal.replaceAll("_", " "));
  const planner = documentValue.planning?.provenance;
  const metadata = document.createElement("div");
  metadata.className = "generation-metadata";
  const values = [
    ["Planner", readableCode(planner?.mode)],
    ["Evidence snapshot", `revision ${documentValue.snapshot_revision}`],
    ["Authority", "read-only"],
  ];
  for (const [label, value] of values) {
    const item = document.createElement("span");
    const itemLabel = document.createElement("small");
    appendText(itemLabel, label);
    const itemValue = document.createElement("strong");
    appendText(itemValue, value);
    item.append(itemLabel, itemValue);
    metadata.appendChild(item);
  }
  const provenance = document.createElement("details");
  provenance.className = "generation-provenance";
  const provenanceSummary = document.createElement("summary");
  appendText(provenanceSummary, "Planning provenance");
  provenance.append(provenanceSummary, fixedFields({
    reason_code: documentValue.reason_code,
    execution_authority: documentValue.execution_authority,
  }, ["reason_code", "execution_authority"]));
  summary.append(eyebrow, heading, metadata, provenance);
  return summary;
}

function updateFreshness(documentValue) {
  const state = documentValue.freshness;
  freshness.textContent = [
    `Project revision ${state.project_revision}`,
    `evidence ${state.evidence_count}`,
    `snapshot ${state.snapshot_sha256.slice(0, 12)}`,
    `surface ${state.surface_fingerprint.slice(0, 12)}`,
  ].join(" · ");
}

function updateActiveView(view) {
  for (const button of viewButtons) {
    if (button.dataset.view === view) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  }
}

function updateCatalogs(documentValue) {
  resetCatalogs();
  const runComponent = documentValue.renderer.components.find(
    (item) => item.renderer === "RunStageExplorer",
  );
  if (runComponent) {
    runCatalog = runComponent.data.runs.map((item) => item.run_id);
    populateSelect(runSelect, runCatalog, runComponent.data.selected_run_id);
    populateSelect(baselineRun, runCatalog, runCatalog[0]);
    populateSelect(candidateRun, runCatalog, runCatalog[1] || runCatalog[0]);
  }
  const inventory = documentValue.renderer.components.find(
    (item) => item.renderer === "EvidenceInventory",
  );
  if (inventory) {
    paperCatalog = Array.from(new Set(inventory.data.items
      .filter((item) => item.kind === "paper")
      .map((item) => item.locator.split("/")[1])
      .filter((item) => validEntryId(item))));
    populateSelect(paperSelect, paperCatalog, inventory.data.selected_paper_id);
  }
  updateSelectionControls();
}

function resetCatalogs() {
  runCatalog = [];
  paperCatalog = [];
  runSelect.replaceChildren();
  baselineRun.replaceChildren();
  candidateRun.replaceChildren();
  paperSelect.replaceChildren();
  updateSelectionControls();
}

function populateSelect(select, values, selectedValue) {
  select.replaceChildren();
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    appendText(option, value);
    option.selected = value === selectedValue;
    select.appendChild(option);
  }
}

function updateSelectionControls() {
  const connected = Boolean(currentProjectId());
  runSelect.disabled = !connected || runCatalog.length === 0;
  openRunButton.disabled = runSelect.disabled;
  paperSelect.disabled = !connected || paperCatalog.length === 0;
  openPaperButton.disabled = paperSelect.disabled;
  comparisonControls.disabled = !connected || runCatalog.length < 2;
}

async function submitAction(action) {
  if (!currentDocument) {
    return;
  }
  const renderer = currentDocument.renderer;
  const event = {
    schema_version: "1.0",
    event_id: `browser-event-${Date.now()}-${eventCounter++}`,
    event_type: "surface_action_requested",
    project_id: renderer.project_id,
    surface_id: renderer.surface_id,
    surface_revision: renderer.surface_revision,
    surface_fingerprint: renderer.surface_fingerprint,
    snapshot_revision: renderer.snapshot.snapshot_revision,
    snapshot_sha256: renderer.snapshot.snapshot_sha256,
    action_id: action.action_id,
  };
  try {
    const receipt = await api(interactionPath("events"), {
      method: "POST",
      body: JSON.stringify(event),
    });
    const explanation = document.createElement("p");
    explanation.className = "proposal-explanation";
    explanation.textContent = "Advice recorded. Awaiting a deterministic controller; not approved or executed.";
    proposalResult.replaceChildren(
      explanation,
      fixedFields(receipt, [
        "status",
        "execution_authority",
        "next_boundary",
        "event_id",
        "action_id",
      ]),
    );
  } catch (error) {
    showError(proposalResult, error);
  }
}

async function inspectArtifact(artifactRefId) {
  if (!currentDocument) {
    return;
  }
  const renderer = currentDocument.renderer;
  const event = {
    schema_version: "1.0",
    event_id: `inspection-${Date.now()}-${eventCounter++}`,
    event_type: "artifact_inspection_requested",
    project_id: renderer.project_id,
    surface_id: renderer.surface_id,
    surface_revision: renderer.surface_revision,
    surface_fingerprint: renderer.surface_fingerprint,
    snapshot_revision: renderer.snapshot.snapshot_revision,
    snapshot_sha256: renderer.snapshot.snapshot_sha256,
    artifact_ref_id: artifactRefId,
  };
  artifactResult.setAttribute("aria-busy", "true");
  try {
    const preview = await api(interactionPath("inspections"), {
      method: "POST",
      body: JSON.stringify(event),
    });
    renderArtifactPreview(preview);
  } catch (error) {
    clearArtifactPreview();
    showError(artifactResult, error);
  } finally {
    artifactResult.setAttribute("aria-busy", "false");
  }
}

function clearArtifactPreview() {
  if (artifactObjectUrl !== null) {
    URL.revokeObjectURL(artifactObjectUrl);
    artifactObjectUrl = null;
  }
  artifactResult.replaceChildren();
}

function interactionPath(operation) {
  if (!currentDocument || !["events", "inspections"].includes(operation)) {
    throw new Error("No current trusted interaction surface is available.");
  }
  if (currentDocument.status === "generated") {
    const renderer = currentDocument.renderer;
    return `/api/v3/generative/projects/${encodeURIComponent(renderer.project_id)}`
      + `/generations/${encodeURIComponent(renderer.surface_id)}/${operation}`;
  }
  return `${workspacePath(currentDocument.query)}/${operation}`;
}

function renderArtifactPreview(preview) {
  clearArtifactPreview();
  const metadata = fixedFields(preview.receipt, [
    "media_type",
    "byte_length",
    "artifact_sha256",
    "execution_authority",
  ]);
  artifactResult.appendChild(metadata);
  if (preview.preview_kind === "image") {
    const binary = atob(preview.image_base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    artifactObjectUrl = URL.createObjectURL(new Blob([bytes], {
      type: preview.receipt.media_type,
    }));
    const image = document.createElement("img");
    image.className = "artifact-image";
    image.alt = "Verified project artifact preview";
    image.src = artifactObjectUrl;
    artifactResult.appendChild(image);
    return;
  }
  if (preview.preview_kind === "pdf_metadata") {
    artifactResult.appendChild(fixedFields(preview, ["preview_kind", "pdf_version"]));
    return;
  }
  const source = document.createElement("pre");
  source.className = "artifact-source";
  source.textContent = preview.text_content;
  artifactResult.appendChild(source);
}

function setIntentEnabled(enabled) {
  intentQuestion.disabled = !enabled;
  generateWorkspaceButton.disabled = !enabled;
  for (const button of quickIntents.querySelectorAll("button")) {
    button.disabled = !enabled;
  }
}

function clearProjectContext(projectId = "") {
  activeProjectId = projectId;
  currentDocument = null;
  quickIntentCatalog = null;
  responseCache.clear();
  resetCatalogs();
  intentQuestion.value = "";
  quickIntents.replaceChildren();
  const quickMessage = document.createElement("p");
  quickMessage.className = "muted";
  appendText(quickMessage, projectId
    ? "Loading prompts grounded in this project..."
    : "Open a project to load applicable prompts.");
  quickIntents.appendChild(quickMessage);
  intentResult.replaceChildren();
  const intentMessage = document.createElement("p");
  intentMessage.className = "muted";
  appendText(intentMessage, "No generated workspace requested.");
  intentResult.appendChild(intentMessage);
  proposalResult.replaceChildren();
  clearArtifactPreview();
  freshness.textContent = "No authoritative project view loaded.";
  workspace.replaceChildren();
  workspace.classList.remove("generated-workspace");
  const empty = document.createElement("p");
  empty.className = "empty-state";
  appendText(empty, projectId
    ? "Open the selected project to load its evidence."
    : "No trusted project workspace is loaded.");
  workspace.appendChild(empty);
  setIntentEnabled(false);
}

async function loadQuickIntents(projectId) {
  const requestedProject = projectId;
  try {
    const catalog = await api(
      `/api/v3/generative/projects/${encodeURIComponent(projectId)}/intents`,
    );
    if (activeProjectId !== requestedProject || projectSelect.value !== requestedProject) {
      return;
    }
    quickIntentCatalog = catalog;
    quickIntents.replaceChildren();
    for (const descriptor of catalog.intents) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quick-intent-button";
      button.dataset.quickIntentId = descriptor.quick_intent_id;
      appendText(button, descriptor.label);
      button.addEventListener("click", () => generateWithIntent({
        schema_version: "1.0",
        kind: "quick",
        project_id: catalog.snapshot.project_id,
        snapshot_revision: catalog.snapshot.snapshot_revision,
        snapshot_sha256: catalog.snapshot.snapshot_sha256,
        quick_intent_id: descriptor.quick_intent_id,
      }));
      quickIntents.appendChild(button);
    }
    setIntentEnabled(true);
  } catch (error) {
    quickIntentCatalog = null;
    setIntentEnabled(false);
    showError(intentResult, error);
  }
}

async function generateWithIntent(intentRequest) {
  if (!quickIntentCatalog || intentRequest.project_id !== activeProjectId) {
    showError(intentResult, new Error("Reload this project's current intent catalog."));
    return;
  }
  const requestedProject = activeProjectId;
  const requestedCatalog = quickIntentCatalog.fingerprint;
  setIntentEnabled(false);
  intentResult.replaceChildren();
  const planning = document.createElement("p");
  planning.className = "muted";
  appendText(planning, "Resolving intent and validating a component plan...");
  intentResult.appendChild(planning);
  try {
    const documentValue = await api(
      `/api/v3/generative/projects/${encodeURIComponent(requestedProject)}/workspace`,
      {
        method: "POST",
        body: JSON.stringify({
          schema_version: "1.0",
          quick_catalog_fingerprint: requestedCatalog,
          intent_request: intentRequest,
        }),
      },
    );
    if (activeProjectId !== requestedProject) {
      return;
    }
    if (documentValue.status !== "generated") {
      renderGenerationFailure(documentValue);
      return;
    }
    currentDocument = documentValue;
    renderWorkspace(documentValue);
    const mode = documentValue.planning.provenance.mode.replaceAll("_", " ");
    intentResult.replaceChildren();
    const accepted = document.createElement("p");
    accepted.className = "generation-accepted";
    appendText(accepted, `Generated from verified evidence · ${mode} · no execution authority.`);
    intentResult.appendChild(accepted);
    const route = generatedWorkspaceHash(documentValue);
    history.pushState({route}, "", route);
  } catch (error) {
    showError(intentResult, error);
    if (error instanceof Error && error.message.includes("current trusted surface")) {
      quickIntentCatalog = null;
    }
  } finally {
    if (activeProjectId === requestedProject && quickIntentCatalog) {
      setIntentEnabled(true);
    }
  }
}

function renderGenerationFailure(documentValue) {
  intentResult.replaceChildren();
  const alert = document.createElement("div");
  alert.className = "generation-failure";
  alert.setAttribute("role", "alert");
  const heading = document.createElement("strong");
  appendText(heading, documentValue.status.replaceAll("_", " "));
  alert.append(heading, fixedFields(documentValue, ["reason_code", "snapshot_revision"]));
  if ((documentValue.entity_candidates || []).length > 0) {
    alert.appendChild(titledSection(
      "Choose a registered identity and ask again",
      fixedRows(documentValue.entity_candidates, ["entity_id", "entity_kind"]),
    ));
  }
  intentResult.appendChild(alert);
}

async function loadProjects() {
  clearProjectContext();
  setBusy(true);
  try {
    const discovery = await api("/api/v2/workspace/projects");
    projectSelect.replaceChildren();
    for (const project of discovery.projects) {
      const option = document.createElement("option");
      option.value = project.project_id;
      appendText(option, `${project.project_id} · r${project.revision}`);
      projectSelect.appendChild(option);
    }
    const available = discovery.projects.length > 0;
    projectSelect.disabled = !available;
    loadButton.disabled = !available;
    for (const button of viewButtons) {
      button.disabled = !available;
    }
    connectionStatus.textContent = available
      ? "Authenticated. Every view will revalidate current project evidence."
      : "Authenticated. No authoritative projects were found.";
    if (!available) {
      setBusy(false);
      return;
    }
    const deepLink = parseWorkspaceHash();
    if (deepLink && discovery.projects.some((item) => item.project_id === deepLink.project_id)) {
      projectSelect.value = deepLink.project_id;
      if (deepLink.generation_id) {
        await loadGeneratedWorkspace(deepLink, "replace");
      } else {
        await loadWorkspace(deepLink, "replace");
      }
    } else {
      await loadWorkspace(defaultQuery(projectSelect.value), "replace");
    }
  } catch (error) {
    projectSelect.disabled = true;
    loadButton.disabled = true;
    for (const button of viewButtons) {
      button.disabled = true;
    }
    currentDocument = null;
    setBusy(false);
    showError(connectionStatus, error);
  }
}

async function loadWorkspace(query, historyMode = "push") {
  const canonical = validateIdentityQuery(query);
  if (activeProjectId !== canonical.project_id) {
    clearProjectContext(canonical.project_id);
  } else {
    resetCatalogs();
  }
  setBusy(true);
  try {
    const documentValue = await api(workspacePath(canonical));
    currentDocument = documentValue;
    projectSelect.value = documentValue.query.project_id;
    renderWorkspace(documentValue);
    if (historyMode !== "none") {
      const route = workspaceHash(documentValue.query);
      if (historyMode === "replace") {
        history.replaceState({route}, "", route);
      } else {
        history.pushState({route}, "", route);
      }
    }
    connectionStatus.textContent = "Current content-addressed workspace loaded.";
    if (!quickIntentCatalog
        || quickIntentCatalog.snapshot.snapshot_sha256 !== documentValue.freshness.snapshot_sha256) {
      await loadQuickIntents(documentValue.query.project_id);
    }
  } catch (error) {
    currentDocument = null;
    setBusy(false);
    freshness.textContent = "Workspace freshness could not be verified.";
    showError(workspace, error);
    workspace.focus({preventScroll: true});
  }
}

async function loadGeneratedWorkspace(route, historyMode = "push") {
  if (!validProjectId(route.project_id) || !validEntryId(route.generation_id)) {
    throw new Error("Generated workspace identity is invalid.");
  }
  if (activeProjectId !== route.project_id) {
    clearProjectContext(route.project_id);
  }
  setBusy(true);
  try {
    const documentValue = await api(
      `/api/v3/generative/projects/${encodeURIComponent(route.project_id)}`
      + `/generations/${encodeURIComponent(route.generation_id)}`,
    );
    if (documentValue.status !== "generated") {
      throw new Error("The retained generation is not renderable.");
    }
    currentDocument = documentValue;
    projectSelect.value = documentValue.project_id;
    renderWorkspace(documentValue);
    if (historyMode !== "none") {
      const hash = generatedWorkspaceHash(documentValue);
      if (historyMode === "replace") {
        history.replaceState({route: hash}, "", hash);
      } else {
        history.pushState({route: hash}, "", hash);
      }
    }
    connectionStatus.textContent = "Retained generated workspace revalidated.";
    if (!quickIntentCatalog) {
      await loadQuickIntents(documentValue.project_id);
    }
  } catch (error) {
    currentDocument = null;
    setBusy(false);
    freshness.textContent = "Generated workspace freshness could not be verified.";
    showError(workspace, error);
    workspace.focus({preventScroll: true});
  }
}

async function activateView(view) {
  const projectId = currentProjectId();
  if (!projectId) {
    return;
  }
  if (view === "run-comparison" && runCatalog.length < 2) {
    const explorer = await api(workspacePath({
      view: "run-stage-explorer",
      project_id: projectId,
    }));
    updateCatalogs(explorer);
  }
  if (view === "run-comparison") {
    if (runCatalog.length < 2) {
      showError(workspace, new Error("Two registered runs are required for comparison."));
      return;
    }
    await loadWorkspace({
      view,
      project_id: projectId,
      baseline_run_id: runCatalog[0],
      candidate_run_id: runCatalog[1],
    });
    return;
  }
  await loadWorkspace({view, project_id: projectId});
}

function currentProjectId() {
  return activeProjectId || projectSelect.value || currentDocument?.project_id
    || currentDocument?.query?.project_id || "";
}

function defaultQuery(projectId) {
  return {view: "project-progress", project_id: projectId};
}

function validateIdentityQuery(query) {
  if (!query || !workspaceViews.has(query.view) || !validProjectId(query.project_id)) {
    throw new Error("Workspace navigation identity is invalid.");
  }
  const result = {view: query.view, project_id: query.project_id};
  for (const key of ["run_id", "paper_id", "baseline_run_id", "candidate_run_id"]) {
    if (query[key] !== undefined) {
      if (!validEntryId(query[key])) {
        throw new Error("Workspace selection identity is invalid.");
      }
      result[key] = query[key];
    }
  }
  if (result.view === "run-comparison"
      && (!result.baseline_run_id || !result.candidate_run_id
          || result.baseline_run_id === result.candidate_run_id)) {
    throw new Error("Run comparison requires two distinct registered identities.");
  }
  return result;
}

function validProjectId(value) {
  return typeof value === "string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
}

function validEntryId(value) {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value)
    && value !== "." && value !== "..";
}

function workspacePath(query) {
  const base = `/api/v2/workspace/projects/${encodeURIComponent(query.project_id)}/${query.view}`;
  if (query.view === "run-stage-explorer" && query.run_id) {
    return `${base}/runs/${encodeURIComponent(query.run_id)}`;
  }
  if (query.view === "paper-evidence" && query.paper_id) {
    return `${base}/papers/${encodeURIComponent(query.paper_id)}`;
  }
  if (query.view === "run-comparison") {
    return `${base}/runs/${encodeURIComponent(query.baseline_run_id)}/${encodeURIComponent(query.candidate_run_id)}`;
  }
  if (query.view === "blockers" && query.run_id) {
    return `${base}/runs/${encodeURIComponent(query.run_id)}`;
  }
  return base;
}

function workspaceHash(query) {
  return `#${workspacePath(query).replace("/api/v2/workspace", "")}`;
}

function generatedWorkspaceHash(documentValue) {
  return `#/projects/${encodeURIComponent(documentValue.project_id)}`
    + `/generated/${encodeURIComponent(documentValue.renderer.surface_id)}`;
}

function parseWorkspaceHash() {
  const prefix = "#/projects/";
  if (!location.hash.startsWith(prefix)) {
    return null;
  }
  let parts;
  try {
    parts = location.hash.slice(prefix.length).split("/").map(decodeURIComponent);
  } catch {
    return null;
  }
  if (parts.length < 2) {
    return null;
  }
  const [projectId, view, marker, first, second] = parts;
  if (view === "generated" && marker && parts.length === 3) {
    if (!validProjectId(projectId) || !validEntryId(marker)) {
      return null;
    }
    return {project_id: projectId, generation_id: marker};
  }
  let query = {project_id: projectId, view};
  if (view === "run-stage-explorer" && marker === "runs" && first && !second) {
    query = {...query, run_id: first};
  } else if (view === "paper-evidence" && marker === "papers" && first && !second) {
    query = {...query, paper_id: first};
  } else if (view === "run-comparison" && marker === "runs" && first && second) {
    query = {...query, baseline_run_id: first, candidate_run_id: second};
  } else if (view === "blockers" && marker === "runs" && first && !second) {
    query = {...query, run_id: first};
  } else if (parts.length !== 2) {
    return null;
  }
  try {
    return validateIdentityQuery(query);
  } catch {
    return null;
  }
}

async function api(path, options = {}) {
  const headers = {Authorization: `Bearer ${tokenInput.value}`};
  const cached = responseCache.get(path);
  if ((options.method === undefined || options.method === "GET") && cached) {
    headers["If-None-Match"] = cached.etag;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {...options, headers});
  if (response.status === 304 && cached) {
    return cached.payload;
  }
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error?.message || "The trusted receiver rejected the request.");
  }
  const etag = response.headers.get("ETag");
  if (etag && (options.method === undefined || options.method === "GET")) {
    responseCache.set(path, {etag, payload});
  }
  return payload;
}

function setBusy(isBusy) {
  workspace.setAttribute("aria-busy", isBusy ? "true" : "false");
  connectButton.disabled = isBusy;
}

function showError(container, error) {
  container.replaceChildren();
  const message = document.createElement("p");
  message.className = "error-text";
  message.setAttribute("role", "alert");
  appendText(message, error instanceof Error ? error.message : "Request failed.");
  container.appendChild(message);
}

connectButton.addEventListener("click", loadProjects);
tokenInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    loadProjects();
  }
});
loadButton.addEventListener("click", () => loadWorkspace(defaultQuery(projectSelect.value)));
projectSelect.addEventListener("change", () => {
  clearProjectContext(projectSelect.value);
});
intentForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!quickIntentCatalog) {
    return;
  }
  const question = intentQuestion.value.trim();
  if (!question) {
    showError(intentResult, new Error("Enter a question before generating a workspace."));
    return;
  }
  intentQuestion.value = "";
  generateWithIntent({
    schema_version: "1.0",
    kind: "free_question",
    project_id: quickIntentCatalog.snapshot.project_id,
    snapshot_revision: quickIntentCatalog.snapshot.snapshot_revision,
    snapshot_sha256: quickIntentCatalog.snapshot.snapshot_sha256,
    question,
  });
});
for (const button of viewButtons) {
  button.addEventListener("click", () => activateView(button.dataset.view));
}
openRunButton.addEventListener("click", () => loadWorkspace({
  view: "run-stage-explorer",
  project_id: currentProjectId(),
  run_id: runSelect.value,
}));
openPaperButton.addEventListener("click", () => loadWorkspace({
  view: "paper-evidence",
  project_id: currentProjectId(),
  paper_id: paperSelect.value,
}));
compareRunsButton.addEventListener("click", () => loadWorkspace({
  view: "run-comparison",
  project_id: currentProjectId(),
  baseline_run_id: baselineRun.value,
  candidate_run_id: candidateRun.value,
}));
window.addEventListener("popstate", () => {
  const route = parseWorkspaceHash();
  if (route && tokenInput.value) {
    if (route.generation_id) {
      loadGeneratedWorkspace(route, "none");
    } else {
      loadWorkspace(route, "none");
    }
  }
});
