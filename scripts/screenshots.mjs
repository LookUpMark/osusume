// README screenshots: drives the built UI (server on :3000) with the LookUpMark
// profile and captures the real views. The wizard shot uses a second server on
// :3001 with a scratch config so the real data/config.json is never touched.
//   cd backend && uv run run_dev.py &  (porta 3000, avviata a mano prima)
//   + electron scripts/screenshots.mjs   [il wizard server su :3001 lo spawna qui]
// Theme can be forced for the whole matrix via OSUSUME_THEME (light|dark):
// it is written to localStorage before the UI bootstraps (same key the app
// itself reads: osusume-theme). Un solo design dalla v1.6.0 (marcantonio-lopez).
import { app, BrowserWindow } from "electron";
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const OUT = new URL("../docs/screenshots/", import.meta.url).pathname;
const REPO = new URL("..", import.meta.url).pathname;
const THEME = process.env.OSUSUME_THEME; // "light" | "dark"
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const waitFor = async (win, js, timeout = 90_000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await win.webContents.executeJavaScript(js).catch(() => false)) return;
    await sleep(400);
  }
  throw new Error(`timeout: ${js}`);
};

// FastAPI sidecar: probe /api/health with a hard cap instead of hanging forever
const waitForHealth = async (port, timeout = 30_000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await fetch(`http://127.0.0.1:${port}/api/health`).then((r) => r.ok).catch(() => false)) return;
    await sleep(400);
  }
  throw new Error(`backend non risponde su :${port}`);
};

// persist forced theme BEFORE the app bootstraps (it reads it at mount)
const applyPreferences = async (win) => {
  const js = THEME ? `localStorage.setItem("osusume-theme", ${JSON.stringify(THEME)})` : "";
  if (js) await win.webContents.executeJavaScript(js);
};

const shot = async (win, name) => {
  const img = await win.webContents.capturePage();
  writeFileSync(join(OUT, `${name}.png`), img.toPNG());
  console.log(`captured ${name}.png`);
};

// fill a React controlled input and submit its form
const search = (sel, value) => `(() => {
  const i = document.querySelector("${sel}");
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  set.call(i, ${JSON.stringify(value)});
  i.dispatchEvent(new Event("input", { bubbles: true }));
  i.closest("form").requestSubmit();
})()`;

const click = (sel) => `document.querySelector(${JSON.stringify(sel)})?.click()`;

app.whenReady().then(async () => {
  mkdirSync(OUT, { recursive: true });
  // scratch server for the wizard shot (empty config → needsSetup): the uv-run
  // FastAPI dev server, same launcher as `pnpm dev` (PORT/CONFIG_PATH/ALR_DATA_DIR env)
  const scratchDir = mkdtempSync(join(tmpdir(), "osusume-wizard-"));
  const wizardSrv = spawn("uv", ["run", "run_dev.py"], {
    cwd: join(REPO, "backend"),
    env: { ...process.env, PORT: "3001", CONFIG_PATH: join(scratchDir, "config.json"), ALR_DATA_DIR: join(scratchDir, "data") },
    stdio: "ignore",
    detached: false,
  });

  const win = new BrowserWindow({ width: 1680, height: 1050, show: true });
  try {
    await waitForHealth(3000);
    await win.loadURL("http://127.0.0.1:3000");
    await win.webContents.executeJavaScript(`localStorage.clear()`);
    await applyPreferences(win);
    await win.reload();
    await sleep(2000);
    // fake login
    await shot(win, "login");
    await win.webContents.executeJavaScript(search(".login-form input", "LookUpMark"));
    // probe-style: single check after a settle sleep (polling misses it somehow)
    let cards = 0;
    for (let i = 0; i < 60; i++) {
      await sleep(3000);
      cards = await win.webContents.executeJavaScript(`document.querySelectorAll("button.mcard").length`);
      if (cards > 5) break;
    }
    if (cards <= 5) throw new Error(`mcards: ${cards}`);
    await sleep(1500);
    await shot(win, "home");

    // detail dialog: open the top card; the on-demand LLM why lands on the dot
    const firstCard = await win.webContents.executeJavaScript(
      `document.querySelector("button.mcard")?.dataset.odId ?? ""`,
    );
    await win.webContents.executeJavaScript(click(`button.mcard[data-od-id="${firstCard}"]`));
    await waitFor(win, `document.querySelector(".dlg")`, 20_000);
    await waitFor(win, `document.querySelector(".dlg .llm-dot.on")`, 150_000); // cold narration ≈ 1 min
    await sleep(400);
    await shot(win, "detail");
    await win.webContents.executeJavaScript(click(".dlg-close"));
    await sleep(300);

    // topbar anime search: dropdown over the recos grid
    await win.webContents.executeJavaScript(search(".search input", "Monster"));
    await waitFor(win, `document.querySelectorAll(".top-results .chat-card").length > 0`, 60_000);
    await sleep(400);
    await shot(win, "search");
    await win.webContents.executeJavaScript(click(".dlg-scrim, header"));
    await win.webContents.executeJavaScript(`document.querySelector(".search input").blur(); window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))`);
    await sleep(300);

    // chat: real question + reply with title cards
    await win.webContents.executeJavaScript(click('nav.nav button[title="Chat"]'));
    await waitFor(win, `document.querySelector(".chat-panel")`, 20_000);
    await win.webContents.executeJavaScript(search(".chat-input input", "What should I watch first, and why?"));
    await waitFor(win, `document.querySelectorAll(".chat-msg.assistant:not(.thinking)").length > 0`, 180_000);
    await sleep(2500); // title cards settle
    await shot(win, "chat");

    await win.webContents.executeJavaScript(click('nav.nav button[title="Profile"]'));
    await waitFor(win, `document.querySelector("#view-profile:not([hidden])")`, 20_000);
    await sleep(500);
    await shot(win, "profile");

    await win.webContents.executeJavaScript(click('nav.nav button[title="Settings"]'));
    await waitFor(win, `document.querySelector("#view-settings:not([hidden])")`, 20_000);
    await sleep(500);
    await shot(win, "settings");

    // wizard on the scratch instance
    const wwin = new BrowserWindow({ width: 1680, height: 1050, show: true });
    await waitForHealth(3001);
    await wwin.loadURL("http://127.0.0.1:3001");
    await wwin.webContents.executeJavaScript(`localStorage.clear()`);
    await applyPreferences(wwin);
    await wwin.reload();
    await waitFor(wwin, `document.querySelector(".wizard-page")`, 30_000);
    await sleep(1500); // hardware probe settles
    await shot(wwin, "setup-wizard");
    wwin.destroy();
  } finally {
    win.destroy();
    wizardSrv.kill();
    app.quit();
  }
});
