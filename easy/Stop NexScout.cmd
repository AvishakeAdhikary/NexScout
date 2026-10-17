@echo off
rem Double-click to stop NexScout. Your data is kept.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-nexscout.ps1" -Stop
