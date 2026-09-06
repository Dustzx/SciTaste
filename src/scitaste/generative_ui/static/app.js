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

function renderProjectProgress(data) {
  const container = document.createElement("div");
  container.className = "progress-board";

  const status = document.createElement("div");
  status.className = `progress-status state-${data.project_state}`;
  const statusTitle = document.createElement("strong");
  appendText(statusTitle, `Observed project state · ${data.project_state}`);
  status.append(statusTitle, fixedFields(data, [
    "project_status", "publication_ready", "summary_ref_ids",
  ]));

  const counts = fixedFields(data.counts, [
    "runs_registered",
    "runs_completed",
    "runs_active",
    "runs_candidates",
    "runs_blocked",
    "runs_failed",
    "runs_unavailable",
    "runs_unknown",
    "completed_stages",
    "papers_registered",
  ]);
  counts.classList.add("progress-counts");
  container.append(status, titledSection("Observed records · no inferred percentage", counts));

  container.appendChild(titledSection("Declared focus and next gate", fixedFields(data, [
    "focus",
    "focus_status",
    "next_gate",
    "focus_ref_ids",
  ])));

  if (data.current_run_id) {
    container.appendChild(titledSection("Selected current run · selection is not execution", fixedFields(data, [
      "current_run_id",
      "current_run_status",
      "current_run_state",
      "current_run_ref_ids",
    ])));
  }

  if (data.milestones.length > 0) {
    container.appendChild(titledSection("Declared project milestones", fixedRows(data.milestones, [
      "milestone_id",
      "recorded_on",
      "reported_status",
      "observed_state",
      "decision",
      "evidence_locator",
      "evidence_binding",
      "support_ref_ids",
    ])));
  } else {
    container.appendChild(titledSection("Declared project milestones", fixedFields(data, [
      "milestone_state", "milestone_reason_code",
    ])));
  }

  if (data.attention.length > 0) {
    container.appendChild(titledSection("Blocked and failed registered work", fixedRows(data.attention, [
      "run_id",
      "reported_status",
      "classification",
      "detail_state",
      "recorded_reasons",
      "source_locator",
      "support_ref_ids",
    ])));
  }

  container.appendChild(titledSection("Latest registered activity · manifest order", fixedRows(
    data.recent_activity,
    [
      "run_id",
      "reported_status",
      "observed_state",
      "provider",
      "model_name",
      "condition",
      "evidence_scope",
      "selected",
      "superseded",
      "source_locator",
      "support_ref_ids",
    ],
  )));

  if (data.stages.length > 0) {
    container.appendChild(titledSection("Observed AutoResearchClaw stages", fixedRows(data.stages, [
      "stage",
      "label_en",
      "label_zh",
      "observed_state",
      "artifact_count",
      "output_locator",
      "support_ref_ids",
    ])));
  } else {
    container.appendChild(titledSection("AutoResearchClaw stage evidence", fixedFields(data, [
      "stage_semantics", "stage_state", "stage_reason_code",
    ])));
  }

  if (data.papers.length > 0) {
    container.appendChild(titledSection("Registered papers", fixedRows(data.papers, [
      "paper_id",
      "title",
      "reported_status",
      "observed_state",
      "publication_ready",
      "selected",
      "support_ref_ids",
    ])));
  }

  container.appendChild(titledSection("Evidence-supported next-step candidates", fixedRows(
    data.next_step_candidates,
    ["kind", "label_code", "target_ids", "support_ref_ids"],
  )));
  return container;
}

const componentRenderers = Object.freeze({
  ProjectSummaryCard: (data) => fixedFields(
    data,
    ["project_status", "publication_ready", "current_focus", "project_ref_id"],
  ),
  StageTimeline: (data) => fixedRows(data.stages, ["stage", "status", "stage_ref_id"]),
  BlockerList: (data) => fixedRows(
    data.blockers,
    ["blocker_id", "severity", "status", "summary", "blocker_ref_id"],
  ),
  RunHealth: (data) => fixedFields(
    data,
    ["run_status", "failure_stage", "retry_safe", "schema_valid", "run_ref_id"],
  ),
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
  RunBlockerPanel: (data) => fixedRows(
    data.blockers,
    ["run_id", "run_status", "classification", "reason_code", "source_locator"],
  ),
  PendingProposalList: (data) => fixedRows(
    data.proposals,
    ["event_id", "action_id", "status", "next_boundary", "execution_authority"],
  ),
  ProjectProgressBoard: renderProjectProgress,
});

function renderWorkspace(documentValue) {
  const renderer = documentValue.renderer;
  workspace.replaceChildren();
  proposalResult.replaceChildren();
  clearArtifactPreview();
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
    const heading = document.createElement("h2");
    appendText(heading, component.title);
    card.append(heading, renderComponent(component.data));
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
  updateActiveView(documentValue.query.view);
  workspace.setAttribute("aria-busy", "false");
  workspace.focus({preventScroll: true});
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
    const receipt = await api(`${workspacePath(currentDocument.query)}/events`, {
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
    const preview = await api(`${workspacePath(currentDocument.query)}/inspections`, {
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

async function loadProjects() {
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
      await loadWorkspace(deepLink, "replace");
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
  resetCatalogs();
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
  } catch (error) {
    currentDocument = null;
    setBusy(false);
    freshness.textContent = "Workspace freshness could not be verified.";
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
  return projectSelect.value || currentDocument?.query?.project_id || "";
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
  resetCatalogs();
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
  const query = parseWorkspaceHash();
  if (query && tokenInput.value) {
    loadWorkspace(query, "none");
  }
});
