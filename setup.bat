@echo off
setlocal

echo ============================================================
echo  Job Tracker Setup
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python found
python --version

echo.
echo Installing dependencies...
pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)
echo [OK] Dependencies installed

echo.
echo Creating Windows Scheduled Task (runs every 2 hours)...

REM Delete existing task if present
schtasks /delete /tn "JobTracker" /f >nul 2>&1

REM Create scheduled task: every 2 hours, starting now
schtasks /create ^
  /tn "JobTracker" ^
  /tr "python \"%~dp0tracker.py\"" ^
  /sc HOURLY ^
  /mo 2 ^
  /st 00:00 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if errorlevel 1 (
    echo WARNING: Could not create scheduled task automatically.
    echo You can run tracker.py manually or create a task in Task Scheduler.
) else (
    echo [OK] Scheduled task created — will run every 2 hours
)

echo.
echo ============================================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Edit config.yaml and set your email credentials
echo  2. Run tracker.py now to do a first scan: python tracker.py
echo  3. Open latest_jobs.html in a browser to see all found jobs
echo ============================================================
echo.
pause
