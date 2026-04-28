@echo off
echo Starting...
pause
python --version
pause
if not exist venv (
    echo Creating venv...
    python -m venv venv
)
echo Running App...
.\venv\Scripts\python.exe Main_App.pyw
echo Finished.
pause
