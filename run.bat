@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM 不打包、直接執行（需先跑過一次 build.bat 建立環境，或自行 pip install -r requirements.txt）
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" blur_sorter.py
) else (
    start "" pythonw blur_sorter.py
)
