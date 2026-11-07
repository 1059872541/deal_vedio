@echo off
rem vedio launcher.
rem Why this file: the package lives under src/ (like util/, jianying_export/),
rem so the repo root has no vedio/ directory. This shim puts src on sys.path.
rem Can be deleted once the project is installed with: pip install -e .
rem
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat with the console
rem codepage (GBK on zh-CN), so UTF-8 Chinese comments break the parser.
chcp 65001 >nul
"%~dp0.venv\Scripts\python.exe" "%~dp0vedio.py" %*
