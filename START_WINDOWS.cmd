@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 serve.py --open-browser
    goto done
)
where python >nul 2>nul
if not errorlevel 1 (
    python serve.py --open-browser
    goto done
)
echo Python 3.10 or newer is required. Install Python and run this file again.
echo https://www.python.org/downloads/windows/
:done
pause
