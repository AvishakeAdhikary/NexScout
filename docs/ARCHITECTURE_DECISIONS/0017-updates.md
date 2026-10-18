# ADR-0017: Updates (desktop self-update, Easy bundle update, update notice) and cleanup

- **Status:** accepted (M16, 2026-10-19)
- **Context:** Every green `main` push publishes a release (ADR via M13). Until v2.2.0, nobody
  learned about a new version, and updating meant downloading and reinstalling by hand. Old
  installers and Docker images piled up. NexScout runs in three ways:
  - the Windows app, which can run its own Docker stack (Easy mode);
  - the Easy zip with double-click scripts;
  - a server that someone runs.

## Decision
1. **Desktop: electron-updater against this repository's GitHub releases.**
   - `electron-builder.yml` declares `publish: github`. The release job builds with
     `--publish never` and uploads `NexScout-Setup-<v>.exe`, its `.blockmap` and `latest.yml`.
     It first checks that `latest.yml` names exactly that file. The artifact name has no
     spaces, because GitHub would rename it.
   - `src/updates.ts` checks 10 s after start, every 6 hours, and from **Check for updates…**.
   - It downloads in the background, then asks "Restart now / Later". With Later, the update
     installs when the app quits. Downgrades and prereleases are off.
   - After a version change, the updater cache (`%LOCALAPPDATA%\nexscout-desktop-updater\pending`)
     is deleted. Only the installed app updates itself: not development runs, not `--smoke`.
2. **Easy mode inside the desktop app.**
   - The stack's images are pinned to the app version. After an app update, the next start
     pulls the new images and runs `up -d`.
   - It then removes the previous NexScout images (`ghcr.io/*/nexscout-(backend|web)` with any
     other version tag) and dangling layers. No other image is touched (`staleImages`, tested).
3. **Easy zip: "Update NexScout".**
   - The script (`start-nexscout.ps1 -Update`, `start-nexscout.sh update`) reads the latest
     release tag from the GitHub API.
   - It downloads that release's `nexscout-easy-<v>.zip` and **verifies it against the
     release's `SHA256SUMS.txt`**. A missing or mismatched checksum stops the update.
   - It then replaces the bundle's files: never `.env`, never volumes. The Unix script moves
     files into place, so the running script keeps reading its old copy.
   - It re-runs the new start script, and that run removes the old images.
   - It refuses to run in a developer checkout (which has a `backend/` folder).
4. **Update notice for everyone else.**
   - `GET /api/v1/version` (signed-in users only) compares `NEXSCOUT_VERSION` with the latest
     GitHub release, cached for 6 hours and retried after 15 minutes when a check fails.
   - The release answer is untrusted: only a version-shaped tag is accepted, and only a URL
     inside this repository is passed on.
   - The web app shows a banner with the steps. The banner is hidden in the desktop app, which
     updates itself, and can be dismissed per version.
   - `NEXSCOUT_UPDATE_CHECK=0` turns the check off. Tests and E2E always do.
5. **What isn't done.** No silent restarts, and no automatic image updates on servers: an
   operator upgrades deliberately (OPERATIONS.md "Deploy / upgrade"). Because the builds are
   unsigned, electron-updater can't verify a publisher signature. It does verify the sha512
   in `latest.yml`, and both files come from the same release over https.

## Consequences
- Users of 2.3.0 and later get updates without reinstalling. Users of 2.2.0 or older install
  once by hand, because those versions had no updater.
- Disk use stays flat: one NexScout version's images and no stale installers.
- An attacker who controls a release can still ship an update. Code signing (KNOWN_LIMITATIONS)
  and release protection on `main` are the mitigations still to do.
