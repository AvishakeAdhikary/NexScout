NexScout - easy start
=====================

1. Install Docker Desktop (free for personal use): https://www.docker.com/products/docker-desktop/
   Start it once and wait until it says it is running.
2. Start NexScout:
   - Windows: double-click "Start NexScout.cmd"
   - macOS:   double-click "Start NexScout.command" (the first time: right-click > Open)
   - Linux:   run ./start-nexscout.sh
3. Your browser opens http://localhost:3000. Create your account and follow "Getting started".

To stop NexScout: "Stop NexScout.cmd" (Windows) or ./start-nexscout.sh stop (macOS/Linux).
Your data is kept between runs.

To update to the newest version: "Update NexScout.cmd" (Windows), "Update NexScout.command"
(macOS) or ./start-nexscout.sh update (Linux). It checks the download, keeps your data and
your .env, starts the new version and removes the old one. NexScout shows a notice when an
update is available.

The file .env in this folder holds your secret keys. Keep it and back it up: without it
NexScout can't read the passwords and tokens you saved. Never share it.

Full guide: docs/USER_GUIDE.md (or https://github.com/AvishakeAdhikary/NexScout)
