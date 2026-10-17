@echo off
rem Double-click to start NexScout (needs Docker Desktop). Opens http://localhost:3000.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-nexscout.ps1" %*
