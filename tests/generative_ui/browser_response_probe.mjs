#!/usr/bin/env node

// Dependency-free Chromium probe for local, evidence-backed receiver acceptance.
// This is an engineering check, not a substitute for a study with human users.

import {spawn} from "node:child_process";
import {mkdtemp, mkdir, readFile, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";

const configuredBaseUrl = process.env.SCITASTE_UI_PROBE_URL || "http://127.0.0.1:8766";
const token = process.env.SCITASTE_UI_PROBE_TOKEN;
const projectId = process.env.SCITASTE_UI_PROBE_PROJECT || "scitaste-self-development";
const chromeCommand = process.env.SCITASTE_CHROME || "google-chrome";
const screenshotRoot = process.env.SCITASTE_UI_PROBE_SCREENSHOTS || "";

if (!token) {
  throw new Error("SCITASTE_UI_PROBE_TOKEN is required");
}
if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(projectId)) {
  throw new Error("SCITASTE_UI_PROBE_PROJECT is invalid");
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
      let networkRequests = 0;
      cdp.onEvent((message) => {
        if (message.sessionId !== sessionId) {
          return;
        }
        if (message.method === "Network.requestWillBeSent") {
          networkRequests += 1;
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
      await cdp.call("Page.navigate", {
        url: `${baseUrl}/#/projects/${encodedProject}/project-progress?lang=zh-CN`,
      }, sessionId);
      await waitFor(cdp, sessionId, "document.readyState === 'complete'");
      await waitFor(cdp, sessionId, "!document.getElementById('connect').disabled");

      await evaluate(cdp, sessionId, `
        (() => {
          document.getElementById("bearer-token").value = ${JSON.stringify(token)};
          window.__scitasteConnectStarted = performance.now();
          document.getElementById("connect").click();
        })()
      `);
      await waitFor(cdp, sessionId, `
        document.getElementById("workspace").getAttribute("aria-busy") === "false"
        && document.querySelectorAll("#quick-intents button").length > 0
        && location.hash.includes("/${encodedProject}/project-progress")
      `, 30_000);
      const connectToFixedMs = await evaluate(cdp, sessionId, `
        performance.now() - window.__scitasteConnectStarted
      `);

      await evaluate(cdp, sessionId, `
        (() => {
          const button = [...document.querySelectorAll("#quick-intents button")]
            .find((item) => item.dataset.quickIntentId === "review-project-progress");
          if (!button) throw new Error("progress quick intent unavailable");
          window.__scitasteGenerationStarted = performance.now();
          button.click();
        })()
      `);
      await waitFor(cdp, sessionId, `
        document.getElementById("workspace").getAttribute("aria-busy") === "false"
        && location.hash.includes("/generated/")
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

      await new Promise((resolve) => setTimeout(resolve, 200));
      const beforeLocaleSwitch = networkRequests;
      await evaluate(cdp, sessionId, `
        (() => {
          const select = document.getElementById("locale-select");
          select.value = "en";
          select.dispatchEvent(new Event("change", {bubbles: true}));
        })()
      `);
      await waitFor(cdp, sessionId, "document.documentElement.lang === 'en'");
      await new Promise((resolve) => setTimeout(resolve, 300));
      const localeSwitchRequests = networkRequests - beforeLocaleSwitch;

      const viewports = [];
      for (const [width, height] of [
        [1440, 1000],
        [768, 900],
        [390, 844],
        [320, 800],
      ]) {
        await setViewport(cdp, sessionId, width, height);
        await evaluate(cdp, sessionId, `
          document.getElementById("workspace").scrollIntoView({block: "start"})
        `);
        await new Promise((resolve) => setTimeout(resolve, 100));
        const layout = await evaluate(cdp, sessionId, `
          (() => {
            const width = window.innerWidth;
            const overflow = [...document.body.querySelectorAll("*")]
              .filter((element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.position !== "fixed"
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
            };
          })()
        `);
        viewports.push(layout);
        if (screenshotRoot && (width === 1440 || width === 390)) {
          await mkdir(screenshotRoot, {recursive: true});
          const capture = await cdp.call("Page.captureScreenshot", {
            format: "png",
            fromSurface: true,
            captureBeyondViewport: false,
          }, sessionId);
          await writeFile(
            join(screenshotRoot, `generated-progress-${width}.png`),
            Buffer.from(capture.data, "base64"),
          );
        }
      }

      const result = {
        measurement_kind: "automated-browser-engineering-probe",
        interpretation_boundary: "not-human-usability-or-scientific-effectiveness",
        project_id: projectId,
        locale_switch_network_requests: localeSwitchRequests,
        connect_to_fixed_workspace_ms: Math.round(connectToFixedMs * 1000) / 1000,
        quick_intent_to_generated_workspace_ms:
          Math.round(quickIntentToGeneratedMs * 1000) / 1000,
        generated_response_focus: generatedResponseFocus,
        runtime_errors: runtimeErrors,
        viewports,
      };
      console.log(JSON.stringify(result, null, 2));
      if (
        runtimeErrors.length > 0
        || localeSwitchRequests !== 0
        || !generatedResponseFocus.workspace_visible
        || !generatedResponseFocus.workspace_has_focus
        || Math.abs(generatedResponseFocus.workspace_top) > 1
        || viewports.some((item) =>
          item.horizontal_overflow
          || item.small_targets.length > 0
          || !item.workspace_visible
          || !item.workspace_has_focus)
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
