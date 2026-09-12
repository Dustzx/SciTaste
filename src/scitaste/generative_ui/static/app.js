import {
  localeFromHash,
  normalizeLocale,
  routeFromHash,
  supportedLocales,
  translateMessage,
  validateCatalogs,
  withLocale,
} from "/assets/locale.js";

const projectSelect = document.getElementById("project-select");
const loadButton = document.getElementById("load-project");
const globalHomeButton = document.getElementById("global-home");
const newTopicButton = document.getElementById("new-topic");
const topicSearch = document.getElementById("topic-search");
const topicManagementStatus = document.getElementById("topic-management-status");
const workspaceHistoryList = document.getElementById("workspace-history-list");
const connectionStatus = document.getElementById("connection-status");
const freshness = document.getElementById("freshness");
const workspace = document.getElementById("workspace");
let proposalResult = null;
let artifactResult = null;
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
const conversationContextMode = document.getElementById("conversation-context-mode");
const generateWorkspaceButton = document.getElementById("generate-workspace");
const intentResult = document.getElementById("intent-result");
const localeSelect = document.getElementById("locale-select");
const skipLink = document.querySelector(".skip-link");
const drawerToggle = document.getElementById("drawer-toggle");
const drawerEdge = document.getElementById("drawer-edge");
const projectDrawer = document.getElementById("project-drawer");
const drawerClose = document.getElementById("drawer-close");
const drawerBackdrop = document.getElementById("drawer-backdrop");
const evidenceTools = document.querySelector(".evidence-tools");
const drawerProjectContext = document.getElementById("drawer-project-context");

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
  "review-project-data-acquisition-request": "quick.data_acquisition",
  "review-project-benchmark-qualification": "quick.benchmark_qualification",
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
let projectDiscovery = null;
let activeProjectId = "";
let accessReady = false;
let researchWorkspaceCatalog = null;
let topicSearchQuery = "";
let activeResearchWorkspaceId = "";
let activeResearchTurnId = "";
let activeResearchWorkspace = null;
let activeResearchTurn = null;
let activeResearchWorkspaceDetail = null;
let eventCounter = 0;
let artifactObjectUrl = null;
let lastProposalReceipt = null;
let lastControllerDecision = null;
let lastArtifactPreview = null;
let lastProposalError = null;
let lastArtifactError = null;
let intentResultState = {kind: "empty"};
let topicManagementState = {kind: "empty"};
let connectionStatusKey = "connection.connecting";
let freshnessStatusKey = "freshness.none";
let connectionStatusError = null;
const compactNavigation = window.matchMedia("(max-width: 900px)");
let drawerPinned = false;
let drawerPreview = false;
let drawerCloseTimer = null;

function isDrawerOpen() {
  return drawerPinned || drawerPreview;
}

function renderDrawerState({focus = false} = {}) {
  const open = isDrawerOpen();
  document.body.classList.toggle("drawer-open", open);
  document.body.classList.toggle("drawer-closed", !open);
  document.body.classList.toggle("drawer-pinned", drawerPinned);
  document.body.classList.toggle("drawer-preview", drawerPreview && !drawerPinned);
  projectDrawer.setAttribute("aria-hidden", open ? "false" : "true");
  projectDrawer.inert = !open;
  drawerToggle.setAttribute("aria-expanded", open ? "true" : "false");
  const labelKey = drawerPinned ? "nav.close" : "nav.open";
  drawerToggle.dataset.i18nAria = labelKey;
  drawerToggle.setAttribute("aria-label", hasTranslation(labelKey)
    ? t(labelKey)
    : drawerPinned ? "Close conversation history" : "Open conversation history");
  drawerBackdrop.setAttribute("aria-label", hasTranslation("nav.close")
    ? t("nav.close")
    : "Close conversation history");
  if (focus && open) {
    projectDrawer.focus({preventScroll: true});
  }
}

function clearDrawerCloseTimer() {
  if (drawerCloseTimer !== null) {
    window.clearTimeout(drawerCloseTimer);
    drawerCloseTimer = null;
  }
}

function setDrawerPinned(pinned, options = {}) {
  clearDrawerCloseTimer();
  drawerPinned = Boolean(pinned);
  drawerPreview = false;
  renderDrawerState(options);
}

function previewDrawer(event) {
  if (compactNavigation.matches || drawerPinned
      || (event?.pointerType && event.pointerType !== "mouse")) {
    return;
  }
  clearDrawerCloseTimer();
  drawerPreview = true;
  renderDrawerState();
}

function scheduleDrawerPreviewClose() {
  if (drawerPinned || !drawerPreview) {
    return;
  }
  clearDrawerCloseTimer();
  drawerCloseTimer = window.setTimeout(() => {
    drawerPreview = false;
    drawerCloseTimer = null;
    renderDrawerState();
  }, 180);
}

function closeDrawerOnMobile() {
  if (compactNavigation.matches) {
    setDrawerPinned(false);
  }
}

renderDrawerState();

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

function formatByteCeiling(bytes) {
  if (!Number.isSafeInteger(bytes) || bytes < 0) {
    return "—";
  }
  if (bytes >= 1024 * 1024) {
    return `${Number((bytes / (1024 * 1024)).toFixed(1))} MiB`;
  }
  if (bytes >= 1024) {
    return `${Number((bytes / 1024).toFixed(1))} KiB`;
  }
  return `${bytes} B`;
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
  function blockerCard(blocker) {
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
    return item;
  }
  for (const blocker of data.blockers.slice(0, 3)) {
    list.appendChild(blockerCard(blocker));
  }
  if (data.blockers.length > 3) {
    const more = document.createElement("details");
    more.className = "more-blockers";
    const moreSummary = document.createElement("summary");
    appendText(moreSummary, t("blocker.more", {count: data.blockers.length - 3}));
    const moreList = document.createElement("div");
    moreList.className = "generated-blocker-list";
    for (const blocker of data.blockers.slice(3)) {
      moreList.appendChild(blockerCard(blocker));
    }
    more.append(moreSummary, moreList);
    list.appendChild(more);
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
    const use = document.createElement("small");
    use.className = "landscape-work-use";
    appendText(use, t(`landscape.use.${work.experiment_role}`));
    const classification = document.createElement("span");
    classification.className = "landscape-work-classification";
    const publication = document.createElement("span");
    publication.className = `landscape-evidence-tag evidence-${work.publication_status}`;
    appendText(publication, t(`landscape.publication.${work.publication_status}`));
    const scope = document.createElement("span");
    scope.className = `landscape-evidence-tag scope-${work.comparison_scope}`;
    appendText(scope, t(`landscape.scope.${work.comparison_scope}`));
    classification.append(publication, scope);
    identity.append(name, venue, use, classification);
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

function renderContributionSummary(data) {
  const section = progressSection(
    t("landscape.types.title"),
    t("landscape.types.subtitle"),
  );
  const scope = document.createElement("aside");
  scope.className = "landscape-scope-note";
  const scopeLabel = document.createElement("strong");
  appendText(scopeLabel, t("landscape.scope.eyebrow"));
  const scopeCopy = document.createElement("span");
  appendText(scopeCopy, activeLocale === "zh-CN" ? data.scope_note_zh : data.scope_note_en);
  scope.append(scopeLabel, scopeCopy);

  const grid = document.createElement("div");
  grid.className = "landscape-type-grid";
  const types = data.works.some((work) => work.contribution_type === "unclassified")
    ? ["unclassified"]
    : ["method", "hybrid", "benchmark"];
  for (const type of types) {
    const works = data.works.filter((work) => work.contribution_type === type);
    const card = document.createElement("article");
    card.className = `landscape-type-card type-${type}`;
    const header = document.createElement("div");
    const count = document.createElement("strong");
    appendText(count, works.length);
    const label = document.createElement("h4");
    appendText(label, t(`landscape.type.${type}`));
    header.append(count, label);
    const description = document.createElement("p");
    appendText(description, t(`landscape.type.${type}.description`));
    const names = document.createElement("small");
    const visibleNames = works.slice(0, 4).map((work) => work.name).join(" · ");
    const remainder = works.length - 4;
    appendText(names, remainder > 0
      ? `${visibleNames} · ${t("landscape.type.more", {count: remainder})}`
      : visibleNames);
    card.append(header, description, names);
    grid.appendChild(card);
  }
  section.append(scope, grid);
  return section;
}

function renderExperimentTracks(data) {
  const section = progressSection(
    t("landscape.tracks.title"),
    t("landscape.tracks.subtitle"),
  );
  const tracks = document.createElement("div");
  tracks.className = "landscape-experiment-tracks";
  const systemWorks = data.works.filter((work) =>
    ["method", "hybrid"].includes(work.contribution_type)
      && work.bundled_artifacts.includes("system"));
  const resourceWorks = data.works.filter((work) =>
    work.contribution_type === "benchmark"
      || (work.contribution_type === "hybrid"
        && work.bundled_artifacts.some((item) =>
          ["benchmark", "judge", "dataset"].includes(item))));
  const trackSpecs = [
    {
      id: "systems",
      works: systemWorks,
      candidates: data.comparison_candidates.filter((item) => item.candidate_kind === "system"),
    },
    {
      id: "resources",
      works: resourceWorks,
      candidates: data.comparison_candidates.filter((item) => item.candidate_kind !== "system"),
    },
  ];
  for (const spec of trackSpecs) {
    const card = document.createElement("article");
    card.className = `landscape-experiment-track track-${spec.id}`;
    const marker = document.createElement("span");
    marker.className = "track-marker";
    appendText(marker, t(`landscape.track.${spec.id}.marker`));
    const copy = document.createElement("div");
    const heading = document.createElement("h4");
    appendText(heading, t(`landscape.track.${spec.id}`));
    const purpose = document.createElement("p");
    appendText(purpose, t(`landscape.track.${spec.id}.purpose`));
    const measures = document.createElement("div");
    measures.className = "track-measures";
    for (const [value, label] of [
      [spec.works.length, t("landscape.track.screened")],
      [spec.candidates.length, t("landscape.track.candidates")],
      [spec.candidates.filter((item) => item.readiness === "formal").length,
        t("landscape.track.formal")],
    ]) {
      const measure = document.createElement("span");
      const number = document.createElement("strong");
      appendText(number, value);
      const labelNode = document.createElement("small");
      appendText(labelNode, label);
      measure.append(number, labelNode);
      measures.appendChild(measure);
    }
    const names = document.createElement("small");
    names.className = "track-names";
    appendText(names, spec.works.slice(0, 4).map((work) => work.name).join(" · "));
    copy.append(heading, purpose, measures, names);
    card.append(marker, copy);
    tracks.appendChild(card);
  }
  const protocol = document.createElement("article");
  protocol.className = "landscape-protocol-gate";
  const protocolMarker = document.createElement("span");
  appendText(protocolMarker, "∩");
  const protocolCopy = document.createElement("div");
  const protocolHeading = document.createElement("h4");
  appendText(protocolHeading, t("landscape.track.protocol"));
  const protocolDescription = document.createElement("p");
  appendText(protocolDescription, t("landscape.track.protocol.purpose"));
  protocolCopy.append(protocolHeading, protocolDescription);
  protocol.append(protocolMarker, protocolCopy, landscapeStatePill(data.freeze_decision));
  section.append(tracks, protocol);
  return section;
}

function renderCandidateReadiness(data) {
  const section = progressSection(
    t("landscape.candidates.title"),
    t("landscape.candidates.subtitle"),
  );
  const groups = document.createElement("div");
  groups.className = "candidate-readiness-groups";
  const candidateGroups = [
    ["systems", (item) => item.candidate_kind === "system"],
    ["resources", (item) => item.candidate_kind !== "system"],
  ];
  for (const [groupId, predicate] of candidateGroups) {
    const group = document.createElement("section");
    group.className = `candidate-readiness-group group-${groupId}`;
    const heading = document.createElement("h4");
    appendText(heading, t(`landscape.candidates.${groupId}`));
    const lanes = document.createElement("div");
    lanes.className = "readiness-lanes";
    for (const readiness of ["reference", "adaptation", "formal"]) {
      const lane = document.createElement("section");
      lane.className = `readiness-lane readiness-${readiness}`;
      const laneHeading = document.createElement("h5");
      appendText(laneHeading, t(`landscape.readiness.${readiness}`));
      lane.appendChild(laneHeading);
      for (const candidate of data.comparison_candidates.filter(
        (item) => predicate(item) && item.readiness === readiness,
      )) {
        const card = document.createElement("article");
        const name = document.createElement("strong");
        appendText(name, candidate.name);
        const meta = document.createElement("small");
        appendText(meta, `${t(`landscape.kind.${candidate.candidate_kind}`)} · ${t(`landscape.role.${candidate.role}`)}`);
        const evidence = document.createElement("div");
        evidence.className = "candidate-evidence-tags";
        const publication = document.createElement("span");
        publication.className = `landscape-evidence-tag evidence-${candidate.publication_status}`;
        appendText(publication, t(`landscape.publication.${candidate.publication_status}`));
        const track = document.createElement("span");
        track.className = `landscape-evidence-tag track-${candidate.evaluation_track}`;
        appendText(track, t(`landscape.evaluation.${candidate.evaluation_track}`));
        evidence.append(publication, track);
        const barrier = document.createElement("span");
        barrier.className = "barrier-code";
        appendText(barrier, localizedCode(candidate.barrier_code));
        card.append(name, meta, evidence, barrier);
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
    group.append(heading, lanes);
    groups.appendChild(group);
  }
  section.appendChild(groups);
  return section;
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
  const typeCounts = Object.fromEntries(
    ["method", "hybrid", "benchmark"].map((type) => [
      type,
      data.works.filter((work) => work.contribution_type === type).length,
    ]),
  );
  const countItems = data.works.some((work) => work.contribution_type === "unclassified")
    ? [
        [data.works.length, t("landscape.count.works")],
        [data.stages.length, t("landscape.count.stages")],
        [data.lenses.length, t("landscape.count.lenses")],
      ]
    : [
        [typeCounts.method, t("landscape.count.methods")],
        [typeCounts.hybrid, t("landscape.count.hybrids")],
        [typeCounts.benchmark, t("landscape.count.benchmarks")],
      ];
  for (const [value, label] of countItems) {
    const item = document.createElement("span");
    const number = document.createElement("strong");
    appendText(number, value);
    const copy = document.createElement("small");
    appendText(copy, label);
    item.append(number, copy);
    synthesis.appendChild(item);
  }
  gate.append(decisionCopy, synthesis);

  const contributionTypes = renderContributionSummary(data);
  const experimentTracks = renderExperimentTracks(data);

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
  const groups = document.createElement("div");
  groups.className = "landscape-contribution-groups";
  const contributionTypesInData = data.works.some(
    (work) => work.contribution_type === "unclassified",
  ) ? ["unclassified"] : ["method", "hybrid", "benchmark"];
  for (const type of contributionTypesInData) {
    const works = data.works.filter((work) => work.contribution_type === type);
    if (works.length === 0) {
      continue;
    }
    const group = document.createElement("details");
    group.className = `landscape-contribution-group type-${type}`;
    if (type !== "benchmark") {
      group.open = true;
    }
    const summary = document.createElement("summary");
    const label = document.createElement("strong");
    appendText(label, t(`landscape.type.${type}`));
    const count = document.createElement("span");
    appendText(count, works.length);
    summary.append(label, count);
    group.append(summary, renderLandscapeTable(data, works));
    groups.appendChild(group);
  }
  map.appendChild(groups);

  const candidateSection = renderCandidateReadiness(data);

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
    contributionTypes,
    experimentTracks,
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
    progressMetric(t("progress.metric.evaluations"), data.counts.evaluations_registered, t("progress.metric.evaluations_note")),
    progressMetric(t("progress.metric.results"), data.counts.evaluation_results_registered, t("progress.metric.results_note")),
    progressMetric(t("progress.metric.acquisitions"), data.counts.acquisition_requests || 0, t("progress.metric.acquisitions_note")),
  );
  const acquisitions = renderAcquisitionRequests(data.acquisitions || []);
  const acquisitionQualifications = renderAcquisitionQualifications(
    data.acquisition_qualifications || [],
  );
  const benchmarkQualifications = renderBenchmarkQualifications(
    data.benchmark_qualifications || [],
  );
  const datasetPackages = renderDatasetPackages(data.dataset_packages || []);
  const reviewIterations = renderReviewIterations(data.review_iterations || []);
  const distribution = renderRunDistribution(data.counts);
  const lifecycle = renderProjectLifecycle(data.lifecycle);

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

  const evaluations = progressSection(
    t("progress.evaluations.title"),
    data.evaluations.length > 0
      ? t("progress.evaluations.subtitle", {count: data.evaluations.length})
      : t("progress.evaluations.empty"),
  );
  if (data.evaluations.length > 0) {
    const evaluationGrid = document.createElement("div");
    evaluationGrid.className = "evaluation-proposal-grid";
    for (const item of data.evaluations) {
      const card = document.createElement("article");
      card.className = `evaluation-proposal-card status-${item.status}`;
      const header = document.createElement("div");
      header.className = "compact-row-header";
      const identity = document.createElement("div");
      const scope = document.createElement("span");
      scope.className = "card-label";
      appendText(scope, t(`progress.evaluations.scope.${item.study_scope}`));
      const title = document.createElement("strong");
      appendText(title, item.protocol_id);
      identity.append(scope, title);
      const status = document.createElement("span");
      status.className = `lifecycle-state state-${item.execution_authorized ? "satisfied" : "blocked"}`;
      appendText(status, t(`progress.evaluations.status.${item.status}`));
      header.append(identity, status);

      const facts = document.createElement("div");
      facts.className = "evaluation-proposal-facts";
      const cells = document.createElement("span");
      appendText(cells, t("progress.evaluations.cells", {count: item.planned_cells}));
      const decisionGates = document.createElement("span");
      appendText(decisionGates, t("progress.evaluations.decision_gates", {
        count: item.decision_blocker_count,
      }));
      const blockers = document.createElement("span");
      appendText(blockers, t("progress.evaluations.diagnostics", {count: item.blocker_count}));
      facts.append(cells, decisionGates, blockers);

      const resources = document.createElement("ul");
      resources.className = "evaluation-resource-list";
      for (const resource of [...item.api_resources, ...item.gpu_resources]) {
        const entry = document.createElement("li");
        appendText(entry, resource);
        resources.appendChild(entry);
      }
      const gateRail = document.createElement("ol");
      gateRail.className = "evaluation-gate-rail";
      for (const gate of item.gates) {
        const gateItem = document.createElement("li");
        gateItem.className = `evaluation-gate state-${gate.state}`;
        const gateName = document.createElement("strong");
        appendText(gateName, t(`progress.evaluations.gate.${gate.gate_id}`));
        const gateState = document.createElement("span");
        appendText(gateState, t(`progress.evaluations.gate_state.${gate.state}`));
        const gateIssues = document.createElement("small");
        appendText(gateIssues, gate.issue_count > 0
          ? t("progress.evaluations.gate_issues", {
            count: gate.issue_count,
            affected: gate.affected_count,
          })
          : t("progress.evaluations.gate_clear"));
        gateItem.append(gateName, gateState, gateIssues);
        gateRail.appendChild(gateItem);
      }
      const nextAction = document.createElement("p");
      nextAction.className = "evaluation-next-action";
      if (item.next_gate_id) {
        const nextGate = item.gates.find((gate) => gate.gate_id === item.next_gate_id);
        appendText(nextAction, t("progress.evaluations.next", {
          action: t(`progress.evaluations.action.${nextGate.next_action_code}`),
        }));
      } else {
        appendText(nextAction, t("progress.evaluations.ready"));
      }
      const boundary = document.createElement("p");
      boundary.className = "muted compact-copy";
      appendText(boundary, t("progress.evaluations.no_execution"));
      card.append(
        header,
        facts,
        resources,
        gateRail,
        nextAction,
        boundary,
        evidenceDisclosure(item.support_ref_ids, {
          data: {
            evaluation_id: item.evaluation_id,
            ready_for_author_review: item.ready_for_author_review,
            execution_authorized: item.execution_authorized,
            selected: item.selected,
            decision_map_sha256: item.gate_map_sha256,
          },
          names: [
            "evaluation_id",
            "ready_for_author_review",
            "execution_authorized",
            "selected",
            "decision_map_sha256",
          ],
        }),
      );
      evaluationGrid.appendChild(card);
    }
    evaluations.appendChild(evaluationGrid);
  }

  const evaluationResults = progressSection(
    t("progress.results.title"),
    data.evaluation_results.length > 0
      ? t("progress.results.subtitle", {count: data.evaluation_results.length})
      : t("progress.results.empty"),
  );
  if (data.evaluation_results.length > 0) {
    const resultGrid = document.createElement("div");
    resultGrid.className = "evaluation-proposal-grid";
    for (const item of data.evaluation_results) {
      const card = document.createElement("article");
      card.className = `evaluation-proposal-card status-${item.status}`;
      const header = document.createElement("div");
      header.className = "compact-row-header";
      const identity = document.createElement("div");
      const label = document.createElement("span");
      label.className = "card-label";
      appendText(label, item.evaluation_id);
      const title = document.createElement("strong");
      appendText(title, item.result_id);
      identity.append(label, title);
      const state = document.createElement("span");
      state.className = `lifecycle-state state-${item.headline_eligible ? "satisfied" : "blocked"}`;
      appendText(state, t(`progress.results.status.${item.status}`));
      header.append(identity, state);

      const facts = document.createElement("div");
      facts.className = "evaluation-proposal-facts";
      const cells = document.createElement("span");
      appendText(cells, t("progress.results.cells", {
        succeeded: item.succeeded_cells,
        planned: item.planned_cells,
      }));
      const failures = document.createElement("span");
      appendText(failures, t("progress.results.failures", {
        failed: item.failed_cells,
        missing: item.missing_cells,
        invalid: item.invalid_cells,
      }));
      const reviews = document.createElement("span");
      appendText(reviews, t("progress.results.reviews", {
        count: item.valid_external_reviews,
      }));
      facts.append(cells, failures, reviews);

      const verdicts = document.createElement("ul");
      verdicts.className = "evaluation-resource-list";
      for (const [key, value] of [
        ["scientific_evidence", item.scientific_evidence_complete],
        ["headline", item.headline_eligible],
        ["effectiveness", item.scientific_effectiveness_established],
      ]) {
        const row = document.createElement("li");
        appendText(row, t(`progress.results.${key}.${value ? "yes" : "no"}`));
        verdicts.appendChild(row);
      }
      card.append(header, facts, verdicts, evidenceDisclosure(item.support_ref_ids, {
        data: {
          result_id: item.result_id,
          evaluation_id: item.evaluation_id,
          selected: item.selected,
        },
        names: ["result_id", "evaluation_id", "selected"],
      }));
      resultGrid.appendChild(card);
    }
    evaluationResults.appendChild(resultGrid);
  }

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
    review_data_acquisition: t("progress.next.data_acquisition"),
    review_benchmark_qualification: t("progress.next.benchmark_qualification"),
    review_iteration: t("progress.next.review_iteration"),
  };
  const lensDefinitions = [
    {
      key: "progress",
      kinds: ["review_iteration", "review_progress", "review_next_gate"],
    },
    {
      key: "experiment",
      kinds: [
        "review_data_acquisition",
        "review_benchmark_qualification",
        "review_research_landscape",
        "compare_runs",
      ],
    },
    {
      key: "paper",
      kinds: ["review_iteration", "review_paper_evidence"],
    },
    {
      key: "risk",
      kinds: ["diagnose_blockers", "review_next_gate"],
    },
  ];
  const candidateList = document.createElement("div");
  candidateList.className = "candidate-list research-lens-grid";
  function candidateButton(candidate, lensKey = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = lensKey
      ? "candidate-button research-lens-button"
      : "candidate-button";
    const label = document.createElement("strong");
    appendText(label, lensKey
      ? t(`progress.lens.${lensKey}.title`)
      : candidateLabels[candidate.kind] || readableCode(candidate.label_code));
    if (lensKey) {
      const body = document.createElement("span");
      body.className = "research-lens-description";
      appendText(body, t(`progress.lens.${lensKey}.body`));
      const current = document.createElement("small");
      appendText(current, t("progress.lens.current", {
        path: candidateLabels[candidate.kind] || readableCode(candidate.label_code),
      }));
      button.append(label, body, current);
    } else {
      const note = document.createElement("small");
      appendText(note, t("progress.next.meta", {
        targets: countMessage("common.targets", candidate.target_ids.length),
        evidence: countMessage("common.records", candidate.support_ref_ids.length),
      }));
      button.append(label, note);
    }
    button.addEventListener("click", () => requestCandidateWorkspace(candidate.candidate_id));
    return button;
  }
  const primaryCandidateIds = new Set();
  for (const lens of lensDefinitions) {
    const candidate = data.next_step_candidates.find((item) => (
      !primaryCandidateIds.has(item.candidate_id) && lens.kinds.includes(item.kind)
    ));
    if (candidate) {
      primaryCandidateIds.add(candidate.candidate_id);
      candidateList.appendChild(candidateButton(candidate, lens.key));
    }
  }
  const remainingCandidates = data.next_step_candidates.filter(
    (candidate) => !primaryCandidateIds.has(candidate.candidate_id),
  );
  if (remainingCandidates.length > 0) {
    const more = document.createElement("details");
    more.className = "more-candidates";
    const moreSummary = document.createElement("summary");
    appendText(moreSummary, t("progress.next.more", {
      count: remainingCandidates.length,
    }));
    const remainder = document.createElement("div");
    remainder.className = "candidate-list";
    for (const candidate of remainingCandidates) {
      remainder.appendChild(candidateButton(candidate));
    }
    more.append(moreSummary, remainder);
    candidateList.appendChild(more);
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
  const details = document.createElement("details");
  details.className = "progress-evidence-vault";
  const detailsSummary = document.createElement("summary");
  const detailsTitle = document.createElement("strong");
  appendText(detailsTitle, t("progress.details.title"));
  const detailsBody = document.createElement("small");
  appendText(detailsBody, t("progress.details.body", {
    runs: data.counts.runs_registered,
    evaluations: data.counts.evaluations_registered,
    blockers: attentionCount,
  }));
  detailsSummary.append(detailsTitle, detailsBody);
  const detailContent = document.createElement("div");
  detailContent.className = "progress-evidence-vault-content";
  detailContent.append(
    benchmarkQualifications,
    datasetPackages,
    acquisitions,
    acquisitionQualifications,
    metrics,
    distribution,
    evaluations,
    evaluationResults,
    standing,
    activity,
  );
  details.append(detailsSummary, detailContent);
  container.appendChild(hero);
  if ((data.review_iterations || []).length > 0) {
    container.appendChild(reviewIterations);
  }
  container.append(nextSteps, direction, lifecycle, details);
  return container;
}

function renderReviewIterations(items) {
  const section = progressSection(
    t("progress.review_iteration.title"),
    items.length > 0
      ? t("progress.review_iteration.subtitle", {count: items.length})
      : t("progress.review_iteration.empty"),
  );
  if (items.length === 0) return section;

  const grid = document.createElement("div");
  grid.className = "review-iteration-grid";
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "review-iteration-card";
    const header = document.createElement("div");
    header.className = "compact-row-header";
    const identity = document.createElement("div");
    const label = document.createElement("span");
    label.className = "card-label";
    appendText(label, t("progress.review_iteration.review", {id: item.review_id}));
    const title = document.createElement("strong");
    appendText(title, item.run_id);
    identity.append(label, title);
    header.append(
      identity,
      progressPill(
        item.execution_approval_required ? "candidate" : "current_work",
        item.execution_approval_required
          ? t("progress.review_iteration.approval_required")
          : t("progress.review_iteration.no_approval_steps"),
      ),
    );

    const facts = document.createElement("div");
    facts.className = "review-iteration-facts";
    for (const [value, key] of [
      [item.concern_count, "concerns"],
      [item.step_count, "steps"],
      [item.next_step_ids.length, "ready"],
      [item.owner_approval_step_ids.length, "approvals"],
    ]) {
      const fact = document.createElement("span");
      const number = document.createElement("strong");
      appendText(number, value);
      const caption = document.createElement("small");
      appendText(caption, t(`progress.review_iteration.${key}`));
      fact.append(number, caption);
      facts.appendChild(fact);
    }

    const stepById = new Map(item.steps.map((step) => [step.step_id, step]));
    let followup = null;
    if (item.followup_design) {
      followup = document.createElement("div");
      followup.className = "review-followup-summary";
      const followupHeader = document.createElement("div");
      followupHeader.className = "compact-row-header";
      const followupIdentity = document.createElement("div");
      const followupLabel = document.createElement("span");
      followupLabel.className = "card-label";
      appendText(followupLabel, t("progress.review_iteration.followup.title"));
      const followupProgram = document.createElement("strong");
      appendText(followupProgram, item.followup_design.evidence_program_id);
      followupIdentity.append(followupLabel, followupProgram);
      followupHeader.append(
        followupIdentity,
        progressPill("candidate", t("progress.review_iteration.followup.no_run")),
      );
      const hypothesisRow = document.createElement("div");
      hypothesisRow.className = "review-followup-hypotheses";
      for (const hypothesis of item.followup_design.hypothesis_ids) {
        const badge = document.createElement("span");
        appendText(badge, hypothesis);
        hypothesisRow.appendChild(badge);
      }
      const resourceRow = document.createElement("div");
      resourceRow.className = "review-followup-resources";
      for (const [key, value] of [
        ["studies", item.followup_design.study_ids.length],
        ["tasks", item.followup_design.task_source_ids.length],
        ["systems", item.followup_design.system_candidate_ids.length],
        ["model", t("progress.review_iteration.followup.unselected")],
        ["sample", t("progress.review_iteration.followup.after_pilot")],
        ["compute", t("progress.review_iteration.followup.unallocated")],
      ]) {
        const resource = document.createElement("span");
        const resourceValue = document.createElement("strong");
        appendText(resourceValue, value);
        const resourceLabel = document.createElement("small");
        appendText(resourceLabel, t(`progress.review_iteration.followup.${key}`));
        resource.append(resourceValue, resourceLabel);
        resourceRow.appendChild(resource);
      }
      const titleGate = document.createElement("p");
      titleGate.className = "review-iteration-boundary";
      appendText(titleGate, t("progress.review_iteration.followup.title_gate"));
      let activation = null;
      if (item.followup_design.activation) {
        const data = item.followup_design.activation;
        activation = document.createElement("div");
        activation.className = "review-activation-summary";
        const activationHeader = document.createElement("div");
        activationHeader.className = "compact-row-header";
        const activationTitle = document.createElement("strong");
        appendText(activationTitle, t("progress.review_iteration.activation.title"));
        activationHeader.append(
          activationTitle,
          progressPill("candidate", t("progress.review_iteration.activation.no_run")),
        );
        const activationFacts = document.createElement("div");
        activationFacts.className = "review-activation-facts";
        for (const [value, key] of [
          [
            `${data.metadata_item_count} / ${formatByteCeiling(data.metadata_byte_ceiling)}`,
            "metadata",
          ],
          [`${data.pilot_ready_model_count}/${data.primary_model_candidate_count}`, "models"],
          [
            `${data.identity_protocol_model_count}/${data.primary_model_candidate_count}`,
            "identity_protocol",
          ],
          [
            `${data.pilot_proposal_ready_model_count}/${data.primary_model_candidate_count}`,
            "pilot_proposal",
          ],
          [`${data.adapter_ready_system_count}/${data.external_system_count}`, "adapters"],
          [`${data.recruited_reviewer_count}/${data.minimum_reviewer_count}`, "reviewers"],
          [t("progress.review_iteration.activation.blocked"), "experiment"],
        ]) {
          const fact = document.createElement("span");
          const factValue = document.createElement("strong");
          appendText(factValue, value);
          const factLabel = document.createElement("small");
          appendText(factLabel, t(`progress.review_iteration.activation.${key}`));
          fact.append(factValue, factLabel);
          activationFacts.appendChild(fact);
        }
        const decision = document.createElement("p");
        decision.className = "review-activation-decision";
        appendText(decision, t("progress.review_iteration.activation.next_decision", {
          count: data.metadata_item_count,
          size: formatByteCeiling(data.metadata_byte_ceiling),
        }));
        const inspectActivation = document.createElement("button");
        inspectActivation.type = "button";
        inspectActivation.className = "secondary-button";
        appendText(inspectActivation, t("progress.review_iteration.activation.inspect"));
        inspectActivation.addEventListener("click", () => loadWorkspace({
          view: "run-stage-explorer",
          project_id: currentProjectId(),
          run_id: data.run_id,
        }));
        activation.append(activationHeader, activationFacts, decision, inspectActivation);
      }
      followup.append(followupHeader, hypothesisRow, resourceRow);
      if (activation) followup.appendChild(activation);
      followup.appendChild(titleGate);
    }
    const lanes = document.createElement("div");
    lanes.className = "review-iteration-lanes";
    for (const lane of item.lanes) {
      const laneCard = document.createElement("details");
      laneCard.className = `review-iteration-lane lane-${lane.stage}`;
      const summary = document.createElement("summary");
      const laneName = document.createElement("strong");
      appendText(laneName, t(`progress.review_iteration.stage.${lane.stage}`));
      const laneCount = document.createElement("small");
      appendText(laneCount, t("progress.review_iteration.lane_meta", {
        steps: lane.step_ids.length,
        ready: lane.ready_count,
        approvals: lane.approval_count,
      }));
      summary.append(laneName, laneCount);
      const laneSteps = document.createElement("div");
      laneSteps.className = "review-iteration-lane-steps";
      for (const stepId of lane.step_ids) {
        const step = stepById.get(stepId);
        if (!step) continue;
        const node = document.createElement("article");
        node.className = `review-iteration-node state-${step.state}`;
        const nodeTitle = document.createElement("strong");
        appendText(nodeTitle, readableCode(step.kind));
        const objective = document.createElement("p");
        appendText(objective, step.objective);
        const nodeMeta = document.createElement("small");
        appendText(nodeMeta, step.requires_owner_approval
          ? t("progress.review_iteration.node_approval")
          : step.depends_on.length > 0
            ? t("progress.review_iteration.node_dependencies", {count: step.depends_on.length})
            : t("progress.review_iteration.node_ready"));
        node.append(nodeTitle, objective, nodeMeta);
        if ((step.hypothesis_ids || []).length > 0) {
          const bindings = document.createElement("div");
          bindings.className = "review-followup-node-bindings";
          for (const hypothesis of step.hypothesis_ids) {
            const badge = document.createElement("span");
            appendText(badge, hypothesis);
            bindings.appendChild(badge);
          }
          node.appendChild(bindings);
        }
        laneSteps.appendChild(node);
      }
      laneCard.append(summary, laneSteps);
      lanes.appendChild(laneCard);
    }

    const flow = document.createElement("div");
    flow.className = "review-iteration-flow";
    for (const edge of item.lane_edges) {
      const relation = document.createElement("span");
      appendText(relation, t("progress.review_iteration.edge", {
        source: t(`progress.review_iteration.stage.${edge.source_stage}`),
        target: t(`progress.review_iteration.stage.${edge.target_stage}`),
        count: edge.dependency_count,
      }));
      flow.appendChild(relation);
    }

    const boundary = document.createElement("p");
    boundary.className = "review-iteration-boundary";
    appendText(boundary, t("progress.review_iteration.boundary"));
    const open = document.createElement("button");
    open.type = "button";
    open.className = "secondary-button";
    appendText(open, t("progress.review_iteration.open_plan"));
    open.addEventListener("click", () => loadWorkspace({
      view: "run-stage-explorer",
      project_id: currentProjectId(),
      run_id: item.run_id,
    }));
    card.append(header, facts);
    if (followup) card.appendChild(followup);
    card.append(
      lanes,
      flow,
      boundary,
      open,
      ...(item.followup_design
        ? [(() => {
          const inspect = document.createElement("button");
          inspect.type = "button";
          inspect.className = "secondary-button";
          appendText(inspect, t("progress.review_iteration.followup.inspect"));
          inspect.addEventListener("click", () => loadWorkspace({
            view: "run-stage-explorer",
            project_id: currentProjectId(),
            run_id: item.followup_design.run_id,
          }));
          return inspect;
        })()]
        : []),
      evidenceDisclosure(item.support_ref_ids, {
        data: {
          plan_sha256: item.plan_sha256,
          followup_design_sha256: item.followup_design?.design_sha256 || null,
          followup_activation_sha256:
            item.followup_design?.activation?.activation_sha256 || null,
          terminal_step_id: item.terminal_step_id,
          authorizes_execution: item.authorizes_execution,
          no_execution_performed: item.no_execution_performed,
        },
        names: [
          "plan_sha256",
          "followup_design_sha256",
          "followup_activation_sha256",
          "terminal_step_id",
          "authorizes_execution",
          "no_execution_performed",
        ],
      }),
    );
    grid.appendChild(card);
  }
  section.appendChild(grid);
  return section;
}

function renderAcquisitionRequests(items) {
  const section = progressSection(
    t("progress.acquisition.title"),
    items.length > 0
      ? t("progress.acquisition.subtitle", {count: items.length})
      : t("progress.acquisition.empty"),
  );
  if (items.length === 0) {
    return section;
  }
  const grid = document.createElement("div");
  grid.className = "acquisition-grid";
  const stateMap = {
    blocked: "blocked",
    awaiting_owner_approval: "candidate",
    download_authorized: "observed_completed",
  };
  for (const item of items) {
    const card = document.createElement("article");
    card.className = `acquisition-card status-${item.status}`;
    const header = document.createElement("div");
    header.className = "compact-row-header";
    const identity = document.createElement("div");
    const label = document.createElement("span");
    label.className = "card-label";
    appendText(label, t("progress.acquisition.decision"));
    const title = document.createElement("strong");
    appendText(title, item.request_id);
    identity.append(label, title);
    header.append(
      identity,
      progressPill(
        stateMap[item.status] || "unknown",
        t(`progress.acquisition.status.${item.status}`),
      ),
    );

    const facts = document.createElement("div");
    facts.className = "acquisition-facts";
    for (const value of [
      t("progress.acquisition.items", {count: item.item_count}),
      t("progress.acquisition.ceiling", {size: formatByteCeiling(item.maximum_total_bytes)}),
      t("progress.acquisition.hosts", {hosts: item.source_hosts.join(", ")}),
    ]) {
      const fact = document.createElement("span");
      appendText(fact, value);
      facts.appendChild(fact);
    }

    const purpose = document.createElement("p");
    purpose.className = "acquisition-purpose";
    appendText(purpose, item.purpose);
    const boundary = document.createElement("p");
    boundary.className = "acquisition-boundary";
    appendText(boundary, t("progress.acquisition.boundary"));
    const restrictions = document.createElement("ul");
    restrictions.className = "acquisition-restrictions";
    for (const key of ["no_network", "no_download", "no_ingestion_execution"]) {
      const restriction = document.createElement("li");
      appendText(restriction, t(`progress.acquisition.${key}`));
      restrictions.appendChild(restriction);
    }

    const review = document.createElement("button");
    review.type = "button";
    review.className = "secondary-button acquisition-review";
    appendText(review, t("progress.acquisition.review"));
    review.addEventListener("click", () => requestCandidateWorkspace(
      "review-data-acquisition-request",
    ));
    card.append(
      header,
      facts,
      purpose,
      boundary,
      restrictions,
      review,
      evidenceDisclosure(item.support_ref_ids, {
        data: {
          request_sha256: item.request_sha256,
          report_sha256: item.report_sha256,
          claim_boundary: item.claim_boundary,
          download_authorized: item.download_authorized,
          authorizes_ingestion: item.authorizes_ingestion,
          authorizes_execution: item.authorizes_execution,
          no_dataset_file_created: item.no_dataset_file_created,
        },
        names: [
          "request_sha256",
          "report_sha256",
          "claim_boundary",
          "download_authorized",
          "authorizes_ingestion",
          "authorizes_execution",
          "no_dataset_file_created",
        ],
      }),
    );
    grid.appendChild(card);
  }
  section.appendChild(grid);
  return section;
}

function renderAcquisitionQualifications(items) {
  const section = progressSection(
    t("progress.qualification.title"),
    items.length > 0
      ? t("progress.qualification.subtitle", {count: items.length})
      : t("progress.qualification.empty"),
  );
  if (items.length === 0) {
    return section;
  }
  const grid = document.createElement("div");
  grid.className = "acquisition-grid";
  const stateMap = {
    "invalid-acquisition": "failed",
    "brief-only-pilot-candidate": "candidate",
    "formal-empirical-task-candidate": "observed_completed",
  };
  for (const item of items) {
    const card = document.createElement("article");
    card.className = `acquisition-card status-${item.scientific_disposition}`;
    const header = document.createElement("div");
    header.className = "compact-row-header";
    const identity = document.createElement("div");
    const label = document.createElement("span");
    label.className = "card-label";
    appendText(label, t("progress.qualification.cohort"));
    const title = document.createElement("strong");
    appendText(title, item.selection_id);
    identity.append(label, title);
    header.append(
      identity,
      progressPill(
        stateMap[item.scientific_disposition] || "unknown",
        t(`progress.qualification.status.${item.scientific_disposition}`),
      ),
    );

    const facts = document.createElement("div");
    facts.className = "acquisition-facts";
    for (const value of [
      t("progress.qualification.items", {count: item.task_count}),
      t("progress.qualification.bytes", {size: formatByteCeiling(item.observed_total_bytes)}),
      item.ready_for_brief_only_package_prepilot
        ? t("progress.qualification.brief_ready")
        : t("progress.qualification.brief_blocked"),
      item.ready_for_formal_empirical_task_binding
        ? t("progress.qualification.formal_ready")
        : t("progress.qualification.formal_blocked"),
    ]) {
      const fact = document.createElement("span");
      appendText(fact, value);
      facts.appendChild(fact);
    }

    const boundary = document.createElement("p");
    boundary.className = "acquisition-boundary";
    appendText(boundary, t("progress.qualification.boundary"));
    const blockers = document.createElement("ul");
    blockers.className = "acquisition-restrictions";
    const blockerCodes = [
      ...item.formal_task_blocker_codes,
      ...item.objective_progress_blocker_codes,
    ];
    for (const code of blockerCodes) {
      const blocker = document.createElement("li");
      appendText(blocker, localizedCode(code));
      blockers.appendChild(blocker);
    }

    const review = document.createElement("button");
    review.type = "button";
    review.className = "secondary-button acquisition-review";
    appendText(review, t("progress.qualification.review"));
    review.addEventListener("click", () => requestCandidateWorkspace(
      "review-data-acquisition-request",
    ));
    card.append(
      header,
      facts,
      boundary,
      blockers,
      review,
      evidenceDisclosure(item.support_ref_ids, {
        data: {
          request_sha256: item.request_sha256,
          receipt_sha256: item.receipt_sha256,
          report_sha256: item.report_sha256,
          report_file_sha256: item.report_file_sha256,
          authorizes_ingestion: item.authorizes_ingestion,
          authorizes_execution: item.authorizes_execution,
          provider_call_performed: item.provider_call_performed,
          gpu_work_performed: item.gpu_work_performed,
        },
        names: [
          "request_sha256",
          "receipt_sha256",
          "report_sha256",
          "report_file_sha256",
          "authorizes_ingestion",
          "authorizes_execution",
          "provider_call_performed",
          "gpu_work_performed",
        ],
      }),
    );
    grid.appendChild(card);
  }
  section.appendChild(grid);
  return section;
}

function renderDatasetPackages(items) {
  const section = progressSection(
    t("progress.dataset_package.title"),
    items.length > 0
      ? t("progress.dataset_package.subtitle", {count: items.length})
      : t("progress.dataset_package.empty"),
  );
  if (items.length === 0) {
    return section;
  }
  const grid = document.createElement("div");
  grid.className = "acquisition-grid";
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "acquisition-card dataset-package-card";
    const header = document.createElement("div");
    header.className = "compact-row-header";
    const identity = document.createElement("div");
    const label = document.createElement("span");
    label.className = "card-label";
    appendText(label, t("progress.dataset_package.request"));
    const title = document.createElement("strong");
    appendText(title, item.request_id);
    identity.append(label, title);
    header.append(
      identity,
      progressPill(
        item.ready_for_owner_approval
          ? "candidate"
          : item.metadata_review_ready
            ? "blocked"
            : "failed",
        item.ready_for_owner_approval
          ? t("progress.dataset_package.approval_ready")
          : item.metadata_review_ready
            ? t("progress.dataset_package.license_blocked")
            : t("progress.dataset_package.metadata_blocked"),
      ),
    );

    const flow = document.createElement("div");
    flow.className = "dataset-package-flow";
    const flowItems = [
      [String(item.asset_count), t("progress.dataset_package.archives")],
      [formatByteCeiling(item.observed_download_bytes), t("progress.dataset_package.download")],
      [formatByteCeiling(item.maximum_unpacked_bytes), t("progress.dataset_package.unpacked")],
      [formatByteCeiling(item.minimum_free_storage_bytes), t("progress.dataset_package.free")],
    ];
    for (const [value, copy] of flowItems) {
      const fact = document.createElement("div");
      const amount = document.createElement("strong");
      appendText(amount, value);
      const factLabel = document.createElement("small");
      appendText(factLabel, copy);
      fact.append(amount, factLabel);
      flow.appendChild(fact);
    }

    const taskGrid = document.createElement("div");
    taskGrid.className = "dataset-package-tasks";
    for (const task of item.task_qualifications) {
      const taskCard = document.createElement("div");
      const taskName = document.createElement("strong");
      appendText(taskName, localizedCode(task.task_id));
      const taskFacts = document.createElement("small");
      appendText(taskFacts, t("progress.dataset_package.task_summary", {
        count: task.asset_count,
        size: formatByteCeiling(task.observed_compressed_bytes),
      }));
      const license = document.createElement("span");
      license.className = "dataset-package-license";
      appendText(license, t(`progress.dataset_package.license.${task.license_disposition}`));
      taskCard.append(taskName, taskFacts, license);
      taskGrid.appendChild(taskCard);
    }

    const blockerCodes = [
      ...item.approval_blocker_codes,
      ...item.pending_qualification_codes,
    ];
    const blockers = document.createElement("ul");
    blockers.className = "acquisition-restrictions dataset-package-blockers";
    for (const code of blockerCodes.slice(0, 5)) {
      const blocker = document.createElement("li");
      appendText(blocker, localizedCode(code));
      blockers.appendChild(blocker);
    }

    const controlPath = document.createElement("div");
    controlPath.className = "dataset-package-control-path";
    const controlLabel = document.createElement("strong");
    appendText(controlLabel, t("progress.dataset_package.control_path"));
    const controlSteps = document.createElement("span");
    appendText(controlSteps, t("progress.dataset_package.control_steps"));
    controlPath.append(controlLabel, controlSteps);

    const boundary = document.createElement("p");
    boundary.className = "acquisition-boundary";
    appendText(boundary, t("progress.dataset_package.boundary", {
      hashes: item.pending_content_hash_count,
    }));
    const review = document.createElement("button");
    review.type = "button";
    review.className = "secondary-button acquisition-review";
    appendText(review, t("progress.dataset_package.review"));
    review.addEventListener("click", () => requestCandidateWorkspace(
      "review-data-acquisition-request",
    ));
    card.append(
      header,
      flow,
      taskGrid,
      blockers,
      controlPath,
      boundary,
      review,
      evidenceDisclosure(item.support_ref_ids, {
        data: {
          proposal_sha256: item.proposal_sha256,
          report_sha256: item.report_sha256,
          report_file_sha256: item.report_file_sha256,
          source_hosts: item.source_hosts,
          authorizes_network_preflight: item.authorizes_network_preflight,
          authorizes_download: item.authorizes_download,
          authorizes_ingestion: item.authorizes_ingestion,
          authorizes_api_calls: item.authorizes_api_calls,
          authorizes_gpu_work: item.authorizes_gpu_work,
          authorizes_execution: item.authorizes_execution,
          no_dataset_file_created: item.no_dataset_file_created,
        },
        names: [
          "proposal_sha256",
          "report_sha256",
          "report_file_sha256",
          "source_hosts",
          "authorizes_network_preflight",
          "authorizes_download",
          "authorizes_ingestion",
          "authorizes_api_calls",
          "authorizes_gpu_work",
          "authorizes_execution",
          "no_dataset_file_created",
        ],
      }),
    );
    grid.appendChild(card);
  }
  section.appendChild(grid);
  return section;
}

function renderBenchmarkQualifications(items) {
  const section = progressSection(
    t("progress.benchmark_qualification.title"),
    items.length > 0
      ? t("progress.benchmark_qualification.subtitle", {count: items.length})
      : t("progress.benchmark_qualification.empty"),
  );
  if (items.length === 0) {
    return section;
  }
  const grid = document.createElement("div");
  grid.className = "acquisition-grid";
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "acquisition-card benchmark-qualification-card";
    const header = document.createElement("div");
    header.className = "compact-row-header";
    const identity = document.createElement("div");
    const label = document.createElement("span");
    label.className = "card-label";
    appendText(label, t("progress.benchmark_qualification.candidate"));
    const title = document.createElement("strong");
    appendText(title, item.candidate_id);
    identity.append(label, title);
    header.append(
      identity,
      progressPill(
        item.metadata_review_ready ? "candidate" : "failed",
        item.metadata_review_ready
          ? t("progress.benchmark_qualification.metadata_ready")
          : t("progress.benchmark_qualification.metadata_blocked"),
      ),
    );

    const funnel = document.createElement("div");
    funnel.className = "benchmark-funnel";
    const funnelValues = [
      [item.accepted_task_count, t("progress.benchmark_qualification.accepted")],
      [item.selected_task_count, t("progress.benchmark_qualification.capacity_fit")],
      [
        item.first_preflight_candidate_ids.length,
        t("progress.benchmark_qualification.preflight_first"),
      ],
    ];
    for (const [index, [value, copy]] of funnelValues.entries()) {
      if (index > 0) {
        const arrow = document.createElement("span");
        arrow.className = "benchmark-funnel-arrow";
        arrow.setAttribute("aria-hidden", "true");
        appendText(arrow, "→");
        funnel.appendChild(arrow);
      }
      const step = document.createElement("div");
      step.className = "benchmark-funnel-step";
      const count = document.createElement("strong");
      appendText(count, String(value));
      const stepLabel = document.createElement("small");
      appendText(stepLabel, copy);
      step.append(count, stepLabel);
      funnel.appendChild(step);
    }

    const budget = document.createElement("div");
    budget.className = "benchmark-budget";
    const budgetCopy = document.createElement("span");
    appendText(budgetCopy, t("progress.benchmark_qualification.budget", {
      used: item.planned_gpu_hours,
      cap: item.formal_gpu_hour_cap,
    }));
    const budgetTrack = document.createElement("div");
    budgetTrack.className = "benchmark-budget-track";
    const budgetFill = document.createElement("span");
    budgetFill.style.width = `${Math.min(
      100,
      (item.planned_gpu_hours / item.formal_gpu_hour_cap) * 100,
    )}%`;
    budgetTrack.appendChild(budgetFill);
    budget.append(budgetCopy, budgetTrack);

    const groups = document.createElement("div");
    groups.className = "benchmark-task-groups";
    const groupDefinitions = [
      [
        t("progress.benchmark_qualification.first_tasks"),
        item.first_preflight_candidate_ids,
      ],
      [
        t("progress.benchmark_qualification.memory_excluded"),
        item.excluded_task_ids,
      ],
    ];
    for (const [groupLabel, taskIds] of groupDefinitions) {
      const group = document.createElement("div");
      const heading = document.createElement("strong");
      appendText(heading, groupLabel);
      const list = document.createElement("ul");
      for (const taskId of taskIds) {
        const row = document.createElement("li");
        appendText(row, localizedCode(taskId));
        list.appendChild(row);
      }
      group.append(heading, list);
      groups.appendChild(group);
    }

    const boundary = document.createElement("p");
    boundary.className = "acquisition-boundary";
    appendText(
      boundary,
      item.requires_additional_48gb_single_device_resource
        ? t("progress.benchmark_qualification.boundary_48gb")
        : t("progress.benchmark_qualification.boundary"),
    );
    const gates = document.createElement("div");
    gates.className = "acquisition-facts";
    for (const [ready, readyKey, blockedKey] of [
      [
        item.acquisition_request_ready,
        "progress.benchmark_qualification.acquisition_ready",
        "progress.benchmark_qualification.acquisition_blocked",
      ],
      [
        item.local_preflight_ready,
        "progress.benchmark_qualification.preflight_ready",
        "progress.benchmark_qualification.preflight_blocked",
      ],
      [
        item.experiment_ready,
        "progress.benchmark_qualification.experiment_ready",
        "progress.benchmark_qualification.experiment_blocked",
      ],
    ]) {
      const fact = document.createElement("span");
      appendText(fact, t(ready ? readyKey : blockedKey));
      gates.appendChild(fact);
    }

    const review = document.createElement("button");
    review.type = "button";
    review.className = "secondary-button acquisition-review";
    appendText(review, t("progress.benchmark_qualification.review"));
    review.addEventListener("click", () => requestCandidateWorkspace(
      "review-benchmark-qualification",
    ));
    card.append(
      header,
      funnel,
      budget,
      groups,
      boundary,
      gates,
      review,
      evidenceDisclosure(item.support_ref_ids, {
        data: {
          proposal_sha256: item.proposal_sha256,
          report_sha256: item.report_sha256,
          report_file_sha256: item.report_file_sha256,
          planned_cells: item.planned_cells,
          authorizes_download: item.authorizes_download,
          authorizes_api_calls: item.authorizes_api_calls,
          authorizes_gpu_work: item.authorizes_gpu_work,
          authorizes_execution: item.authorizes_execution,
          external_action_performed: item.external_action_performed,
        },
        names: [
          "proposal_sha256",
          "report_sha256",
          "report_file_sha256",
          "planned_cells",
          "authorizes_download",
          "authorizes_api_calls",
          "authorizes_gpu_work",
          "authorizes_execution",
          "external_action_performed",
        ],
      }),
    );
    grid.appendChild(card);
  }
  section.appendChild(grid);
  return section;
}

function renderProjectLifecycle(data) {
  const section = progressSection(
    t("lifecycle.title"),
    t("lifecycle.subtitle"),
  );
  section.classList.add("project-lifecycle");
  const header = document.createElement("div");
  header.className = "lifecycle-header";
  const state = document.createElement("strong");
  appendText(state, t(`lifecycle.state.${data.lifecycle_state}`));
  const authority = document.createElement("small");
  appendText(authority, t("lifecycle.no_official_authority"));
  header.append(state, authority);

  const rail = document.createElement("ol");
  rail.className = "project-lifecycle-rail";
  for (const gate of data.gates) {
    const node = document.createElement("li");
    node.className = `lifecycle-node state-${gate.state}`;
    const marker = document.createElement("span");
    marker.className = "lifecycle-marker";
    marker.setAttribute("aria-hidden", "true");
    const copy = document.createElement("div");
    const label = document.createElement("strong");
    appendText(label, t(`lifecycle.gate.${gate.gate_id}`));
    const reason = document.createElement("small");
    appendText(reason, localizedCode(gate.reason_code));
    copy.append(label, reason);
    const pill = document.createElement("span");
    pill.className = `lifecycle-state state-${gate.state}`;
    appendText(pill, t(`lifecycle.gate_state.${gate.state}`));
    node.append(marker, copy, pill);
    if (gate.support_ref_ids.length > 0) {
      node.appendChild(evidenceDisclosure(gate.support_ref_ids));
    }
    rail.appendChild(node);
  }
  const gateDetails = document.createElement("details");
  gateDetails.className = "lifecycle-gate-details";
  const gateSummary = document.createElement("summary");
  appendText(gateSummary, t("lifecycle.show_gates", {count: data.gates.length}));
  gateDetails.append(gateSummary, rail, evidenceDisclosure(data.support_ref_ids, {
    data: {
      idea_to_paper_complete: data.idea_to_paper_complete,
      internal_review_cycle_complete: data.internal_review_cycle_complete,
      independent_pre_submission_review_complete:
        data.independent_pre_submission_review_complete,
      scientific_evidence_complete: data.scientific_evidence_complete,
      paper_scientific_evidence_bound: data.paper_scientific_evidence_bound,
      top_venue_evidence_loop_complete: data.top_venue_evidence_loop_complete,
      official_decision_authority: data.official_decision_authority,
      scientific_effectiveness_established: data.scientific_effectiveness_established,
    },
    names: [
      "idea_to_paper_complete",
      "internal_review_cycle_complete",
      "independent_pre_submission_review_complete",
      "scientific_evidence_complete",
      "paper_scientific_evidence_bound",
      "top_venue_evidence_loop_complete",
      "official_decision_authority",
      "scientific_effectiveness_established",
    ],
  }));
  section.append(header, gateDetails);
  return section;
}

function renderEvidenceGraph(data) {
  const container = document.createElement("div");
  container.className = "evidence-graph-workspace";
  const instructions = document.createElement("p");
  instructions.className = "evidence-graph-instructions";
  appendText(instructions, t("graph.instructions"));

  const namespace = "http://www.w3.org/2000/svg";
  const width = 760;
  const height = 420;
  const canvas = document.createElementNS(namespace, "svg");
  canvas.classList.add("evidence-graph-canvas");
  canvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", t("graph.aria", {
    nodes: data.nodes.length,
    edges: data.edges.length,
  }));

  const positions = new Map();
  data.nodes.forEach((node, index) => {
    if (index === 0) {
      positions.set(node.evidence_ref_id, {x: width / 2, y: height / 2});
      return;
    }
    const count = Math.max(1, data.nodes.length - 1);
    const angle = ((index - 1) / count) * Math.PI * 2 - Math.PI / 2;
    positions.set(node.evidence_ref_id, {
      x: width / 2 + Math.cos(angle) * 285,
      y: height / 2 + Math.sin(angle) * 150,
    });
  });

  for (const edge of data.edges) {
    const source = positions.get(edge.source_ref_id);
    const target = positions.get(edge.target_ref_id);
    const line = document.createElementNS(namespace, "line");
    line.classList.add("evidence-graph-edge");
    line.setAttribute("x1", source.x);
    line.setAttribute("y1", source.y);
    line.setAttribute("x2", target.x);
    line.setAttribute("y2", target.y);
    const edgeTitle = document.createElementNS(namespace, "title");
    appendText(edgeTitle, readableCode(edge.relation));
    line.appendChild(edgeTitle);
    canvas.appendChild(line);
  }

  const detail = document.createElement("section");
  detail.className = "evidence-graph-detail";
  detail.setAttribute("aria-live", "polite");
  const graphNodes = new Map();

  function selectNode(node) {
    for (const graphNode of graphNodes.values()) {
      graphNode.classList.remove("selected");
      graphNode.setAttribute("aria-pressed", "false");
    }
    const selected = graphNodes.get(node.evidence_ref_id);
    selected.classList.add("selected");
    selected.setAttribute("aria-pressed", "true");
    detail.replaceChildren();
    const heading = document.createElement("h3");
    appendText(heading, node.label);
    const kind = document.createElement("p");
    appendText(kind, `${t("graph.kind")}: ${localizedCode(node.kind)}`);
    const reference = document.createElement("code");
    appendText(reference, node.evidence_ref_id);
    const explore = document.createElement("button");
    explore.type = "button";
    explore.className = "evidence-graph-explore";
    appendText(explore, t("graph.explore"));
    explore.addEventListener("click", () => exploreEvidenceNode(node));
    detail.append(heading, kind, reference, explore);
  }

  for (const node of data.nodes) {
    const position = positions.get(node.evidence_ref_id);
    const group = document.createElementNS(namespace, "g");
    group.classList.add("evidence-graph-node", `graph-kind-${node.kind}`);
    group.setAttribute("role", "button");
    group.setAttribute("tabindex", "0");
    group.setAttribute("aria-pressed", "false");
    group.setAttribute("aria-label", t("graph.node_aria", {
      label: node.label,
      kind: localizedCode(node.kind),
    }));
    group.setAttribute("transform", `translate(${position.x} ${position.y})`);
    const circle = document.createElementNS(namespace, "circle");
    circle.setAttribute("r", node.kind === "project_manifest" ? "45" : "34");
    const label = document.createElementNS(namespace, "text");
    label.setAttribute("y", "4");
    const compact = node.label.length > 20 ? `${node.label.slice(0, 19)}…` : node.label;
    appendText(label, compact);
    const title = document.createElementNS(namespace, "title");
    appendText(title, node.label);
    group.append(circle, label, title);
    group.addEventListener("click", () => selectNode(node));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectNode(node);
      }
    });
    graphNodes.set(node.evidence_ref_id, group);
    canvas.appendChild(group);
  }

  const initial = document.createElement("p");
  initial.className = "muted";
  appendText(initial, t("graph.select"));
  detail.appendChild(initial);
  container.append(instructions, canvas, detail);
  return container;
}

function exploreEvidenceNode(node) {
  if (!quickIntentCatalog || quickIntentCatalog.snapshot.project_id !== currentProjectId()) {
    intentResultState = {kind: "error", error: uiError("error.reload_catalog")};
    renderIntentResult();
    return;
  }
  generateWithIntent({
    schema_version: "1.0",
    kind: "free_question",
    project_id: quickIntentCatalog.snapshot.project_id,
    snapshot_revision: quickIntentCatalog.snapshot.snapshot_revision,
    snapshot_sha256: quickIntentCatalog.snapshot.snapshot_sha256,
    question: t("graph.explore_question", {
      label: node.label,
      kind: readableCode(node.kind),
      evidence: node.evidence_ref_id,
    }),
  });
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
  EvidenceGraph: renderEvidenceGraph,
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
  const key = `action.${action.proposal_kind}`;
  return hasTranslation(key) ? t(key) : action.label;
}

function renderWorkspace(documentValue, {preserveTransient = false, focus = true} = {}) {
  const renderer = documentValue.renderer;
  const generated = documentValue.status === "generated";
  const placements = new Map((documentValue.placements || []).map(
    (item) => [item.component_id, item],
  ));
  workspace.classList.remove("project-index-workspace");
  workspace.classList.toggle("generated-workspace", generated);
  workspace.replaceChildren();
  if (!preserveTransient) {
    lastProposalReceipt = null;
    lastControllerDecision = null;
    lastArtifactPreview = null;
    lastProposalError = null;
    lastArtifactError = null;
  }
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
    card.classList.add(`component-${component.renderer.replaceAll(/([a-z])([A-Z])/g, "$1-$2").toLowerCase()}`);
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
    button.className = "proposal-action-button";
    appendText(button, actionLabel(action));
    button.addEventListener("click", () => submitAction(action));
    actions.appendChild(button);
  }
  renderInteractionWorkbench();
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
  if (activeResearchWorkspace && activeResearchTurn) {
    const breadcrumb = document.createElement("nav");
    breadcrumb.className = "generation-breadcrumb";
    breadcrumb.setAttribute("aria-label", t("thread.breadcrumb_aria"));
    const projectHome = document.createElement("button");
    projectHome.type = "button";
    projectHome.className = "generation-breadcrumb-home";
    projectHome.setAttribute("aria-label", t("project.open_home_aria", {
      project: documentValue.project_id,
    }));
    appendText(projectHome, documentValue.project_id);
    projectHome.addEventListener("click", () => (
      loadWorkspace(defaultQuery(documentValue.project_id))
    ));
    const topic = document.createElement("span");
    appendText(topic, activeResearchWorkspace.title);
    const page = document.createElement("strong");
    appendText(page, t("thread.turn_page", {ordinal: activeResearchTurn.ordinal}));
    breadcrumb.append(
      projectHome,
      breadcrumbSeparator(),
      topic,
      breadcrumbSeparator(),
      page,
    );
    summary.appendChild(breadcrumb);
  }
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow dark";
  appendText(eyebrow, t("generation.validated"));
  const heading = document.createElement("h2");
  appendText(heading, t(`title.generated.${documentValue.intent.goal}`));
  const planner = documentValue.planning?.provenance;
  const metadata = document.createElement("div");
  metadata.className = "generation-metadata";
  const values = [
    [t("thread.topic"), activeResearchWorkspace?.title || t("common.missing")],
    [t("thread.page"), activeResearchTurn
      ? t("thread.turn_page", {ordinal: activeResearchTurn.ordinal})
      : t("common.missing")],
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
    workspace_id: activeResearchWorkspaceId || undefined,
    turn_id: activeResearchTurnId || undefined,
    reason_code: documentValue.reason_code,
    execution_authority: documentValue.execution_authority,
  }, ["workspace_id", "turn_id", "reason_code", "execution_authority"]));
  summary.append(eyebrow, heading, metadata, provenance);
  return summary;
}

function breadcrumbSeparator() {
  const separator = document.createElement("span");
  separator.className = "generation-breadcrumb-separator";
  separator.setAttribute("aria-hidden", "true");
  appendText(separator, "/");
  return separator;
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
    lastProposalError = null;
    renderProposalResult();
  } catch (error) {
    lastProposalError = error;
    renderProposalResult();
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
  lastArtifactError = null;
  try {
    const preview = await api(interactionPath("inspections"), {
      method: "POST",
      body: JSON.stringify(event),
    });
    lastArtifactPreview = preview;
    renderArtifactResult();
  } catch (error) {
    clearArtifactPreview();
    lastArtifactError = error;
    renderArtifactResult();
  }
}

function renderProposalResult() {
  renderInteractionWorkbench();
}

function renderProposalContent() {
  if (!proposalResult) return;
  if (lastProposalError) {
    proposalResult.dataset.state = "error";
    showError(proposalResult, lastProposalError);
    return;
  }
  if (lastControllerDecision) {
    proposalResult.dataset.state = lastControllerDecision.status;
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
  proposalResult.dataset.state = lastProposalReceipt.status;
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
    lastProposalError = null;
    renderProposalResult();
  } catch (error) {
    lastProposalError = error;
    renderProposalResult();
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
  if (artifactResult) artifactResult.replaceChildren();
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
  renderInteractionWorkbench();
}

function renderArtifactPreview(preview) {
  if (!artifactResult) return;
  clearArtifactPreview({forget: false});
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

function renderInteractionWorkbench() {
  document.getElementById("interaction-workbench")?.remove();
  proposalResult = null;
  artifactResult = null;
  const hasProposal = Boolean(
    lastProposalReceipt || lastControllerDecision || lastProposalError,
  );
  const hasArtifact = Boolean(lastArtifactPreview || lastArtifactError);
  if (!hasProposal && !hasArtifact) return;

  const workbench = document.createElement("section");
  workbench.id = "interaction-workbench";
  workbench.className = "interaction-workbench";
  const header = document.createElement("header");
  header.className = "interaction-workbench-header";
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow dark";
  appendText(eyebrow, t("workbench.eyebrow"));
  const heading = document.createElement("h2");
  appendText(heading, t("workbench.title"));
  const body = document.createElement("p");
  appendText(body, t("workbench.body"));
  header.append(eyebrow, heading, body);

  const grid = document.createElement("div");
  grid.className = "interaction-workbench-grid";
  if (hasProposal) {
    const panel = document.createElement("section");
    panel.className = "interaction-workbench-panel proposal-panel";
    const panelHeading = document.createElement("h3");
    appendText(panelHeading, t("inspector.proposal_title"));
    const panelBody = document.createElement("p");
    appendText(panelBody, t("inspector.proposal_body"));
    proposalResult = document.createElement("div");
    proposalResult.id = "proposal-result";
    proposalResult.setAttribute("role", "status");
    panel.append(panelHeading, panelBody, proposalResult);
    grid.appendChild(panel);
  }
  if (hasArtifact) {
    const panel = document.createElement("section");
    panel.className = "interaction-workbench-panel artifact-panel";
    const panelHeading = document.createElement("h3");
    appendText(panelHeading, t("inspector.evidence_title"));
    const panelBody = document.createElement("p");
    appendText(panelBody, t("inspector.evidence_body"));
    artifactResult = document.createElement("div");
    artifactResult.id = "artifact-result";
    artifactResult.setAttribute("role", "status");
    panel.append(panelHeading, panelBody, artifactResult);
    grid.appendChild(panel);
  }
  workbench.append(header, grid);
  workspace.appendChild(workbench);
  renderProposalContent();
  if (artifactResult) {
    if (lastArtifactError) showError(artifactResult, lastArtifactError);
    else if (lastArtifactPreview) renderArtifactPreview(lastArtifactPreview);
  }
}

function setIntentEnabled(enabled) {
  intentQuestion.disabled = !enabled;
  generateWorkspaceButton.disabled = !enabled;
  conversationContextMode.disabled = !enabled || !activeResearchWorkspaceId;
  for (const button of quickIntents.querySelectorAll("button")) {
    button.disabled = !enabled;
  }
}

function clearProjectContext(projectId = "") {
  activeProjectId = projectId;
  drawerProjectContext.textContent = projectId || t("thread.no_project");
  researchWorkspaceCatalog = null;
  topicSearchQuery = "";
  topicSearch.value = "";
  activeResearchWorkspaceId = "";
  activeResearchTurnId = "";
  activeResearchWorkspace = null;
  activeResearchTurn = null;
  activeResearchWorkspaceDetail = null;
  conversationContextMode.value = "recent";
  currentDocument = null;
  quickIntentCatalog = null;
  lastProposalReceipt = null;
  lastControllerDecision = null;
  lastArtifactPreview = null;
  lastProposalError = null;
  lastArtifactError = null;
  intentResultState = {kind: "empty"};
  topicManagementState = {kind: "empty"};
  responseCache.clear();
  resetCatalogs();
  intentQuestion.value = "";
  intentQuestion.style.height = "";
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
  newTopicButton.disabled = !projectId;
  topicSearch.disabled = !projectId;
  renderTopicManagementStatus();
  renderWorkspaceHistory();
}

function renderTopicManagementStatus() {
  topicManagementStatus.replaceChildren();
  if (topicManagementState.kind === "empty") {
    return;
  }
  if (topicManagementState.kind === "error") {
    showError(topicManagementStatus, topicManagementState.error);
    return;
  }
  const message = document.createElement("p");
  message.className = "muted";
  appendText(message, t("thread.renamed"));
  topicManagementStatus.appendChild(message);
}

function localizedQuickIntentText(value) {
  const descriptor = quickIntentCatalog?.intents.find(
    (item) => item.quick_intent_id === value,
  );
  if (!descriptor) {
    return value;
  }
  const labelKey = quickIntentLabelKeys[descriptor.label_code];
  return labelKey ? t(labelKey) : descriptor.label;
}

function workspaceDisplayTitle(title) {
  return localizedQuickIntentText(title);
}

function turnPromptDisplay(prompt) {
  return prompt.kind === "quick" ? localizedQuickIntentText(prompt.text) : prompt.text;
}

function renderWorkspaceHistory() {
  workspaceHistoryList.replaceChildren();
  if (!activeProjectId) {
    const empty = document.createElement("p");
    empty.className = "muted";
    appendText(empty, t("thread.open_project"));
    workspaceHistoryList.appendChild(empty);
    return;
  }
  if (!researchWorkspaceCatalog) {
    const loading = document.createElement("p");
    loading.className = "muted";
    appendText(loading, t("thread.loading"));
    workspaceHistoryList.appendChild(loading);
    return;
  }
  if (researchWorkspaceCatalog.workspaces.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    appendText(empty, t("thread.empty"));
    workspaceHistoryList.appendChild(empty);
    return;
  }
  const normalizedSearch = topicSearchQuery.trim().toLocaleLowerCase(activeLocale);
  const filteredWorkspaces = normalizedSearch
    ? researchWorkspaceCatalog.workspaces.filter((item) => (
      workspaceDisplayTitle(item.title).toLocaleLowerCase(activeLocale).includes(normalizedSearch)
      || item.title.toLocaleLowerCase(activeLocale).includes(normalizedSearch)
    ))
    : researchWorkspaceCatalog.workspaces;
  const visibleWorkspaces = [...filteredWorkspaces];
  const activeItem = researchWorkspaceCatalog.workspaces.find(
    (item) => item.workspace_id === activeResearchWorkspaceId,
  );
  if (activeItem && !visibleWorkspaces.some(
    (item) => item.workspace_id === activeResearchWorkspaceId,
  )) {
    visibleWorkspaces.unshift(activeItem);
  }
  if (filteredWorkspaces.length === 0 && !activeItem) {
    const empty = document.createElement("p");
    empty.className = "muted";
    appendText(empty, t("thread.no_match"));
    workspaceHistoryList.appendChild(empty);
    return;
  }
  const list = document.createElement("ol");
  list.className = "workspace-history-items";
  for (const item of visibleWorkspaces) {
    const displayTitle = workspaceDisplayTitle(item.title);
    const row = document.createElement("li");
    row.className = "workspace-history-topic";
    const button = document.createElement("button");
    button.type = "button";
    button.className = item.workspace_id === activeResearchWorkspaceId
      ? "workspace-history-button selected"
      : "workspace-history-button";
    const title = document.createElement("strong");
    appendText(title, displayTitle);
    const metadata = document.createElement("small");
    appendText(metadata, t("thread.turn_count", {count: item.revision}));
    const status = document.createElement("small");
    status.className = `workspace-history-status state-${item.latest_status}`;
    appendText(status, localizedCode(item.latest_status));
    button.append(title, metadata, status);
    button.addEventListener("click", () => loadResearchTurn({
      project_id: activeProjectId,
      workspace_id: item.workspace_id,
      turn_id: item.latest_turn_id,
    }));
    const actions = document.createElement("div");
    actions.className = "workspace-history-actions";
    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.className = "workspace-history-rename";
    renameButton.setAttribute("aria-label", t("thread.rename_aria", {title: displayTitle}));
    renameButton.setAttribute("title", t("thread.rename"));
    appendText(renameButton, "✎");
    renameButton.addEventListener("click", () => renameResearchWorkspace(item));
    actions.append(button, renameButton);
    row.appendChild(actions);
    if (item.workspace_id === activeResearchWorkspaceId
        && activeResearchWorkspaceDetail?.workspace.workspace_id === item.workspace_id) {
      const turns = document.createElement("ol");
      turns.className = "workspace-turn-items";
      for (const turn of activeResearchWorkspaceDetail.turns) {
        const turnRow = document.createElement("li");
        const turnButton = document.createElement("button");
        turnButton.type = "button";
        turnButton.className = turn.turn_id === activeResearchTurnId
          ? "workspace-turn-button selected"
          : "workspace-turn-button";
        const page = document.createElement("span");
        appendText(page, t("thread.turn_page", {ordinal: turn.ordinal}));
        const prompt = document.createElement("small");
        appendText(prompt, turnPromptDisplay(turn.prompt));
        const turnStatus = document.createElement("small");
        turnStatus.className = `workspace-history-status state-${turn.status}`;
        appendText(turnStatus, localizedCode(turn.status));
        turnButton.append(page, prompt, turnStatus);
        turnButton.addEventListener("click", () => loadResearchTurn({
          project_id: activeProjectId,
          workspace_id: item.workspace_id,
          turn_id: turn.turn_id,
        }));
        turnRow.appendChild(turnButton);
        turns.appendChild(turnRow);
      }
      row.appendChild(turns);
    }
    list.appendChild(row);
  }
  workspaceHistoryList.appendChild(list);
}

async function renameResearchWorkspace(item) {
  const proposed = window.prompt(t("thread.rename_prompt"), workspaceDisplayTitle(item.title));
  if (proposed === null) {
    return;
  }
  const title = proposed.trim();
  if (!title || title === item.title) {
    return;
  }
  try {
    const renamed = await api(
      `/api/v4/projects/${encodeURIComponent(activeProjectId)}`
        + `/workspaces/${encodeURIComponent(item.workspace_id)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          schema_version: "1.0",
          expected_metadata_revision: item.metadata_revision,
          expected_title: item.title,
          title,
        }),
      },
    );
    if (activeResearchWorkspaceId === renamed.workspace_id) {
      activeResearchWorkspace = renamed;
      if (activeResearchWorkspaceDetail) {
        activeResearchWorkspaceDetail = {
          ...activeResearchWorkspaceDetail,
          workspace: renamed,
        };
      }
    }
    topicManagementState = {kind: "renamed"};
    renderTopicManagementStatus();
    await loadResearchWorkspaceCatalog(activeProjectId);
  } catch (error) {
    await loadResearchWorkspaceCatalog(activeProjectId);
    if (activeResearchWorkspaceId === item.workspace_id) {
      await loadResearchWorkspaceDetail(activeProjectId, item.workspace_id);
    }
    topicManagementState = {kind: "error", error};
    renderTopicManagementStatus();
  }
}

async function loadResearchWorkspaceCatalog(projectId) {
  const requestedProject = projectId;
  try {
    const catalog = await api(
      `/api/v4/projects/${encodeURIComponent(projectId)}/workspaces`,
    );
    if (activeProjectId !== requestedProject) {
      return;
    }
    researchWorkspaceCatalog = catalog;
    renderWorkspaceHistory();
  } catch (error) {
    if (activeProjectId !== requestedProject) {
      return;
    }
    showError(workspaceHistoryList, error);
  }
}

async function loadResearchWorkspaceDetail(projectId, workspaceId) {
  const requestedProject = projectId;
  const requestedWorkspace = workspaceId;
  try {
    const detail = await api(
      `/api/v4/projects/${encodeURIComponent(projectId)}`
        + `/workspaces/${encodeURIComponent(workspaceId)}`,
    );
    if (activeProjectId !== requestedProject
        || activeResearchWorkspaceId !== requestedWorkspace) {
      return;
    }
    activeResearchWorkspaceDetail = detail;
    conversationContextMode.disabled = !quickIntentCatalog || !activeResearchWorkspaceId;
    renderWorkspaceHistory();
  } catch (error) {
    if (activeProjectId !== requestedProject
        || activeResearchWorkspaceId !== requestedWorkspace) {
      return;
    }
    activeResearchWorkspaceDetail = null;
    showError(workspaceHistoryList, error);
  }
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
    renderWorkspaceHistory();
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
  const selectedContextTurnIds = (
    activeResearchWorkspaceId
    && conversationContextMode.value === "recent"
    && activeResearchWorkspaceDetail?.workspace.workspace_id === activeResearchWorkspaceId
  )
    ? activeResearchWorkspaceDetail.turns.map((item) => item.turn_id).slice(-8)
    : [];
  setIntentEnabled(false);
  intentResultState = {kind: "resolving"};
  renderIntentResult();
  try {
    const base = `/api/v4/projects/${encodeURIComponent(requestedProject)}/workspaces`;
    const path = activeResearchWorkspaceId
      ? `${base}/${encodeURIComponent(activeResearchWorkspaceId)}/turns`
      : base;
    const turnDocument = await api(
      path,
      {
        method: "POST",
        body: JSON.stringify({
          schema_version: "1.0",
          quick_catalog_fingerprint: requestedCatalog,
          intent_request: intentRequest,
          context_turn_ids: selectedContextTurnIds,
        }),
      },
    );
    if (activeProjectId !== requestedProject) {
      return;
    }
    activeResearchWorkspace = turnDocument.workspace;
    activeResearchWorkspaceId = turnDocument.workspace.workspace_id;
    activeResearchTurnId = turnDocument.turn.turn_id;
    activeResearchTurn = turnDocument.turn;
    activeResearchWorkspaceDetail = null;
    const documentValue = turnDocument.turn.document;
    if (documentValue.status !== "generated") {
      renderGenerationFailure(documentValue);
      await Promise.all([
        loadResearchWorkspaceCatalog(requestedProject),
        loadResearchWorkspaceDetail(requestedProject, activeResearchWorkspaceId),
      ]);
      return;
    }
    currentDocument = documentValue;
    renderWorkspace(documentValue);
    intentResultState = {
      kind: "accepted",
      mode: documentValue.planning.provenance.mode,
      contextCount: documentValue.context_turn_ids.length,
    };
    renderIntentResult();
    const route = researchTurnHash(turnDocument);
    history.pushState({route}, "", route);
    await Promise.all([
      loadResearchWorkspaceCatalog(requestedProject),
      loadResearchWorkspaceDetail(requestedProject, activeResearchWorkspaceId),
    ]);
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
    const context = document.createElement("p");
    context.className = "muted";
    appendText(context, intentResultState.contextCount > 0
      ? t("generation.context_used", {count: intentResultState.contextCount})
      : t("generation.context_none"));
    intentResult.appendChild(context);
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

function renderProjectIndex(discovery, historyMode = "push") {
  clearProjectContext();
  projectDiscovery = discovery;
  workspace.replaceChildren();
  workspace.classList.add("project-index-workspace");
  const header = document.createElement("section");
  header.className = "project-index-header";
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow dark";
  appendText(eyebrow, t("project.index.eyebrow"));
  const title = document.createElement("h2");
  appendText(title, t("project.index.title"));
  const summary = document.createElement("p");
  appendText(summary, t("project.index.summary", {count: discovery.projects.length}));
  header.append(eyebrow, title, summary);
  const grid = document.createElement("div");
  grid.className = "project-index-grid";
  for (const project of discovery.projects) {
    const card = document.createElement("article");
    card.className = "project-index-card";
    const heading = document.createElement("h3");
    appendText(heading, project.project_id);
    const facts = fixedFields(project, ["revision", "paper_count", "has_current_run"]);
    const open = document.createElement("button");
    open.type = "button";
    appendText(open, t("project.open_home"));
    open.addEventListener("click", () => loadWorkspace(defaultQuery(project.project_id)));
    card.append(heading, facts, open);
    grid.appendChild(card);
  }
  workspace.append(header, grid);
  workspace.setAttribute("aria-busy", "false");
  setFreshnessStatus("freshness.project_index");
  updateActiveView(null);
  if (historyMode !== "none") {
    const route = localizedHash("#/");
    if (historyMode === "replace") {
      history.replaceState({route}, "", route);
    } else {
      history.pushState({route}, "", route);
    }
  }
}

async function loadProjects() {
  clearProjectContext();
  setBusy(true);
  try {
    const discovery = await api("/api/v2/workspace/projects");
    projectDiscovery = discovery;
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
    globalHomeButton.disabled = false;
    for (const button of viewButtons) {
      button.disabled = !available;
    }
    setConnectionStatus(available ? "connection.ready" : "connection.no_projects");
    if (!available) {
      renderProjectIndex(discovery, "replace");
      setBusy(false);
      return;
    }
    const deepLink = parseWorkspaceHash();
    if (deepLink && discovery.projects.some((item) => item.project_id === deepLink.project_id)) {
      projectSelect.value = deepLink.project_id;
      if (deepLink.workspace_id) {
        await loadResearchTurn(deepLink, "replace");
      } else if (deepLink.generation_id) {
        await loadGeneratedWorkspace(deepLink, "replace");
      } else {
        await loadWorkspace(deepLink, "replace");
      }
    } else {
      renderProjectIndex(discovery, "replace");
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
    await loadResearchWorkspaceCatalog(documentValue.query.project_id);
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
    activeResearchWorkspace = null;
    activeResearchWorkspaceId = "";
    activeResearchTurnId = "";
    activeResearchTurn = null;
    activeResearchWorkspaceDetail = null;
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
    await loadResearchWorkspaceCatalog(documentValue.project_id);
  } catch (error) {
    currentDocument = null;
    setBusy(false);
    setFreshnessStatus("freshness.generated_unverified");
    showError(workspace, error);
    workspace.focus({preventScroll: true});
  }
}

async function loadResearchTurn(route, historyMode = "push") {
  if (!validProjectId(route.project_id)
      || !validEntryId(route.workspace_id)
      || !validEntryId(route.turn_id)) {
    throw uiError("error.generated_identity");
  }
  if (activeProjectId !== route.project_id) {
    clearProjectContext(route.project_id);
  }
  setBusy(true);
  try {
    const turnDocument = await api(
      `/api/v4/projects/${encodeURIComponent(route.project_id)}`
      + `/workspaces/${encodeURIComponent(route.workspace_id)}`
      + `/turns/${encodeURIComponent(route.turn_id)}`,
    );
    const documentValue = turnDocument.turn.document;
    activeResearchWorkspace = turnDocument.workspace;
    activeResearchWorkspaceId = turnDocument.workspace.workspace_id;
    activeResearchTurnId = turnDocument.turn.turn_id;
    activeResearchTurn = turnDocument.turn;
    activeResearchWorkspaceDetail = null;
    projectSelect.value = documentValue.project_id;
    if (documentValue.status !== "generated") {
      renderGenerationFailure(documentValue);
      throw uiError("error.generation_unrenderable");
    }
    currentDocument = documentValue;
    renderWorkspace(documentValue);
    if (historyMode !== "none") {
      const hash = researchTurnHash(turnDocument);
      if (historyMode === "replace") {
        history.replaceState({route: hash}, "", hash);
      } else {
        history.pushState({route: hash}, "", hash);
      }
    }
    setConnectionStatus("connection.turn_loaded");
    if (!quickIntentCatalog) {
      await loadQuickIntents(documentValue.project_id);
    }
    await Promise.all([
      loadResearchWorkspaceCatalog(documentValue.project_id),
      loadResearchWorkspaceDetail(documentValue.project_id, activeResearchWorkspaceId),
    ]);
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

function researchTurnHash(turnDocument) {
  return localizedHash(
    `#/projects/${encodeURIComponent(turnDocument.workspace.project_id)}`
      + `/workspaces/${encodeURIComponent(turnDocument.workspace.workspace_id)}`
      + `/turns/${encodeURIComponent(turnDocument.turn.turn_id)}`,
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
  if (view === "workspaces" && marker && first === "turns" && second && parts.length === 5) {
    if (!validProjectId(projectId) || !validEntryId(marker) || !validEntryId(second)) {
      return null;
    }
    return {project_id: projectId, workspace_id: marker, turn_id: second};
  }
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
  const headers = {};
  const cached = responseCache.get(path);
  if ((options.method === undefined || options.method === "GET") && cached) {
    headers["If-None-Match"] = cached.etag;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {...options, headers, credentials: "same-origin"});
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
  drawerProjectContext.textContent = activeProjectId || t("thread.no_project");
  renderDrawerState();
  if (connectionStatusError) {
    showError(connectionStatus, connectionStatusError);
  } else {
    setConnectionStatus(connectionStatusKey);
  }
  if (currentDocument) {
    renderWorkspace(currentDocument, {preserveTransient: true, focus: false});
  } else if (projectDiscovery && accessReady) {
    renderProjectIndex(projectDiscovery, "none");
  } else {
    setFreshnessStatus(freshnessStatusKey || "freshness.none");
    renderProposalResult();
    renderArtifactResult();
  }
  renderQuickIntents();
  renderIntentResult();
  renderTopicManagementStatus();
  renderWorkspaceHistory();
  setIntentEnabled(Boolean(quickIntentCatalog) && intentResultState.kind !== "resolving");
}

async function initializeLocalization() {
  localeSelect.disabled = true;
  try {
    await loadLocaleCatalogs();
    rerenderForLocale();
    replaceHashLocale();
    localeSelect.disabled = false;
    await initializeAccess();
  } catch (error) {
    activeLocale = "en";
    document.documentElement.lang = "en";
    localeSelect.value = "en";
    localeSelect.disabled = true;
    connectionStatus.textContent = error instanceof Error
      ? error.message
      : "Interface language resources could not be verified.";
  }
}

async function initializeAccess() {
  setConnectionStatus("connection.connecting");
  const response = await fetch("/session", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw uiError("error.local_session");
  }
  accessReady = true;
  await loadProjects();
}

skipLink.addEventListener("click", (event) => {
  event.preventDefault();
  workspace.focus({preventScroll: false});
});
drawerToggle.addEventListener("click", () => {
  setDrawerPinned(!drawerPinned, {focus: !drawerPinned});
});
drawerClose.addEventListener("click", () => {
  setDrawerPinned(false);
  drawerToggle.focus({preventScroll: true});
});
drawerBackdrop.addEventListener("click", () => setDrawerPinned(false));
drawerEdge.addEventListener("pointerenter", previewDrawer);
drawerEdge.addEventListener("pointerleave", scheduleDrawerPreviewClose);
projectDrawer.addEventListener("pointerenter", clearDrawerCloseTimer);
projectDrawer.addEventListener("pointerleave", scheduleDrawerPreviewClose);
projectDrawer.addEventListener("focusin", () => {
  clearDrawerCloseTimer();
  if (!drawerPinned) {
    drawerPreview = true;
    renderDrawerState();
  }
});
projectDrawer.addEventListener("focusout", (event) => {
  if (!projectDrawer.contains(event.relatedTarget)
      && !drawerEdge.contains(event.relatedTarget)) {
    scheduleDrawerPreviewClose();
  }
});
projectDrawer.addEventListener("click", (event) => {
  if (event.target.closest("button")) {
    closeDrawerOnMobile();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && evidenceTools.open) {
    evidenceTools.removeAttribute("open");
  }
  if (event.key === "Escape" && isDrawerOpen()) {
    setDrawerPinned(false);
    drawerToggle.focus({preventScroll: true});
  }
});
compactNavigation.addEventListener("change", () => setDrawerPinned(false));
evidenceTools.addEventListener("click", (event) => {
  if (event.target.closest("button")) {
    evidenceTools.removeAttribute("open");
  }
});
document.addEventListener("pointerdown", (event) => {
  if (evidenceTools.open && !evidenceTools.contains(event.target)) {
    evidenceTools.removeAttribute("open");
  }
});
localeSelect.addEventListener("change", () => {
  activeLocale = normalizeLocale(localeSelect.value);
  replaceHashLocale();
  rerenderForLocale();
});
globalHomeButton.addEventListener("click", () => {
  if (projectDiscovery) {
    renderProjectIndex(projectDiscovery);
  }
});
newTopicButton.addEventListener("click", () => {
  if (!activeProjectId) {
    return;
  }
  topicSearchQuery = "";
  topicSearch.value = "";
  topicManagementState = {kind: "empty"};
  renderTopicManagementStatus();
  activeResearchWorkspaceId = "";
  activeResearchTurnId = "";
  activeResearchWorkspace = null;
  activeResearchTurn = null;
  activeResearchWorkspaceDetail = null;
  conversationContextMode.value = "recent";
  conversationContextMode.disabled = true;
  renderWorkspaceHistory();
  loadWorkspace(defaultQuery(activeProjectId));
});
topicSearch.addEventListener("input", () => {
  topicSearchQuery = topicSearch.value;
  renderWorkspaceHistory();
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
  intentQuestion.style.height = "";
  generateWithIntent({
    schema_version: "1.0",
    kind: "free_question",
    project_id: quickIntentCatalog.snapshot.project_id,
    snapshot_revision: quickIntentCatalog.snapshot.snapshot_revision,
    snapshot_sha256: quickIntentCatalog.snapshot.snapshot_sha256,
    question,
  });
});
intentQuestion.addEventListener("input", () => {
  intentQuestion.style.height = "auto";
  intentQuestion.style.height = `${Math.min(intentQuestion.scrollHeight, 136)}px`;
});
intentQuestion.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    intentForm.requestSubmit();
  }
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
  if (route && accessReady) {
    if (route.workspace_id) {
      loadResearchTurn(route, "none");
    } else if (route.generation_id) {
      loadGeneratedWorkspace(route, "none");
    } else {
      loadWorkspace(route, "none");
    }
  } else if (accessReady && projectDiscovery) {
    renderProjectIndex(projectDiscovery, "none");
  }
});

initializeLocalization();
