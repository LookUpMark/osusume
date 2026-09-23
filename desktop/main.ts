import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import { join } from "node:path";
import { app, BrowserWindow, dialog, Menu, shell } from "electron";

// The server is the FastAPI sidecar: a PyInstaller onedir binary under
// Resources/desktop-server when packaged, backend/.venv/bin/python run_dev.py in
// dev (same app.main bootstrap — uvicorn.Server stays in app.main.SERVER so
// POST /api/shutdown can stop the LLM backend on quit).
let server: ChildProcess | null = null;
let serverPort: number | null = null;
let quitting = false;

if (!app.requestSingleInstanceLock()) {
  // second instance would race for the LLM backend and the port
  app.quit();
}

const root = app.isPackaged ? join(process.resourcesPath, "app") : app.getAppPath();

function serverCommand(): { cmd: string; args: string[] } {
  if (!app.isPackaged) {
    // not `uv run`: uv may be off the PATH of the launched app; the venv python
    // provisioned by `uv sync --project backend` is the stable entry
    const py =
      process.platform === "win32"
        ? join(root, "backend", ".venv", "Scripts", "python.exe")
        : join(root, "backend", ".venv", "bin", "python");
    return { cmd: py, args: [join(root, "backend", "run_dev.py")] };
  }
  return {
    // electron-builder copies the *contents* of build/pyserver/dist/osusume-server
    // into desktop-server/ (binary + _internal side by side)
    cmd: join(
      process.resourcesPath,
      "desktop-server",
      process.platform === "win32" ? "osusume-server.exe" : "osusume-server",
    ),
    args: [],
  };
}

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
  // the gate for the packaged app polls this line (the sidecar owns the log otherwise)
  console.log(`[osusume] sidecar on http://127.0.0.1:${port}`);
  const { cmd, args } = serverCommand();
  server = spawn(cmd, args, {
    cwd: root, // fixtures/ resolve cwd-relative (config.fixtures_available)
    env: {
      ...process.env,
      PORT: String(port),
      // the .app bundle is read-only (App Translocation): all runtime data goes
      // to ~/Library/Application Support/<productName>/
      ALR_DATA_DIR: app.getPath("userData"),
      // frontend build lives in resources/app/dist when packaged (dev: repo root,
      // resolved by app.main from __file__)
      ...(app.isPackaged ? { APP_VERSION: app.getVersion(), DIST_DIR: join(root, "dist") } : {}),
    },
    stdio: ["ignore", "inherit", "inherit"],
  });
  server.on("exit", (code) => {
    if (!quitting) fail("The local server stopped unexpectedly.", `Exit code ${code}.`);
  });
  // ENOENT/EACCES (binario mancante, quarantena Gatekeeper, venv assente): spawn emette
  // SOLO "error", mai "exit" — senza handler il main loop resta appeso su waitHealth
  // e l'app muore zombie senza finestra né dialogo
  server.on("error", (e) => {
    fail("The local server could not be launched.", String(e));
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

function stopServer(): void {
  // SIGTERM kills the sidecar without running its exit handlers (always on
  // Windows): ask the server to stop the LLM backend itself, best effort
  if (serverPort != null) {
    void fetch(`http://127.0.0.1:${serverPort}/api/shutdown`, { method: "POST" }).catch(() => undefined);
  }
  if (server && server.exitCode == null) {
    server.kill("SIGTERM");
    // never orphan the LLM backend if SIGTERM is swallowed (e.g. during startup)
    const child = server;
    const killTimer = setTimeout(() => child.kill("SIGKILL"), 2_000);
    child.once("exit", () => clearTimeout(killTimer));
  }
}

app.on("before-quit", () => {
  quitting = true;
  stopServer();
});

// SIGTERM/SIGINT (kill, Ctrl+C, logout) bypass before-quit on macOS/Linux and
// would orphan the sidecar: do the cleanup explicitly, then exit — app.quit()
// from a signal handler occasionally stalls in the native quit sequence
for (const signal of ["SIGTERM", "SIGINT"] as const) {
  process.on(signal, () => {
    quitting = true;
    stopServer();
    void new Promise<void>((resolve) => {
      // server already dead (e.g. the /api/shutdown POST beat us): no exit event
      // is coming — don't wait out the 2s grace
      if (server == null || server.exitCode != null) return resolve();
      const t = setTimeout(() => {
        server?.kill("SIGKILL");
        resolve();
      }, 2_000);
      server?.once("exit", () => {
        clearTimeout(t);
        resolve();
      });
    }).then(() => app.exit(0));
  });
}
