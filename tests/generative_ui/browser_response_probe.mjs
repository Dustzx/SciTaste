#!/usr/bin/env node

// Dependency-free Chromium probe for local, evidence-backed receiver acceptance.
// This is an engineering check, not a substitute for a study with human users.

import {spawn} from "node:child_process";
import {mkdtemp, mkdir, readFile, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {dirname, join} from "node:path";

const configuredBaseUrl = process.env.SCITASTE_UI_PROBE_URL || "http://127.0.0.1:8766";
const projectId = process.env.SCITASTE_UI_PROBE_PROJECT || "scitaste-self-development";
const quickIntentId = process.env.SCITASTE_UI_PROBE_QUICK_INTENT || "review-project-progress";
const followupQuickIntentId = process.env.SCITASTE_UI_PROBE_FOLLOWUP_INTENT || "";
const chromeCommand = process.env.SCITASTE_CHROME || "google-chrome";
const screenshotRoot = process.env.SCITASTE_UI_PROBE_SCREENSHOTS || "";
const finalLocale = process.env.SCITASTE_UI_PROBE_FINAL_LOCALE || "en";
const fullPageScreenshots = process.env.SCITASTE_UI_PROBE_FULL_PAGE === "1";
const reportPath = process.env.SCITASTE_UI_PROBE_REPORT || "";
const exploreGraph = process.env.SCITASTE_UI_PROBE_EXPLORE_GRAPH === "1";
const controlProposal = process.env.SCITASTE_UI_PROBE_CONTROL_PROPOSAL === "1";

if (!["en", "zh-CN"].includes(finalLocale)) {
  throw new Error("SCITASTE_UI_PROBE_FINAL_LOCALE must be en or zh-CN");
}
if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(projectId)) {
  throw new Error("SCITASTE_UI_PROBE_PROJECT is invalid");
}
if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(quickIntentId)) {
  throw new Error("SCITASTE_UI_PROBE_QUICK_INTENT is invalid");
}
if (followupQuickIntentId && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(followupQuickIntentId)) {
  throw new Error("SCITASTE_UI_PROBE_FOLLOWUP_INTENT is invalid");
}
const parsedBaseUrl = new URL(configuredBaseUrl);
if (
  parsedBaseUrl.protocol !== "http:"
  || !["127.0.0.1", "localhost", "[::1]"].includes(parsedBaseUrl.hostname)
  || parsedBaseUrl.username
  || parsedBaseUrl.password
  || parsedBaseUrl.search
  || parsedBaseUrl.hash
  || !["", "/"].includes(parsedBaseUrl.pathname)
) {
  throw new Error("SCITASTE_UI_PROBE_URL must be a credential-free loopback HTTP origin");
}
const baseUrl = parsedBaseUrl.origin;

async function main() {
  const profile = await mkdtemp(join(tmpdir(), "scitaste-ui-probe-"));
  const chrome = spawn(chromeCommand, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-allow-origins=*",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "about:blank",
  ], {stdio: ["ignore", "ignore", "pipe"]});

  let stderr = "";
  chrome.stderr.on("data", (chunk) => {
    stderr += String(chunk);
    if (stderr.length > 16_384) {
      stderr = stderr.slice(-16_384);
    }
  });

  try {
    const [port, browserPath] = await devtoolsAddress(profile, chrome);
    const socket = await openSocket(`ws://127.0.0.1:${port}${browserPath}`);
    const cdp = new CDPClient(socket);
    try {
      const created = await cdp.call("Target.createTarget", {url: "about:blank"});
      const attached = await cdp.call("Target.attachToTarget", {
        targetId: created.targetId,
        flatten: true,
      });
      const sessionId = attached.sessionId;
      await cdp.call("Page.enable", {}, sessionId);
      await cdp.call("Runtime.enable", {}, sessionId);
      await cdp.call("Network.enable", {}, sessionId);
      await cdp.call("Log.enable", {}, sessionId);

      const runtimeErrors = [];
      const httpFailures = [];
      let networkRequests = 0;
      cdp.onEvent((message) => {
        if (message.sessionId !== sessionId) {
          return;
        }
        if (message.method === "Network.requestWillBeSent") {
          networkRequests += 1;
        } else if (
          message.method === "Network.responseReceived"
          && message.params.response.status >= 400
          && !String(message.params.response.url || "").endsWith("/favicon.ico")
        ) {
          httpFailures.push({
            status: message.params.response.status,
            url: message.params.response.url,
          });
        } else if (message.method === "Runtime.exceptionThrown") {
          runtimeErrors.push(message.params.exceptionDetails.text || "runtime exception");
        } else if (
          message.method === "Log.entryAdded"
          && message.params.entry.level === "error"
          && !String(message.params.entry.url || "").endsWith("/favicon.ico")
        ) {
          runtimeErrors.push(message.params.entry.text);
        }
      });

      await setViewport(cdp, sessionId, 390, 844);
      const encodedProject = encodeURIComponent(projectId);
      const navigationStartedAt = performance.now();
      await cdp.call("Page.navigate", {
        url: `${baseUrl}/#/projects/${encodedProject}/project-progress?lang=zh-CN`,
      }, sessionId);
      await waitFor(cdp, sessionId, "document.readyState === 'complete'");
      await waitFor(cdp, sessionId, `
        document.getElementById("workspace").getAttribute("aria-busy") === "false"
        && document.querySelectorAll("#quick-intents button").length > 0
        && location.hash.includes("/${encodedProject}/project-progress")
      `, 30_000);
      const sessionToFixedMs = performance.now() - navigationStartedAt;
      const projectHomeShell = await evaluate(cdp, sessionId, `(() => {
        const workspace = document.getElementById("workspace");
        const composer = document.querySelector(".conversation-composer");
        return {
          mobile_drawer_default_closed:
            document.getElementById("drawer-toggle").getAttribute("aria-expanded") === "false",
          composer_follows_workspace: Boolean(
            workspace.compareDocumentPosition(composer) & Node.DOCUMENT_POSITION_FOLLOWING
          ),
          research_lens_count: document.querySelectorAll(".research-lens-button").length,
          operating_loop_present: Boolean(document.querySelector(".project-operating-loop")),
          operating_plane_count: document.querySelectorAll(".project-operating-plane").length,
          operating_bridge_present: Boolean(document.querySelector(".project-operating-bridge")),
          operating_controls_present:
            document.querySelectorAll(".project-operating-loop button").length >= 2,
        };
      })()`);
      await evaluate(cdp, sessionId, `document.getElementById("drawer-toggle").click()`);
      await waitFor(cdp, sessionId, `
        document.getElementById("drawer-toggle").getAttribute("aria-expanded") === "true"
        && getComputedStyle(document.getElementById("project-drawer")).position === "fixed"
        && getComputedStyle(document.getElementById("drawer-backdrop")).display !== "none"
      `);
      projectHomeShell.mobile_drawer_opens_as_overlay = await evaluate(cdp, sessionId, `
        document.getElementById("project-drawer").getBoundingClientRect().width < window.innerWidth
      `);
      await evaluate(cdp, sessionId, `document.getElementById("drawer-backdrop").click()`);
      await waitFor(cdp, sessionId, `
        document.getElementById("drawer-toggle").getAttribute("aria-expanded") === "false"
      `);
      await evaluate(cdp, sessionId, `document.querySelector(".evidence-tools > summary").click()`);
      await waitFor(cdp, sessionId, `document.querySelector(".evidence-tools").open`);
      projectHomeShell.mobile_evidence_tools_fit = await evaluate(cdp, sessionId, `(() => {
        const panel = document.querySelector(".evidence-tools-panel");
        const rect = panel.getBoundingClientRect();
        return rect.left >= 0
          && rect.right <= window.innerWidth
          && panel.querySelectorAll(".view-button").length === 8
          && Boolean(panel.querySelector(".selection-controls"));
      })()`);
      await evaluate(cdp, sessionId, `
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}))
      `);
      await waitFor(cdp, sessionId, `!document.querySelector(".evidence-tools").open`);

      await waitFor(cdp, sessionId, `document.querySelector(".gate-action-card")`, 30_000);
      const gateAction = await evaluate(cdp, sessionId, `(() => {
        const card = document.querySelector(".gate-action-card");
        const decisionControlCount = card.querySelectorAll(".gate-action-controls button").length;
        const awaitsDecision = card.classList.contains("state-ready_for_owner_decision");
        return {
          present: Boolean(card),
          flow_node_count: card.querySelectorAll(".gate-action-node").length,
          envelope_fact_count: card.querySelectorAll(".gate-action-envelope > span").length,
          decision_control_count: decisionControlCount,
          decision_controls_consistent:
            awaitsDecision ? decisionControlCount === 3 : decisionControlCount === 1,
          separate_execute_control_absent:
            ![...card.querySelectorAll("button")]
              .some((item) => /execute|运行|执行/i.test(item.textContent)),
        };
      })()`);
      const routeIntervention = await evaluate(cdp, sessionId, `(() => {
        const cards = [...document.querySelectorAll(".tool-route-card")];
        const button = cards[0]?.querySelector("button");
        if (!button) return {present: false};
        button.click();
        return {
          present: true,
          route_count: cards.length,
          economics_bar_count: cards[0].querySelectorAll(".verification-economy-row").length,
          advisory_state_present: Boolean(cards[0].querySelector(".verification-advisory-state")),
          focused_stage: cards[0].querySelector("strong")?.textContent || "",
          feedback_seeded: document.getElementById("intent-question").value.length > 0,
          submit_mode_changed: /revision|修订|调整/i.test(
            document.getElementById("generate-workspace").textContent,
          ),
        };
      })()`);
      projectHomeShell.route_intervention = routeIntervention;
      if (screenshotRoot) {
        await mkdir(screenshotRoot, {recursive: true});
        await setViewport(cdp, sessionId, 1440, 1000);
        await evaluate(cdp, sessionId, `window.scrollTo({top: 0, behavior: "instant"})`);
        await new Promise((resolve) => setTimeout(resolve, 100));
        const loopCapture = await cdp.call("Page.captureScreenshot", {
          format: "png",
          fromSurface: true,
          captureBeyondViewport: false,
        }, sessionId);
        await writeFile(
          join(screenshotRoot, "project-operating-loop-1440.png"),
          Buffer.from(loopCapture.data, "base64"),
        );
        await evaluate(cdp, sessionId, `
          document.querySelector(".gate-action-card").scrollIntoView({block: "center"})
        `);
        await new Promise((resolve) => setTimeout(resolve, 100));
        const capture = await cdp.call("Page.captureScreenshot", {
          format: "png",
          fromSurface: true,
          captureBeyondViewport: false,
        }, sessionId);
        await writeFile(
          join(screenshotRoot, "project-gate-action-1440.png"),
          Buffer.from(capture.data, "base64"),
        );
        await setViewport(cdp, sessionId, 390, 844);
      }

      await evaluate(cdp, sessionId, `
        (() => {
          const button = [...document.querySelectorAll("#quick-intents button")]
            .find((item) => item.dataset.quickIntentId === ${JSON.stringify(quickIntentId)});
          if (!button) throw new Error("requested quick intent unavailable");
          window.__scitasteGenerationStarted = performance.now();
          button.click();
        })()
      `);
      await waitFor(cdp, sessionId, `
        document.getElementById("workspace").getAttribute("aria-busy") === "false"
        && (
          (location.hash.includes("/workspaces/") && location.hash.includes("/turns/"))
          || location.hash.includes("/generated/")
        )
        && document.querySelectorAll("#workspace .component-card").length > 0
      `, 30_000);
      const quickIntentToGeneratedMs = await evaluate(cdp, sessionId, `
        performance.now() - window.__scitasteGenerationStarted
      `);
      const generatedResponseFocus = await evaluate(cdp, sessionId, `
        (() => {
          const workspace = document.getElementById("workspace");
          const rect = workspace.getBoundingClientRect();
          return {
            workspace_top: Math.round(rect.top),
            workspace_visible: rect.bottom > 0 && rect.top < window.innerHeight,
            workspace_has_focus: document.activeElement === workspace,
          };
        })()
      `);

      let evidenceGraphExploration = {tested: false};
      if (exploreGraph) {
        await waitFor(cdp, sessionId, `
          document.querySelectorAll(".evidence-graph-node").length > 1
          && document.querySelectorAll(".workspace-turn-button").length > 0
        `, 30_000);
        const graphStart = await evaluate(cdp, sessionId, `({
          workspace_id: location.hash.match(/\\/workspaces\\/([^/]+)\\/turns\\//)?.[1] || "",
          turn_id: location.hash.match(/\\/turns\\/([^?]+)/)?.[1] || "",
          turn_count: document.querySelectorAll(".workspace-turn-button").length,
          node_count: document.querySelectorAll(".evidence-graph-node").length,
        })`);
        await evaluate(cdp, sessionId, `
          document.querySelectorAll(".evidence-graph-node")[1].dispatchEvent(
            new MouseEvent("click", {bubbles: true}),
          )
        `);
        await waitFor(cdp, sessionId, `
          document.querySelector(".evidence-graph-node.selected")
          && document.querySelector(".evidence-graph-explore")
        `);
        await evaluate(cdp, sessionId, `
          document.querySelector(".evidence-graph-explore").click()
        `);
        await waitFor(cdp, sessionId, `
          document.getElementById("workspace").getAttribute("aria-busy") === "false"
          && location.hash.includes("/workspaces/${graphStart.workspace_id}/turns/")
          && (location.hash.match(/\\/turns\\/([^?]+)/)?.[1] || "")
            !== ${JSON.stringify(graphStart.turn_id)}
          && document.querySelectorAll(".workspace-turn-button").length
            === ${graphStart.turn_count + 1}
        `, 30_000);
        evidenceGraphExploration = await evaluate(cdp, sessionId, `({
          tested: true,
          node_count: ${graphStart.node_count},
          workspace_id_preserved:
            (location.hash.match(/\\/workspaces\\/([^/]+)\\/turns\\//)?.[1] || "")
              === ${JSON.stringify(graphStart.workspace_id)},
          turn_count_increment:
            document.querySelectorAll(".workspace-turn-button").length
              - ${graphStart.turn_count},
          generated_followup_present:
            document.querySelectorAll(".evidence-graph-node").length > 1,
        })`);
      }

      let topicNavigation = {tested: false};
      if (followupQuickIntentId) {
        await waitFor(cdp, sessionId, `
          document.querySelectorAll(".workspace-turn-button").length > 0
        `);
        const firstTopicState = await evaluate(cdp, sessionId, `({
          workspace_id: location.hash.match(/\\/workspaces\\/([^/]+)\\/turns\\//)?.[1] || "",
          turn_id: location.hash.match(/\\/turns\\/([^?]+)/)?.[1] || "",
          turn_count: document.querySelectorAll(".workspace-turn-button").length,
        })`);
        await evaluate(cdp, sessionId, `
          (() => {
            const button = [...document.querySelectorAll("#quick-intents button")]
              .find((item) => item.dataset.quickIntentId === ${JSON.stringify(followupQuickIntentId)});
            if (!button) throw new Error("requested follow-up intent unavailable");
            button.click();
          })()
        `);
        await waitFor(cdp, sessionId, `
          (location.hash.match(/\\/turns\\/([^?]+)/)?.[1] || "")
            !== ${JSON.stringify(firstTopicState.turn_id)}
          && document.querySelectorAll(".workspace-turn-button").length
            === ${firstTopicState.turn_count + 1}
        `, 30_000);
        topicNavigation = await evaluate(cdp, sessionId, `
          (() => {
            const workspaceId = location.hash.match(/\\/workspaces\\/([^/]+)\\/turns\\//)?.[1] || "";
            return {
              tested: true,
              workspace_id_preserved: workspaceId === ${JSON.stringify(firstTopicState.workspace_id)},
              active_turn_id: location.hash.match(/\\/turns\\/([^?]+)/)?.[1] || "",
              turn_page_count: document.querySelectorAll(".workspace-turn-button").length,
              turn_count_increment:
                document.querySelectorAll(".workspace-turn-button").length
                  - ${firstTopicState.turn_count},
            };
          })()
        `);
      }

      await new Promise((resolve) => setTimeout(resolve, 200));
      const beforeLocaleSwitch = networkRequests;
      await evaluate(cdp, sessionId, `
        (() => {
          const select = document.getElementById("locale-select");
          select.value = ${JSON.stringify(finalLocale)};
          select.dispatchEvent(new Event("change", {bubbles: true}));
        })()
      `);
      await waitFor(cdp, sessionId, `document.documentElement.lang === ${JSON.stringify(finalLocale)}`);
      await new Promise((resolve) => setTimeout(resolve, 300));
      const localeSwitchRequests = networkRequests - beforeLocaleSwitch;

      await setViewport(cdp, sessionId, 1440, 1000);
      await evaluate(cdp, sessionId, `
        (() => {
          const toggle = document.getElementById("drawer-toggle");
          if (toggle.getAttribute("aria-expanded") === "true") {
            document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
          }
          document.getElementById("drawer-edge").dispatchEvent(
            new PointerEvent("pointerenter", {pointerType: "mouse"}),
          );
        })()
      `);
      await waitFor(cdp, sessionId, `
        document.body.classList.contains("drawer-preview")
        && document.getElementById("drawer-toggle").getAttribute("aria-expanded") === "true"
        && document.getElementById("project-drawer").getBoundingClientRect().left >= 0
      `);
      const desktopDrawer = await evaluate(cdp, sessionId, `(() => {
        const drawer = document.getElementById("project-drawer");
        return {
          hover_preview_opens: document.body.classList.contains("drawer-preview"),
          fully_visible:
            drawer.getBoundingClientRect().left >= 0
            && drawer.getBoundingClientRect().right <= window.innerWidth,
          overlays_without_backdrop:
            getComputedStyle(drawer).position === "fixed"
            && getComputedStyle(document.getElementById("drawer-backdrop")).display === "none",
          history_present: Boolean(drawer.querySelector("#workspace-history-list")),
          internal_intent_slug_hidden: !drawer.textContent.includes("review-project-progress"),
          fixed_views_absent: !drawer.querySelector(".view-navigation"),
          evidence_selection_absent: !drawer.querySelector(".selection-controls"),
        };
      })()`);
      if (screenshotRoot) {
        await mkdir(screenshotRoot, {recursive: true});
        const capture = await cdp.call("Page.captureScreenshot", {
          format: "png",
          fromSurface: true,
          captureBeyondViewport: false,
        }, sessionId);
        await writeFile(
          join(screenshotRoot, "conversation-drawer-hover-1440.png"),
          Buffer.from(capture.data, "base64"),
        );
      }
      await evaluate(cdp, sessionId, `
        (() => {
          const edge = document.getElementById("drawer-edge");
          const drawer = document.getElementById("project-drawer");
          edge.dispatchEvent(new PointerEvent("pointerleave", {pointerType: "mouse"}));
          drawer.dispatchEvent(new PointerEvent("pointerenter", {pointerType: "mouse"}));
        })()
      `);
      await new Promise((resolve) => setTimeout(resolve, 250));
      desktopDrawer.pointer_transfer_preserves_preview = await evaluate(cdp, sessionId, `
        document.body.classList.contains("drawer-preview")
      `);
      await evaluate(cdp, sessionId, `
        document.getElementById("project-drawer").dispatchEvent(
          new PointerEvent("pointerleave", {pointerType: "mouse"}),
        )
      `);
      await waitFor(cdp, sessionId, `
        document.getElementById("drawer-toggle").getAttribute("aria-expanded") === "false"
      `);
      await evaluate(cdp, sessionId, `document.getElementById("drawer-toggle").click()`);
      await waitFor(cdp, sessionId, `document.body.classList.contains("drawer-pinned")`);
      desktopDrawer.click_pins = await evaluate(cdp, sessionId, `
        document.getElementById("drawer-toggle").getAttribute("aria-expanded") === "true"
      `);
      await evaluate(cdp, sessionId, `
        document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}))
      `);
      await waitFor(cdp, sessionId, `
        document.getElementById("drawer-toggle").getAttribute("aria-expanded") === "false"
      `);
      desktopDrawer.escape_closes = true;

      const viewports = [];
      for (const [width, height] of [
        [1440, 1000],
        [768, 900],
        [390, 844],
        [320, 800],
      ]) {
        await setViewport(cdp, sessionId, width, height);
        await evaluate(cdp, sessionId, `
          (() => {
            const toggle = document.getElementById("drawer-toggle");
            if (toggle.getAttribute("aria-expanded") === "true") {
              document.dispatchEvent(
                new KeyboardEvent("keydown", {key: "Escape", bubbles: true}),
              );
            }
            const workspace = document.getElementById("workspace");
            workspace.focus({preventScroll: true});
            workspace.scrollIntoView({block: "start"});
          })()
        `);
        await new Promise((resolve) => setTimeout(resolve, 100));
        const layout = await evaluate(cdp, sessionId, `
          (() => {
            const width = window.innerWidth;
            const overflow = [...document.body.querySelectorAll("*")]
              .filter((element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return !element.closest("[inert]")
                  && style.position !== "fixed"
                  && rect.width > 0
                  && (rect.left < -1 || rect.right > width + 1);
              })
              .slice(0, 12)
              .map((element) => element.id
                ? "#" + element.id
                : element.className
                  ? element.tagName.toLowerCase() + "." + String(element.className).split(" ")[0]
                  : element.tagName.toLowerCase());
            const smallTargets = [...document.querySelectorAll(
              "button:not([disabled]), select:not([disabled]), textarea:not([disabled]), input:not([disabled]), a[href]",
            )]
              .filter((element) => !element.classList.contains("skip-link"))
              .filter((element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== "none"
                  && style.visibility !== "hidden"
                  && rect.width > 0
                  && rect.height > 0
                  && (rect.width < 24 || rect.height < 24);
              })
              .map((element) => ({
                id: element.id || element.textContent.trim().slice(0, 40),
                width: Math.round(element.getBoundingClientRect().width * 10) / 10,
                height: Math.round(element.getBoundingClientRect().height * 10) / 10,
              }));
            return {
              viewport_width: width,
              document_scroll_width: document.documentElement.scrollWidth,
              document_scroll_height: document.documentElement.scrollHeight,
              horizontal_overflow: document.documentElement.scrollWidth > width + 1,
              overflowing_elements: overflow,
              small_targets: smallTargets,
              component_count: document.querySelectorAll("#workspace .component-card").length,
              workspace_top: Math.round(document.getElementById("workspace")
                .getBoundingClientRect().top),
              workspace_visible: (() => {
                const rect = document.getElementById("workspace").getBoundingClientRect();
                return rect.bottom > 0 && rect.top < window.innerHeight;
              })(),
              workspace_has_focus: document.activeElement === document.getElementById("workspace"),
              composer_below_workspace: (() => {
                const workspaceRect = document.getElementById("workspace").getBoundingClientRect();
                const composerRect = document.querySelector(".conversation-composer")
                  .getBoundingClientRect();
                return composerRect.top >= workspaceRect.bottom - 1;
              })(),
              composer_visible: (() => {
                const rect = document.querySelector(".conversation-composer").getBoundingClientRect();
                return rect.bottom > 0 && rect.top < window.innerHeight;
              })(),
              composer_height: Math.round(document.querySelector(".conversation-composer")
                .getBoundingClientRect().height),
              composer_is_bounded: document.querySelector(".conversation-composer")
                .getBoundingClientRect().height <= Math.min(260, window.innerHeight * 0.34),
            };
          })()
        `);
        viewports.push(layout);
        if (screenshotRoot && (width === 1440 || width === 390)) {
          await mkdir(screenshotRoot, {recursive: true});
          const screenshotOptions = {
            format: "png",
            fromSurface: true,
            captureBeyondViewport: fullPageScreenshots,
          };
          if (fullPageScreenshots) {
            const metrics = await cdp.call("Page.getLayoutMetrics", {}, sessionId);
            screenshotOptions.clip = {
              x: 0,
              y: 0,
              width: metrics.cssContentSize.width,
              height: metrics.cssContentSize.height,
              scale: 1,
            };
          }
          const capture = await cdp.call("Page.captureScreenshot", screenshotOptions, sessionId);
          await writeFile(
            join(screenshotRoot, `generated-${quickIntentId}-${width}.png`),
            Buffer.from(capture.data, "base64"),
          );
        }
      }

      let intervention = {tested: false};
      if (controlProposal) {
        await setViewport(cdp, sessionId, 1440, 1000);
        await waitFor(cdp, sessionId, `
          document.getElementById("workspace").getAttribute("aria-busy") === "false"
          && document.querySelector(".proposal-action-button")
        `, 30_000);
        await evaluate(cdp, sessionId, `
          document.querySelector(".proposal-action-button").click()
        `);
        await waitFor(cdp, sessionId, `
          document.querySelector("#proposal-result[data-state='proposal_pending']")
          && document.querySelectorAll("#proposal-result .component-actions button").length === 2
          && !document.querySelector("aside.inspector")
        `, 30_000);
        await evaluate(cdp, sessionId, `
          document.querySelectorAll("#proposal-result .component-actions button")[1].click()
        `);
        await waitFor(cdp, sessionId, `
          document.querySelector("#proposal-result[data-state='rejected']")
        `, 30_000);
        intervention = await evaluate(cdp, sessionId, `({
          tested: true,
          right_sidebar_absent: !document.querySelector("aside.inspector"),
          inline_workbench_present: Boolean(document.getElementById("interaction-workbench")),
          recorded_state: document.getElementById("proposal-result")?.dataset.state || "",
        })`);
      }

      const result = {
        measurement_kind: "automated-browser-engineering-probe",
        interpretation_boundary: "not-human-usability-or-scientific-effectiveness",
        project_id: projectId,
        quick_intent_id: quickIntentId,
        project_home_shell: projectHomeShell,
        project_gate_action: gateAction,
        locale_switch_network_requests: localeSwitchRequests,
        session_to_fixed_workspace_ms: Math.round(sessionToFixedMs * 1000) / 1000,
        quick_intent_to_generated_workspace_ms:
          Math.round(quickIntentToGeneratedMs * 1000) / 1000,
        generated_response_focus: generatedResponseFocus,
        desktop_conversation_drawer: desktopDrawer,
        evidence_graph_exploration: evidenceGraphExploration,
        intervention,
        topic_navigation: topicNavigation,
        runtime_errors: runtimeErrors,
        http_failures: httpFailures,
        viewports,
      };
      const serializedResult = `${JSON.stringify(result, null, 2)}\n`;
      if (reportPath) {
        await mkdir(dirname(reportPath), {recursive: true});
        await writeFile(reportPath, serializedResult, "utf8");
      }
      console.log(serializedResult.trimEnd());
      if (
        runtimeErrors.length > 0
        || localeSwitchRequests !== 0
        || !projectHomeShell.mobile_drawer_default_closed
        || !projectHomeShell.mobile_drawer_opens_as_overlay
        || !projectHomeShell.mobile_evidence_tools_fit
        || !projectHomeShell.composer_follows_workspace
        || projectHomeShell.research_lens_count !== 4
        || !projectHomeShell.operating_loop_present
        || projectHomeShell.operating_plane_count !== 2
        || !projectHomeShell.operating_bridge_present
        || !projectHomeShell.operating_controls_present
        || !gateAction.present
        || gateAction.flow_node_count !== 3
        || gateAction.envelope_fact_count !== 6
        || !gateAction.decision_controls_consistent
        || !gateAction.separate_execute_control_absent
        || !projectHomeShell.route_intervention?.present
        || projectHomeShell.route_intervention.route_count < 1
        || projectHomeShell.route_intervention.economics_bar_count !== 2
        || !projectHomeShell.route_intervention.advisory_state_present
        || !projectHomeShell.route_intervention.feedback_seeded
        || !projectHomeShell.route_intervention.submit_mode_changed
        || !generatedResponseFocus.workspace_visible
        || !generatedResponseFocus.workspace_has_focus
        || !desktopDrawer.hover_preview_opens
        || !desktopDrawer.fully_visible
        || !desktopDrawer.overlays_without_backdrop
        || !desktopDrawer.history_present
        || !desktopDrawer.internal_intent_slug_hidden
        || !desktopDrawer.fixed_views_absent
        || !desktopDrawer.evidence_selection_absent
        || !desktopDrawer.pointer_transfer_preserves_preview
        || !desktopDrawer.click_pins
        || !desktopDrawer.escape_closes
        || (evidenceGraphExploration.tested && (
          !evidenceGraphExploration.workspace_id_preserved
          || evidenceGraphExploration.turn_count_increment !== 1
          || !evidenceGraphExploration.generated_followup_present
        ))
        || (intervention.tested && (
          !intervention.right_sidebar_absent
          || !intervention.inline_workbench_present
          || intervention.recorded_state !== "rejected"
        ))
        || (topicNavigation.tested && (
          !topicNavigation.workspace_id_preserved || topicNavigation.turn_count_increment !== 1
        ))
        || viewports.some((item) =>
          item.horizontal_overflow
          || item.small_targets.length > 0
          || !item.workspace_visible
          || !item.workspace_has_focus
          || !item.composer_below_workspace
          || !item.composer_visible
          || !item.composer_is_bounded)
      ) {
        process.exitCode = 1;
      }
    } finally {
      cdp.close();
    }
  } catch (error) {
    const detail = stderr ? `\nChromium stderr:\n${stderr}` : "";
    throw new Error(`${error instanceof Error ? error.message : String(error)}${detail}`);
  } finally {
    await stopChrome(chrome);
    await rm(profile, {recursive: true, force: true});
  }
}

class CDPClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = [];
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id !== undefined) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message));
        else pending.resolve(message.result || {});
        return;
      }
      for (const listener of this.listeners) listener(message);
    });
  }

  call(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    const message = {id, method, params};
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.socket.send(JSON.stringify(message));
    });
  }

  onEvent(listener) {
    this.listeners.push(listener);
  }

  close() {
    this.socket.close();
  }
}

async function devtoolsAddress(profilePath, process) {
  const activePort = join(profilePath, "DevToolsActivePort");
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (process.exitCode !== null) {
      throw new Error(`Chromium exited before DevTools became ready (${process.exitCode})`);
    }
    try {
      const [port, browserPath] = (await readFile(activePort, "utf8")).trim().split("\n");
      if (port && browserPath) return [Number(port), browserPath];
    } catch {
      // Chromium creates the file atomically after binding the debugging socket.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("timed out waiting for Chromium DevTools");
}

function openSocket(url) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    socket.addEventListener("open", () => resolve(socket), {once: true});
    socket.addEventListener("error", () => reject(new Error("DevTools WebSocket failed")), {
      once: true,
    });
  });
}

async function evaluate(cdp, sessionId, expression) {
  const response = await cdp.call("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.text || "browser evaluation failed");
  }
  return response.result.value;
}

async function waitFor(cdp, sessionId, expression, timeoutMs = 15_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      if (await evaluate(cdp, sessionId, `Boolean(${expression})`)) return;
    } catch {
      // Navigation can briefly invalidate the execution context.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`timed out waiting for browser condition: ${expression}`);
}

function setViewport(cdp, sessionId, width, height) {
  return cdp.call("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width <= 390,
  }, sessionId);
}

async function stopChrome(process) {
  if (process.exitCode !== null) return;
  const closed = new Promise((resolve) => process.once("close", resolve));
  process.kill("SIGTERM");
  await Promise.race([
    closed,
    new Promise((resolve) => setTimeout(resolve, 2000)),
  ]);
  if (process.exitCode === null) {
    process.kill("SIGKILL");
    await closed;
  }
}

await main();
