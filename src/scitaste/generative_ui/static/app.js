import {
  localeFromHash,
  normalizeLocale,
  routeFromHash,
  supportedLocales,
  translateMessage,
  validateCatalogs,
  withLocale,
} from "/assets/locale.js";

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
const localeSelect = document.getElementById("locale-select");
const skipLink = document.querySelector(".skip-link");

const localeAssetPaths = Object.freeze({
  en: "/assets/locales/en.json",
  "zh-CN": "/assets/locales/zh-CN.json",
});
const localeCatalogs = {en: Object.freeze({}), "zh-CN": Object.freeze({})};
const quickIntentLabelKeys = Object.freeze({
  "review-observed-project-progress": "quick.progress",
  "diagnose-blocked-and-failed-runs": "quick.blockers",
  "compare-latest-registered-run-records": "quick.comparison",
  "review-registered-paper-evidence": "quick.paper",
  "review-manifest-declared-next-gate": "quick.next_gate",
  "review-autoresearch-evaluation-landscape": "quick.research_landscape",
});
let activeLocale = localeFromFragment() || browserLocale();

const workspaceViews = Object.freeze(new Set([
  "project-progress",
  "research-landscape",
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
let lastProposalReceipt = null;
let lastControllerDecision = null;
let lastArtifactPreview = null;
let intentResultState = {kind: "empty"};
let connectionStatusKey = "connection.credential_required";
let freshnessStatusKey = "freshness.none";
let connectionStatusError = null;

function browserLocale() {
  return String(navigator.language || "en").toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

function fragmentParts(hash = location.hash) {
  return {route: routeFromHash(hash)};
}

function localeFromFragment(hash = location.hash) {
  return localeFromHash(hash);
}

function localizedHash(route) {
  return withLocale(route, activeLocale);
}

function replaceHashLocale() {
  const route = localizedHash(location.hash || "#/");
  history.replaceState({...history.state, route}, "", route);
}

function hasTranslation(key, locale = activeLocale) {
  return typeof localeCatalogs[locale]?.[key] === "string"
    || typeof localeCatalogs.en[key] === "string";
}

function t(key, values = {}) {
  return translateMessage(localeCatalogs, activeLocale, key, values);
}

function countMessage(base, count) {
  return t(`${base}.${count === 1 ? "one" : "many"}`, {count});
}

function fieldLabel(name) {
  const key = `field.${name}`;
  return hasTranslation(key) ? t(key) : name.replaceAll("_", " ");
}

function localizedCode(value) {
  const normalized = String(value ?? "none");
  const key = `code.${normalized}`;
  return hasTranslation(key) ? t(key) : readableCode(normalized);
}

function uiError(key) {
  const error = new Error(t(key));
  error.translationKey = key;
  return error;
}

function localizeStaticShell() {
  document.documentElement.lang = activeLocale;
  document.title = t("document.title");
  localeSelect.value = activeLocale;
  for (const element of document.querySelectorAll("[data-i18n]")) {
    element.textContent = t(element.dataset.i18n);
  }
  for (const element of document.querySelectorAll("[data-i18n-aria]")) {
    element.setAttribute("aria-label", t(element.dataset.i18nAria));
  }
  for (const element of document.querySelectorAll("[data-i18n-placeholder]")) {
    element.setAttribute("placeholder", t(element.dataset.i18nPlaceholder));
  }
  for (const element of document.querySelectorAll("[data-error-key]")) {
    element.textContent = t(element.dataset.errorKey);
  }
}

function setConnectionStatus(key) {
  connectionStatusKey = key;
  connectionStatusError = null;
  connectionStatus.textContent = t(key);
}

function setFreshnessStatus(key) {
  freshnessStatusKey = key;
  freshness.textContent = t(key);
}

async function loadLocaleCatalogs() {
  const entries = await Promise.all(Object.entries(localeAssetPaths).map(async ([locale, path]) => {
    const response = await fetch(path, {cache: "no-store"});
    if (!response.ok) {
      throw new Error(`Locale catalog ${locale} could not be loaded.`);
    }
    const catalog = await response.json();
    if (!catalog || Array.isArray(catalog) || typeof catalog !== "object") {
      throw new Error(`Locale catalog ${locale} is invalid.`);
    }
    return [locale, Object.freeze(catalog)];
  }));
  for (const [locale, catalog] of entries) {
    localeCatalogs[locale] = catalog;
  }
  validateCatalogs(localeCatalogs);
}

function appendText(parent, value) {
  parent.appendChild(document.createTextNode(formatValue(value)));
}

function formatValue(value) {
  if (value === null || value === undefined) {
    return t("common.missing");
  }
  if (typeof value === "boolean") {
    return value ? t("common.yes") : t("common.no");
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
    appendText(term, fieldLabel(name));
    const description = document.createElement("dd");
    appendText(description, localizeFieldValue(name, data[name]));
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

const localizableValueFields = Object.freeze(new Set([
  "execution_authority",
  "metrics_state",
  "next_boundary",
  "observed_state",
  "paper_status",
  "planner_mode",
  "preview_kind",
  "recorded_status",
  "reported_status",
  "run_status",
  "stage_state",
  "state",
  "status",
]));

function localizeFieldValue(name, value) {
  if (localizableValueFields.has(name) && typeof value === "string") {
    return localizedCode(value);
  }
  return value;
}

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
  appendText(pill, label || t(`progress.state.${state}`));
  return pill;
}

function evidenceDisclosure(refIds, fields = null) {
  const details = document.createElement("details");
  details.className = "evidence-disclosure";
  const summary = document.createElement("summary");
  const references = Array.from(new Set(refIds || []));
  appendText(summary, countMessage("common.records", references.length));
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
    t("progress.distribution.title"),
    t("progress.distribution.subtitle"),
  );
  const definitions = [
    ["observed_completed", t("progress.distribution.completed"), counts.runs_completed],
    ["current_work", t("progress.distribution.active"), counts.runs_active],
    ["candidate", t("progress.distribution.candidate"), counts.runs_candidates],
    ["blocked", t("progress.distribution.blocked"), counts.runs_blocked],
    ["failed", t("progress.distribution.failed"), counts.runs_failed],
    ["unavailable", t("progress.distribution.unavailable"), counts.runs_unavailable],
    ["unknown", t("progress.distribution.unknown"), counts.runs_unknown],
  ];
  const distribution = document.createElement("div");
  distribution.className = "run-distribution";
  distribution.setAttribute("role", "img");
  distribution.setAttribute("aria-label", definitions
    .filter(([, , count]) => count > 0)
    .map(([, label, count]) => `${label}: ${count}`)
    .join(activeLocale === "zh-CN" ? "，" : ", ") || t("progress.distribution.aria_empty"));
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
    appendText(unavailable, t("progress.no_reason_run"));
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
    appendText(selected, t("progress.selected_run"));
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
    showError(intentResult, uiError("error.reload_catalog"));
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
    appendText(button, `${run.run_id} · ${localizedCode(run.outcome)}`);
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
  container.appendChild(titledSection(t("run.registered"), runList));

  if (data.stages.length > 0) {
    const stages = document.createElement("ol");
    stages.className = "stage-list";
    for (const stage of data.stages) {
      const item = document.createElement("li");
      const heading = document.createElement("strong");
      appendText(heading, t("run.stage_heading", {
        stage: stage.stage,
        label: activeLocale === "zh-CN" ? stage.label_zh : stage.label_en,
      }));
      item.append(heading, fixedFields(stage, [
        "status",
        "artifact_count",
        "output_locator",
        "summary_code",
      ]));
      stages.appendChild(item);
    }
    container.appendChild(titledSection(t("run.stage_outputs"), stages));
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
    titledSection(t("selection.baseline"), fixedFields(data.baseline, [
      "run_id", "status", "provider", "model_name", "condition", "seed", "evidence_scope",
    ])),
    titledSection(t("selection.candidate"), fixedFields(data.candidate, [
      "run_id", "status", "provider", "model_name", "condition", "seed", "evidence_scope",
    ])),
    titledSection(t("comparison.metrics"), fixedFields(data, [
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
  appendText(button, t("artifact.inspect"));
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
  appendText(statusLabel, t("project.recorded_status"));
  status.append(statusLabel, progressPill(data.project_status, localizedCode(data.project_status)));
  const focus = document.createElement("p");
  focus.className = "project-focus-copy";
  appendText(focus, data.current_focus);
  const publication = document.createElement("p");
  publication.className = "availability-note";
  appendText(publication, data.publication_ready
    ? t("project.publication_ready")
    : t("project.publication_unready"));
  container.append(status, focus, publication, evidenceDisclosure([data.project_ref_id]));
  return container;
}

function renderRunHealth(data) {
  const container = document.createElement("div");
  container.className = "run-health-summary";
  const state = ["complete", "completed", "succeeded", "success"].includes(data.run_status)
    ? "observed_completed"
    : data.run_status;
  container.appendChild(progressPill(state, localizedCode(data.run_status)));
  const facts = document.createElement("div");
  facts.className = "health-facts";
  const factValues = [
    [t("health.failure_stage"), data.failure_stage],
    [t("health.retry_safe"), data.retry_safe],
    [t("health.schema_valid"), data.schema_valid],
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
  appendText(summary, t("blocker.summary", {count: data.blockers.length}));
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
      appendText(reason, t("blocker.no_reason"));
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

function researchLabel(item) {
  return activeLocale === "zh-CN" ? item.label_zh : item.label_en;
}

function landscapeStatePill(state, namespace = "landscape") {
  const pill = document.createElement("span");
  pill.className = `landscape-pill state-${state}`;
  appendText(pill, t(`${namespace}.${state}`));
  return pill;
}

function renderLandscapeTable(data, works) {
  const scroll = document.createElement("div");
  scroll.className = "landscape-matrix-scroll";
  const table = document.createElement("table");
  table.className = "landscape-matrix";
  const head = document.createElement("thead");
  const headingRow = document.createElement("tr");
  const workHeading = document.createElement("th");
  workHeading.scope = "col";
  appendText(workHeading, t("landscape.work"));
  headingRow.appendChild(workHeading);
  for (const stage of data.stages) {
    const cell = document.createElement("th");
    cell.scope = "col";
    appendText(cell, researchLabel(stage));
    headingRow.appendChild(cell);
  }
  const signalHeading = document.createElement("th");
  signalHeading.scope = "col";
  appendText(signalHeading, t("landscape.signal"));
  headingRow.appendChild(signalHeading);
  head.appendChild(headingRow);
  const body = document.createElement("tbody");
  for (const work of works) {
    const row = document.createElement("tr");
    row.className = `landscape-work role-${work.role}`;
    const identity = document.createElement("th");
    identity.scope = "row";
    const name = document.createElement("strong");
    appendText(name, work.name);
    const venue = document.createElement("small");
    appendText(venue, work.venue);
    identity.append(name, venue);
    row.appendChild(identity);
    for (const stage of data.stages) {
      const covered = work.stage_ids.includes(stage.stage_id);
      const cell = document.createElement("td");
      const mark = document.createElement("span");
      mark.className = covered ? "coverage-mark covered" : "coverage-mark";
      mark.setAttribute("aria-label", covered
        ? t("landscape.covered", {stage: researchLabel(stage)})
        : t("landscape.not_covered", {stage: researchLabel(stage)}));
      appendText(mark, covered ? "●" : "·");
      cell.appendChild(mark);
      row.appendChild(cell);
    }
    const signal = document.createElement("td");
    const signalTag = document.createElement("span");
    signalTag.className = `signal-tag signal-${work.execution_signal}`;
    appendText(signalTag, t(`landscape.signal.${work.execution_signal}`));
    const resource = document.createElement("small");
    resource.className = "resource-tier";
    appendText(resource, t(`landscape.resource.${work.resource_tier}`));
    signal.append(signalTag, resource);
    row.appendChild(signal);
    body.appendChild(row);
  }
  table.append(head, body);
  scroll.appendChild(table);
  return scroll;
}

function renderResearchLandscape(data) {
  const container = document.createElement("div");
  container.className = "research-landscape";

  const gate = document.createElement("section");
  gate.className = `landscape-decision state-${data.freeze_decision}`;
  const decisionCopy = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow dark";
  appendText(eyebrow, t("landscape.decision.eyebrow"));
  const heading = document.createElement("h3");
  appendText(heading, t(`landscape.decision.${data.freeze_decision}`));
  decisionCopy.append(eyebrow, heading);
  const synthesis = document.createElement("div");
  synthesis.className = "landscape-counts";
  for (const [value, label] of [
    [data.works.length, t("landscape.count.works")],
    [data.stages.length, t("landscape.count.stages")],
    [data.lenses.length, t("landscape.count.lenses")],
  ]) {
    const item = document.createElement("span");
    const number = document.createElement("strong");
    appendText(number, value);
    const copy = document.createElement("small");
    appendText(copy, label);
    item.append(number, copy);
    synthesis.appendChild(item);
  }
  gate.append(decisionCopy, synthesis);

  const lenses = progressSection(t("landscape.lenses.title"), t("landscape.lenses.subtitle"));
  const lensGrid = document.createElement("div");
  lensGrid.className = "landscape-lenses";
  for (const lens of data.lenses) {
    const item = document.createElement("article");
    const symbol = document.createElement("span");
    symbol.className = "lens-symbol";
    appendText(symbol, lens.symbol);
    const copy = document.createElement("div");
    const label = document.createElement("strong");
    appendText(label, researchLabel(lens));
    const question = document.createElement("small");
    appendText(question, activeLocale === "zh-CN" ? lens.question_zh : lens.question_en);
    copy.append(label, question);
    item.append(symbol, copy);
    lensGrid.appendChild(item);
  }
  lenses.appendChild(lensGrid);

  const map = progressSection(t("landscape.matrix.title"), t("landscape.matrix.subtitle"));
  const foreground = data.works.filter((work) => work.role !== "context");
  const context = data.works.filter((work) => work.role === "context");
  map.appendChild(renderLandscapeTable(data, foreground));
  if (context.length > 0) {
    const more = document.createElement("details");
    more.className = "landscape-context";
    const summary = document.createElement("summary");
    appendText(summary, t("landscape.matrix.more", {count: context.length}));
    more.append(summary, renderLandscapeTable(data, context));
    map.appendChild(more);
  }

  const candidateSection = progressSection(
    t("landscape.candidates.title"),
    t("landscape.candidates.subtitle"),
  );
  const lanes = document.createElement("div");
  lanes.className = "readiness-lanes";
  for (const readiness of ["reference", "adaptation", "formal"]) {
    const lane = document.createElement("section");
    lane.className = `readiness-lane readiness-${readiness}`;
    const laneHeading = document.createElement("h4");
    appendText(laneHeading, t(`landscape.readiness.${readiness}`));
    lane.appendChild(laneHeading);
    for (const candidate of data.comparison_candidates.filter(
      (item) => item.readiness === readiness,
    )) {
      const card = document.createElement("article");
      const name = document.createElement("strong");
      appendText(name, candidate.name);
      const meta = document.createElement("small");
      appendText(meta, `${t(`landscape.kind.${candidate.candidate_kind}`)} · ${t(`landscape.role.${candidate.role}`)}`);
      const barrier = document.createElement("span");
      barrier.className = "barrier-code";
      appendText(barrier, localizedCode(candidate.barrier_code));
      card.append(name, meta, barrier);
      lane.appendChild(card);
    }
    if (!lane.querySelector("article")) {
      const empty = document.createElement("p");
      empty.className = "lane-empty";
      appendText(empty, t("landscape.readiness.none"));
      lane.appendChild(empty);
    }
    lanes.appendChild(lane);
  }
  candidateSection.appendChild(lanes);

  const planning = progressSection(t("landscape.gates.title"), t("landscape.gates.subtitle"));
  const gateRail = document.createElement("ol");
  gateRail.className = "planning-gate-rail";
  for (const item of data.planning_gates) {
    const node = document.createElement("li");
    node.className = `gate-node state-${item.state}`;
    const marker = document.createElement("span");
    marker.className = "gate-marker";
    marker.setAttribute("aria-hidden", "true");
    const label = document.createElement("strong");
    appendText(label, researchLabel(item));
    node.append(marker, label, landscapeStatePill(item.state, "landscape.gate"));
    gateRail.appendChild(node);
  }
  const unresolved = document.createElement("details");
  unresolved.className = "landscape-open-questions";
  const unresolvedSummary = document.createElement("summary");
  appendText(unresolvedSummary, t("landscape.questions", {count: data.open_questions.length}));
  const questionList = document.createElement("ol");
  for (const question of data.open_questions) {
    const item = document.createElement("li");
    appendText(item, researchLabel(question));
    questionList.appendChild(item);
  }
  unresolved.append(unresolvedSummary, questionList);
  planning.append(gateRail, unresolved);

  container.append(
    gate,
    lenses,
    map,
    candidateSection,
    planning,
    evidenceDisclosure(data.support_ref_ids, {
      data: {
        synthesis_scope: data.synthesis_scope,
        source_document: data.source_document,
        source_document_sha256: data.source_document_sha256,
        decision_reason_code: data.decision_reason_code,
      },
      names: [
        "synthesis_scope",
        "source_document",
        "source_document_sha256",
        "decision_reason_code",
      ],
    }),
  );
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
  appendText(heroLabel, t("progress.canonical"));
  heroTop.append(heroLabel, progressPill(data.project_state));
  const summary = document.createElement("p");
  summary.className = "progress-summary";
  const candidateClause = countMessage("progress.candidates", data.counts.runs_candidates);
  const paperClause = countMessage("progress.papers", data.counts.papers_registered);
  appendText(
    summary,
    t("progress.summary", {
      completed: data.counts.runs_completed,
      registered: data.counts.runs_registered,
      attention: attentionCount,
      candidates: candidateClause,
      papers: paperClause,
    }),
  );
  const generationHint = document.createElement("p");
  generationHint.className = "generation-hint";
  appendText(
    generationHint,
    t("progress.generation_hint"),
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
    progressMetric(t("progress.metric.registered"), data.counts.runs_registered, t("progress.metric.registered_note")),
    progressMetric(t("progress.metric.completed"), data.counts.runs_completed, t("progress.metric.completed_note"), "positive"),
    progressMetric(t("progress.metric.attention"), attentionCount, t("progress.metric.attention_note"), attentionCount ? "warning" : "positive"),
    progressMetric(t("progress.metric.candidates"), data.counts.runs_candidates, t("progress.metric.candidates_note"), "candidate"),
    progressMetric(t("progress.metric.stages"), data.counts.completed_stages, t("progress.metric.stages_note")),
    progressMetric(t("progress.metric.papers"), data.counts.papers_registered, t("progress.metric.papers_note")),
  );
  container.append(hero, metrics, renderRunDistribution(data.counts));

  const direction = progressSection(t("progress.direction.title"), t("progress.direction.subtitle"));
  const directionGrid = document.createElement("div");
  directionGrid.className = "direction-grid";
  const focus = document.createElement("article");
  const focusLabel = document.createElement("span");
  focusLabel.className = "card-label";
  appendText(focusLabel, t("progress.current_focus"));
  const focusValue = document.createElement("strong");
  appendText(focusValue, data.focus);
  const focusStatus = document.createElement("small");
  appendText(focusStatus, localizedCode(data.focus_status));
  focus.append(focusLabel, focusValue, focusStatus, evidenceDisclosure(data.focus_ref_ids));
  const gate = document.createElement("article");
  const gateLabel = document.createElement("span");
  gateLabel.className = "card-label";
  appendText(gateLabel, t("progress.next_gate"));
  const gateValue = document.createElement("strong");
  appendText(gateValue, data.next_gate || t("progress.no_next_gate"));
  gate.append(gateLabel, gateValue);
  directionGrid.append(focus, gate);
  if (data.current_run_id) {
    const currentRun = document.createElement("article");
    currentRun.className = "current-run-card";
    const runCopy = document.createElement("div");
    const runLabel = document.createElement("span");
    runLabel.className = "card-label";
    appendText(runLabel, t("progress.selected_not_execution"));
    const runValue = document.createElement("strong");
    appendText(runValue, compactRunLabel(data.current_run_id));
    runCopy.append(runLabel, runValue, evidenceDisclosure(data.current_run_ref_ids, {
      data: {run_id: data.current_run_id, recorded_status: data.current_run_status},
      names: ["run_id", "recorded_status"],
    }));
    const openRun = document.createElement("button");
    openRun.type = "button";
    openRun.className = "secondary-button";
    appendText(openRun, t("progress.open_run"));
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
    const attention = progressSection(
      t("progress.attention.title"),
      t("progress.attention.subtitle", {count: data.attention.length}),
    );
    const attentionList = document.createElement("div");
    attentionList.className = "attention-list";
    for (const item of data.attention) {
      attentionList.appendChild(renderAttentionItem(item));
    }
    attention.appendChild(attentionList);
    standing.appendChild(attention);
  }

  const milestones = progressSection(
    t("progress.timeline.title"),
    data.milestones.length > 0
      ? t("progress.timeline.subtitle", {count: data.milestones.length})
      : t("progress.timeline.empty"),
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
    t("progress.activity.title"),
    t("progress.activity.subtitle", {count: data.activity_total}),
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
    appendText(moreSummary, t("progress.activity.more", {
      count: data.recent_activity.length - 4,
    }));
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
    appendText(truncated, t("progress.activity.truncated"));
    activity.appendChild(truncated);
  }
  activityAndNext.appendChild(activity);

  const nextSteps = progressSection(
    t("progress.next.title"),
    t("progress.next.subtitle"),
  );
  const candidateLabels = {
    review_progress: t("progress.next.review"),
    diagnose_blockers: t("progress.next.blockers"),
    compare_runs: t("progress.next.compare"),
    review_paper_evidence: t("progress.next.paper"),
    review_next_gate: t("progress.next.gate"),
    review_research_landscape: t("progress.next.research_landscape"),
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
    appendText(note, t("progress.next.meta", {
      targets: countMessage("common.targets", candidate.target_ids.length),
      evidence: countMessage("common.records", candidate.support_ref_ids.length),
    }));
    button.append(label, note);
    button.addEventListener("click", () => requestCandidateWorkspace(candidate.candidate_id));
    candidateList.appendChild(button);
  }
  nextSteps.appendChild(candidateList);

  const availability = document.createElement("div");
  availability.className = "availability-note";
  if (data.stages.length > 0) {
    appendText(availability, t("progress.availability.stages", {count: data.stages.length}));
  } else if (data.stage_semantics === "self-development-milestones-not-autoresearchclaw-stages") {
    appendText(availability, t("progress.availability.self_development"));
  } else {
    appendText(availability, t("progress.availability.stage_state", {
      state: localizedCode(data.stage_state),
    }));
  }
  if (data.papers.length > 0) {
    appendText(availability, t("progress.availability.papers", {count: data.papers.length}));
  } else {
    appendText(availability, t("progress.availability.no_paper"));
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
  ResearchLandscapeMap: renderResearchLandscape,
});

function workspaceTitle(documentValue) {
  if (documentValue.status === "generated") {
    return t(`title.generated.${documentValue.intent.goal}`);
  }
  return t(`title.${documentValue.query.view}`);
}

function componentTitle(component) {
  if (component.renderer === "ProjectSummaryCard") {
    return component.title;
  }
  const key = `component.${component.renderer}`;
  return hasTranslation(key) ? t(key) : component.title;
}

function placementExplanation(placement) {
  const key = `placement.${placement.reason_code}`;
  return hasTranslation(key) ? t(key) : placement.explanation;
}

function actionLabel(action) {
  const key = `action.${action.proposal?.payload?.kind}`;
  return hasTranslation(key) ? t(key) : action.label;
}

function renderWorkspace(documentValue, {preserveTransient = false, focus = true} = {}) {
  const renderer = documentValue.renderer;
  const generated = documentValue.status === "generated";
  const placements = new Map((documentValue.placements || []).map(
    (item) => [item.component_id, item],
  ));
  workspace.classList.toggle("generated-workspace", generated);
  workspace.replaceChildren();
  if (!preserveTransient) {
    lastProposalReceipt = null;
    lastControllerDecision = null;
    lastArtifactPreview = null;
  }
  renderProposalResult();
  renderArtifactResult();
  if (generated) {
    workspace.appendChild(renderGenerationSummary(documentValue));
  }
  if (!generated) {
    const title = document.createElement("h2");
    title.className = "workspace-title";
    appendText(title, workspaceTitle(documentValue));
    workspace.appendChild(title);
  }
  const cards = new Map();
  for (const component of renderer.components) {
    const renderComponent = componentRenderers[component.renderer];
    if (typeof renderComponent !== "function") {
      throw uiError("workspace.unknown_component");
    }
    const card = document.createElement("section");
    card.className = "component-card";
    const placement = placements.get(component.component_id);
    if (placement) {
      card.classList.add(`plan-group-${placement.group}`);
      card.classList.add(`plan-emphasis-${placement.emphasis}`);
    }
    const heading = document.createElement("h2");
    appendText(heading, componentTitle(component));
    card.append(heading, renderComponent(component.data));
    if (placement) {
      const explanation = document.createElement("p");
      explanation.className = "placement-explanation";
      appendText(explanation, placementExplanation(placement));
      card.appendChild(explanation);
    }
    workspace.appendChild(card);
    cards.set(component.component_id, card);
  }
  for (const action of renderer.actions) {
    const card = cards.get(action.component_id);
    if (!card) {
      throw uiError("workspace.orphan_action");
    }
    let actions = card.querySelector(".component-actions");
    if (!actions) {
      actions = document.createElement("div");
      actions.className = "component-actions";
      card.appendChild(actions);
    }
    const button = document.createElement("button");
    button.type = "button";
    appendText(button, actionLabel(action));
    button.addEventListener("click", () => submitAction(action));
    actions.appendChild(button);
  }
  updateCatalogs(documentValue);
  updateFreshness(documentValue);
  updateActiveView(generated ? null : documentValue.query.view);
  workspace.setAttribute("aria-busy", "false");
  if (focus) {
    workspace.focus({preventScroll: true});
    workspace.scrollIntoView({block: "start"});
  }
}

function renderGenerationSummary(documentValue) {
  const summary = document.createElement("section");
  summary.className = "generation-summary";
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow dark";
  appendText(eyebrow, t("generation.validated"));
  const heading = document.createElement("h2");
  appendText(heading, t(`title.generated.${documentValue.intent.goal}`));
  const planner = documentValue.planning?.provenance;
  const metadata = document.createElement("div");
  metadata.className = "generation-metadata";
  const values = [
    [t("generation.planner"), localizedCode(planner?.mode)],
    [t("generation.snapshot"), t("generation.revision", {
      revision: documentValue.snapshot_revision,
    })],
    [t("generation.authority"), t("generation.read_only")],
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
  appendText(provenanceSummary, t("generation.provenance"));
  provenance.append(provenanceSummary, fixedFields({
    reason_code: documentValue.reason_code,
    execution_authority: documentValue.execution_authority,
  }, ["reason_code", "execution_authority"]));
  summary.append(eyebrow, heading, metadata, provenance);
  return summary;
}

function updateFreshness(documentValue) {
  const state = documentValue.freshness;
  freshnessStatusKey = null;
  freshness.textContent = t("freshness.summary", {
    revision: state.project_revision,
    evidence: state.evidence_count,
    snapshot: state.snapshot_sha256.slice(0, 12),
    surface: state.surface_fingerprint.slice(0, 12),
  });
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
    lastProposalReceipt = receipt;
    lastControllerDecision = null;
    renderProposalResult();
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

function renderProposalResult() {
  proposalResult.replaceChildren();
  if (!lastProposalReceipt) {
    const empty = document.createElement("p");
    empty.className = "muted";
    appendText(empty, t("inspector.proposal_none"));
    proposalResult.appendChild(empty);
    return;
  }
  if (lastControllerDecision) {
    const outcome = document.createElement("p");
    outcome.className = "proposal-explanation";
    appendText(outcome, t("inspector.controller_recorded"));
    proposalResult.append(
      outcome,
      fixedFields(lastControllerDecision, [
        "status",
        "execution_authority",
        "next_boundary",
        "proposal_kind",
        "controller_request_id",
      ]),
    );
    return;
  }
  const explanation = document.createElement("p");
  explanation.className = "proposal-explanation";
  explanation.textContent = t("inspector.proposal_recorded");
  proposalResult.append(
    explanation,
    fixedFields(lastProposalReceipt, [
      "status",
      "execution_authority",
      "next_boundary",
      "event_id",
      "action_id",
    ]),
  );
  const controls = document.createElement("div");
  controls.className = "component-actions";
  const approve = document.createElement("button");
  approve.type = "button";
  appendText(approve, t("inspector.approve"));
  approve.addEventListener("click", () => submitControllerDecision("approve"));
  const reject = document.createElement("button");
  reject.type = "button";
  appendText(reject, t("inspector.reject"));
  reject.addEventListener("click", () => submitControllerDecision("reject"));
  controls.append(approve, reject);
  proposalResult.appendChild(controls);
}

async function submitControllerDecision(requestedDecision) {
  if (!lastProposalReceipt || !currentDocument) {
    return;
  }
  const request = {
    schema_version: "1.0",
    controller_request_id: `controller-${Date.now()}-${eventCounter++}`,
    proposal_event_id: lastProposalReceipt.event_id,
    requested_decision: requestedDecision,
    human_confirmation: requestedDecision === "approve",
  };
  try {
    lastControllerDecision = await api(interactionPath("decisions"), {
      method: "POST",
      body: JSON.stringify(request),
    });
    renderProposalResult();
  } catch (error) {
    showError(proposalResult, error);
  }
}

function clearArtifactPreview({forget = true} = {}) {
  if (artifactObjectUrl !== null) {
    URL.revokeObjectURL(artifactObjectUrl);
    artifactObjectUrl = null;
  }
  if (forget) {
    lastArtifactPreview = null;
  }
  artifactResult.replaceChildren();
}

function interactionPath(operation) {
  if (!currentDocument || !["events", "inspections", "decisions"].includes(operation)) {
    throw uiError("error.no_interaction_surface");
  }
  if (currentDocument.status === "generated") {
    const renderer = currentDocument.renderer;
    return `/api/v3/generative/projects/${encodeURIComponent(renderer.project_id)}`
      + `/generations/${encodeURIComponent(renderer.surface_id)}/${operation}`;
  }
  return `${workspacePath(currentDocument.query)}/${operation}`;
}

function renderArtifactResult() {
  if (lastArtifactPreview) {
    renderArtifactPreview(lastArtifactPreview, {remember: false});
    return;
  }
  clearArtifactPreview({forget: false});
  const empty = document.createElement("p");
  empty.className = "muted";
  appendText(empty, t("inspector.evidence_none"));
  artifactResult.appendChild(empty);
}

function renderArtifactPreview(preview, {remember = true} = {}) {
  clearArtifactPreview({forget: false});
  if (remember) {
    lastArtifactPreview = preview;
  }
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
    image.alt = t("inspector.image_alt");
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
  lastProposalReceipt = null;
  lastControllerDecision = null;
  lastArtifactPreview = null;
  intentResultState = {kind: "empty"};
  responseCache.clear();
  resetCatalogs();
  intentQuestion.value = "";
  quickIntents.replaceChildren();
  const quickMessage = document.createElement("p");
  quickMessage.className = "muted";
  appendText(quickMessage, projectId
    ? t("connection.loading_prompts")
    : t("quick.open_project"));
  quickIntents.appendChild(quickMessage);
  intentResult.replaceChildren();
  const intentMessage = document.createElement("p");
  intentMessage.className = "muted";
  appendText(intentMessage, t("generation.none"));
  intentResult.appendChild(intentMessage);
  renderProposalResult();
  clearArtifactPreview();
  renderArtifactResult();
  setFreshnessStatus("freshness.none");
  workspace.replaceChildren();
  workspace.classList.remove("generated-workspace");
  const empty = document.createElement("p");
  empty.className = "empty-state";
  appendText(empty, projectId
    ? t("workspace.open_selected")
    : t("workspace.empty"));
  workspace.appendChild(empty);
  setIntentEnabled(false);
}

function renderQuickIntents() {
  quickIntents.replaceChildren();
  if (!quickIntentCatalog) {
    const message = document.createElement("p");
    message.className = "muted";
    appendText(message, activeProjectId
      ? t("connection.loading_prompts")
      : t("quick.open_project"));
    quickIntents.appendChild(message);
    return;
  }
  for (const descriptor of quickIntentCatalog.intents) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quick-intent-button";
    button.dataset.quickIntentId = descriptor.quick_intent_id;
    const labelKey = quickIntentLabelKeys[descriptor.label_code];
    appendText(button, labelKey ? t(labelKey) : descriptor.label);
    button.addEventListener("click", () => generateWithIntent({
      schema_version: "1.0",
      kind: "quick",
      project_id: quickIntentCatalog.snapshot.project_id,
      snapshot_revision: quickIntentCatalog.snapshot.snapshot_revision,
      snapshot_sha256: quickIntentCatalog.snapshot.snapshot_sha256,
      quick_intent_id: descriptor.quick_intent_id,
    }));
    quickIntents.appendChild(button);
  }
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
    renderQuickIntents();
    setIntentEnabled(true);
  } catch (error) {
    quickIntentCatalog = null;
    setIntentEnabled(false);
    intentResultState = {kind: "error", error};
    renderIntentResult();
  }
}

async function generateWithIntent(intentRequest) {
  if (!quickIntentCatalog || intentRequest.project_id !== activeProjectId) {
    intentResultState = {kind: "error", error: uiError("error.reload_catalog")};
    renderIntentResult();
    return;
  }
  const requestedProject = activeProjectId;
  const requestedCatalog = quickIntentCatalog.fingerprint;
  setIntentEnabled(false);
  intentResultState = {kind: "resolving"};
  renderIntentResult();
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
    intentResultState = {
      kind: "accepted",
      mode: documentValue.planning.provenance.mode,
    };
    renderIntentResult();
    const route = generatedWorkspaceHash(documentValue);
    history.pushState({route}, "", route);
  } catch (error) {
    intentResultState = {kind: "error", error};
    renderIntentResult();
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
  intentResultState = {kind: "failure", documentValue};
  renderIntentResult();
}

function renderIntentResult() {
  intentResult.replaceChildren();
  if (intentResultState.kind === "empty") {
    const empty = document.createElement("p");
    empty.className = "muted";
    appendText(empty, t("generation.none"));
    intentResult.appendChild(empty);
    return;
  }
  if (intentResultState.kind === "resolving") {
    const planning = document.createElement("p");
    planning.className = "muted";
    appendText(planning, t("generation.resolving"));
    intentResult.appendChild(planning);
    return;
  }
  if (intentResultState.kind === "accepted") {
    const accepted = document.createElement("p");
    accepted.className = "generation-accepted";
    appendText(accepted, t("generation.accepted", {
      mode: localizedCode(intentResultState.mode),
    }));
    intentResult.appendChild(accepted);
    return;
  }
  if (intentResultState.kind === "error") {
    showError(intentResult, intentResultState.error);
    return;
  }
  const documentValue = intentResultState.documentValue;
  const alert = document.createElement("div");
  alert.className = "generation-failure";
  alert.setAttribute("role", "alert");
  const heading = document.createElement("strong");
  appendText(heading, localizedCode(documentValue.status));
  alert.append(heading, fixedFields(documentValue, ["reason_code", "snapshot_revision"]));
  if ((documentValue.entity_candidates || []).length > 0) {
    alert.appendChild(titledSection(
      t("generation.choose_identity"),
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
    setConnectionStatus(available ? "connection.authenticated" : "connection.no_projects");
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
    setConnectionStatus("connection.workspace_loaded");
    if (!quickIntentCatalog
        || quickIntentCatalog.snapshot.snapshot_sha256 !== documentValue.freshness.snapshot_sha256) {
      await loadQuickIntents(documentValue.query.project_id);
    }
  } catch (error) {
    currentDocument = null;
    setBusy(false);
    setFreshnessStatus("freshness.unverified");
    showError(workspace, error);
    workspace.focus({preventScroll: true});
  }
}

async function loadGeneratedWorkspace(route, historyMode = "push") {
  if (!validProjectId(route.project_id) || !validEntryId(route.generation_id)) {
    throw uiError("error.generated_identity");
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
      throw uiError("error.generation_unrenderable");
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
    setConnectionStatus("connection.generated_loaded");
    if (!quickIntentCatalog) {
      await loadQuickIntents(documentValue.project_id);
    }
  } catch (error) {
    currentDocument = null;
    setBusy(false);
    setFreshnessStatus("freshness.generated_unverified");
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
      showError(workspace, uiError("error.two_runs"));
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
    throw uiError("error.navigation_identity");
  }
  const result = {view: query.view, project_id: query.project_id};
  for (const key of ["run_id", "paper_id", "baseline_run_id", "candidate_run_id"]) {
    if (query[key] !== undefined) {
      if (!validEntryId(query[key])) {
        throw uiError("error.selection_identity");
      }
      result[key] = query[key];
    }
  }
  if (result.view === "run-comparison"
      && (!result.baseline_run_id || !result.candidate_run_id
          || result.baseline_run_id === result.candidate_run_id)) {
    throw uiError("error.distinct_runs");
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
  return localizedHash(`#${workspacePath(query).replace("/api/v2/workspace", "")}`);
}

function generatedWorkspaceHash(documentValue) {
  return localizedHash(
    `#/projects/${encodeURIComponent(documentValue.project_id)}`
      + `/generated/${encodeURIComponent(documentValue.renderer.surface_id)}`,
  );
}

function parseWorkspaceHash() {
  const prefix = "#/projects/";
  const route = fragmentParts().route;
  if (!route.startsWith(prefix)) {
    return null;
  }
  let parts;
  try {
    parts = route.slice(prefix.length).split("/").map(decodeURIComponent);
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
    const code = payload.error?.code;
    const errorKey = code && hasTranslation(`error.${code}`)
      ? `error.${code}`
      : "error.receiver_rejected";
    const error = new Error(t(errorKey));
    error.translationKey = errorKey;
    throw error;
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
  if (container === connectionStatus) {
    connectionStatusError = error;
  }
  const errorKey = error instanceof Error ? error.translationKey : null;
  if (errorKey) {
    message.dataset.errorKey = errorKey;
  }
  appendText(message, errorKey
    ? t(errorKey)
    : error instanceof Error
      ? error.message
      : t("error.request_failed"));
  container.appendChild(message);
}

function rerenderForLocale() {
  localizeStaticShell();
  if (connectionStatusError) {
    showError(connectionStatus, connectionStatusError);
  } else {
    setConnectionStatus(connectionStatusKey);
  }
  if (currentDocument) {
    renderWorkspace(currentDocument, {preserveTransient: true, focus: false});
  } else {
    setFreshnessStatus(freshnessStatusKey || "freshness.none");
    renderProposalResult();
    renderArtifactResult();
  }
  renderQuickIntents();
  renderIntentResult();
  setIntentEnabled(Boolean(quickIntentCatalog) && intentResultState.kind !== "resolving");
}

async function initializeLocalization() {
  connectButton.disabled = true;
  localeSelect.disabled = true;
  try {
    await loadLocaleCatalogs();
    rerenderForLocale();
    replaceHashLocale();
    localeSelect.disabled = false;
    connectButton.disabled = false;
  } catch (error) {
    activeLocale = "en";
    document.documentElement.lang = "en";
    localeSelect.value = "en";
    localeSelect.disabled = true;
    connectButton.disabled = true;
    connectionStatus.textContent = error instanceof Error
      ? error.message
      : "Interface language resources could not be verified.";
  }
}

connectButton.addEventListener("click", loadProjects);
skipLink.addEventListener("click", (event) => {
  event.preventDefault();
  workspace.focus({preventScroll: false});
});
localeSelect.addEventListener("change", () => {
  activeLocale = normalizeLocale(localeSelect.value);
  replaceHashLocale();
  rerenderForLocale();
});
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
    intentResultState = {kind: "error", error: uiError("error.enter_question")};
    renderIntentResult();
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
  const routeLocale = localeFromFragment();
  if (routeLocale && routeLocale !== activeLocale) {
    activeLocale = routeLocale;
    rerenderForLocale();
  }
  const route = parseWorkspaceHash();
  if (route && tokenInput.value) {
    if (route.generation_id) {
      loadGeneratedWorkspace(route, "none");
    } else {
      loadWorkspace(route, "none");
    }
  }
});

initializeLocalization();
