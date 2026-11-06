@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
.venv\Scripts\python -m deal_video_agent.agent.subtitle_agent %*
