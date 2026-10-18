@echo off
rem Double-click to update NexScout to the newest release, then start it. Your data is kept.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-nexscout.ps1" -Update %*
