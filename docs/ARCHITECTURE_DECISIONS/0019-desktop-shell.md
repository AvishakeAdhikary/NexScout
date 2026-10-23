# ADR-0019: Desktop shell, a frameless window, the tray, and a narrow page bridge

- **Status:** accepted (M19, 2026-10-23)
- **Context:** On v2.8.0 the desktop app showed two bars, the native title bar with an app menu
  ("Check for updates…" was its only useful item) and the page's own top bar. Closing the window
  quit the app, with no tray to bring it back, so background work looked lost. A second launch
  started a second copy. Updates could only be checked from the menu, through dialogs.
  Navigation inside the app relied on the logo.

## Decision
1. **One bar.**
   - No application menu (`Menu.setApplicationMenu(null)`).
   - Windows and Linux: `titleBarStyle: "hidden"` with a `titleBarOverlay` 56 px high (the
     page's top bar height), in the theme's colours (`policy.titleBarColors`). The page tells the
     app its theme through the bridge.
   - macOS: `hiddenInset` (traffic lights inset).
   - The page's top bar becomes the drag region (`.desktop-titlebar`, only inside the app).
     Its controls are `no-drag`. It leaves room for the window controls using the Window
     Controls Overlay variables (`env(titlebar-area-*)`).
   - Pages without the top bar (sign in) get a drag strip.
   - Since there is no menu, reload (Ctrl+R) and developer tools (F12, unpackaged only) are
     handled in `before-input-event`.
2. **The tray.**
   - Always present: Open, Check for updates, "Keep running in the tray when I close the
     window" (a checkbox), Stop background work and quit (Easy mode), Quit.
   - The close button hides the window while that setting is on (the default). The first time,
     a notification says where NexScout went.
   - The setting lives in `desktop-prefs.json` (`policy.parsePrefs`), apart from the connection
     config.
3. **One instance.** `requestSingleInstanceLock()`. A second launch shows the existing window.
   `--smoke` runs skip the lock, so they never disturb an installed copy.
4. **A narrow bridge.**
   - `preload.ts` exposes exactly these calls: `info`, `checkForUpdates`, `installUpdate`,
     `setCloseToTray`, `stopBackground`, `openLogs`, `setTheme`, `onUpdateStatus`.
   - Each call maps to one `ipcMain.handle` channel. Arguments are coerced in the preload and
     checked again in main.
   - Every handler first checks `policy.isTrustedSender`: the sending frame's origin must be the
     NexScout page's origin. Not the setup page, not an embedded frame.
   - There is still no Node in the page, no generic IPC, and no `<webview>`.
5. **Updates from the page.**
   - Account → About & updates calls `checkForUpdates`. `updates.ts` then reports status
     (checking / downloading n% / ready / none / error) through `onUpdateStatus` instead of
     dialogs, and "Restart to update" calls `installUpdate`.
   - Background checks and the tray's check keep their dialogs.
6. **Navigation (web).**
   - A visible Home link in the top bar.
   - "All cases" and a case switcher that keeps the section, in the case side panel.
   - Breadcrumbs (Cases › case › section › item) on every case page.

## Consequences
- The window looks like one native app. Its controls never cover the page's buttons. This was
  verified with a whole-window capture in the smoke run (`NEXSCOUT_SMOKE_SCREENSHOT`).
- A page served from anywhere else can't use the bridge even if it is loaded into the window.
  Navigation guards already prevent that.
- Older desktop apps (bridge without `info`) are treated as "no bridge" by the web
  (`lib/desktop.desktopBridge`), so a newer web build never breaks an older shell.
- **Smoke-only hooks:** `NEXSCOUT_SMOKE_COOKIE` sets a test account's session, and
  `NEXSCOUT_SMOKE_SCREENSHOT` saves a capture. Both act only with `--smoke`.
