import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import { join } from "node:path";
import { app, BrowserWindow, dialog, Menu, shell } from "electron";

// The server runs as a plain-Node child of the Electron binary (ELECTRON_RUN_AS_NODE)
// on an esbuild bundle — no dependency on the type-stripping of Electron's embedded
// Node, and its own SIGTERM handler keeps stopping the LLM backend on quit.
let server: ChildProcess | null = null;
let serverPort: number | null = null;
let quitting = false;

if (!app.requestSingleInstanceLock()) {
  // second instance would race for the LLM backend and the port
  app.quit();
}

const root = app.isPackaged ? join(process.resourcesPath, "app") : app.getAppPath();

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.listen(0, "127.0.0.1", () => {
      const port = (s.address() as { port: number }).port;
      s.close(() => resolve(port));
    });
    s.on("error", reject);
  });
}

async function waitHealth(port: number, timeoutMs = 15_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (res.ok) return true;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

function fail(message: string, detail: string): void {
  dialog.showErrorBox("Osusume", `${message}\n\n${detail}`);
  app.quit();
}

async function start(): Promise<void> {
  const port = await freePort();
  serverPort = port;
  server = spawn(process.execPath, [join(root, "dist-electron", "server.mjs")], {
    cwd: root, // serveStatic root "./dist" is cwd-relative
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: "1",
      NODE_ENV: "production",
      PORT: String(port),
      // the .app bundle is read-only (App Translocation): all runtime data goes
      // to ~/Library/Application Support/<productName>/
      ALR_DATA_DIR: app.getPath("userData"),
      // version marker only when packaged: in dev-electron a version bump must
      // not reopen the wizard on every `pnpm app`
      ...(app.isPackaged ? { APP_VERSION: app.getVersion() } : {}),
    },
    stdio: ["ignore", "inherit", "inherit"],
  });
  server.on("exit", (code) => {
    if (!quitting) fail("The local server stopped unexpectedly.", `Exit code ${code}.`);
  });

  if (!(await waitHealth(port))) {
    fail("The local server did not start.", "Check the log output and reopen the app.");
    return;
  }

  Menu.setApplicationMenu(
    Menu.buildFromTemplate([{ role: "appMenu" }, { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" }]),
  );

  const win = new BrowserWindow({
    width: 1280,
    height: 832,
    minWidth: 960,
    minHeight: 640,
    show: false,
    backgroundColor: "#121212",
  });
  win.once("ready-to-show", () => win.show());
  // links (AniList pages, release downloads) open in the system browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith(`http://127.0.0.1:${port}`)) {
      e.preventDefault();
      void shell.openExternal(url);
    }
  });
  await win.loadURL(`http://127.0.0.1:${port}`); // not file:// — the API rejects foreign Host headers
}

app.on("second-instance", () => {
  const [win] = BrowserWindow.getAllWindows();
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

app.whenReady().then(start).catch((e) => fail("Startup failed.", String(e)));

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  quitting = true;
  // SIGTERM kills the Node child without running its exit handlers (always on
  // Windows): ask the server to stop the LLM backend itself, best effort
  if (serverPort != null) {
    void fetch(`http://127.0.0.1:${serverPort}/api/shutdown`, { method: "POST" }).catch(() => undefined);
  }
  server?.kill("SIGTERM");
});
