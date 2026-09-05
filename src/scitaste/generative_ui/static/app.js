const tokenInput = document.getElementById("bearer-token");
const connectButton = document.getElementById("connect");
const projectSelect = document.getElementById("project-select");
const loadButton = document.getElementById("load-project");
const connectionStatus = document.getElementById("connection-status");
const workspace = document.getElementById("workspace");
const proposalResult = document.getElementById("proposal-result");

let currentRenderer = null;
let eventCounter = 0;

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
  DecisionComparison: (data) => fixedFields(
    data,
    data.view === "transition"
      ? [
          "view",
          "status",
          "current_stage",
          "recommended_action",
          "alternative_action",
          "decision_ref_id",
          "run_ref_id",
        ]
      : [
          "view",
          "metric",
          "baseline_score",
          "candidate_score",
          "decision_ref_id",
          "baseline_run_ref_id",
          "candidate_run_ref_id",
        ],
  ),
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
  ArtifactViewer: (data) => fixedFields(
    data,
    ["artifact_path", "media_type", "artifact_ref_id"],
  ),
  PaperPreview: (data) => fixedFields(
    data,
    ["paper_title", "paper_status", "publication_ready", "excerpt", "paper_ref_id"],
  ),
});

function renderSurface(renderer) {
  workspace.replaceChildren();
  proposalResult.replaceChildren();
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
}

async function submitAction(action) {
  if (!currentRenderer) {
    return;
  }
  const event = {
    schema_version: "1.0",
    event_id: `browser-event-${Date.now()}-${eventCounter++}`,
    event_type: "surface_action_requested",
    project_id: currentRenderer.project_id,
    surface_id: currentRenderer.surface_id,
    surface_revision: currentRenderer.surface_revision,
    surface_fingerprint: currentRenderer.surface_fingerprint,
    snapshot_revision: currentRenderer.snapshot.snapshot_revision,
    snapshot_sha256: currentRenderer.snapshot.snapshot_sha256,
    action_id: action.action_id,
  };
  try {
    const receipt = await api(
      `/api/v1/projects/${encodeURIComponent(currentRenderer.project_id)}/events`,
      {method: "POST", body: JSON.stringify(event)},
    );
    proposalResult.replaceChildren(
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

async function loadProjects() {
  try {
    const discovery = await api("/api/v1/projects");
    projectSelect.replaceChildren();
    for (const project of discovery.projects) {
      const option = document.createElement("option");
      option.value = project.project_id;
      appendText(option, project.project_id);
      projectSelect.appendChild(option);
    }
    const available = discovery.projects.length > 0;
    projectSelect.disabled = !available;
    loadButton.disabled = !available;
    connectionStatus.textContent = available
      ? "Authenticated. Select an authoritative project."
      : "Authenticated. No authoritative projects were found.";
    if (available) {
      await loadCurrentSurface();
    }
  } catch (error) {
    projectSelect.disabled = true;
    loadButton.disabled = true;
    showError(connectionStatus, error);
  }
}

async function loadCurrentSurface() {
  const projectId = projectSelect.value;
  if (!projectId) {
    return;
  }
  try {
    currentRenderer = await api(
      `/api/v1/projects/${encodeURIComponent(projectId)}/surface`,
    );
    renderSurface(currentRenderer);
    connectionStatus.textContent = "Current content-addressed surface loaded.";
  } catch (error) {
    currentRenderer = null;
    showError(workspace, error);
  }
}

async function api(path, options = {}) {
  const headers = {Authorization: `Bearer ${tokenInput.value}`};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {...options, headers});
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error?.message || "The trusted receiver rejected the request.");
  }
  return payload;
}

function showError(container, error) {
  container.replaceChildren();
  const message = document.createElement("p");
  message.className = "error-text";
  appendText(message, error instanceof Error ? error.message : "Request failed.");
  container.appendChild(message);
}

connectButton.addEventListener("click", loadProjects);
loadButton.addEventListener("click", loadCurrentSurface);
