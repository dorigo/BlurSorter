@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   失焦照片分類器 - 打包成 BlurSorter.exe
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py -3
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [錯誤] 找不到 Python。請先到 https://www.python.org/downloads/ 安裝 Python 3.10 以上，
        echo        安裝時記得勾選「Add python.exe to PATH」。
        pause
        exit /b 1
    )
    set PY=python
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 建立虛擬環境...
    %PY% -m venv .venv || goto :fail
)

echo [2/3] 安裝套件...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller -q || goto :fail

echo [3/3] 準備圖示並打包（約 1~3 分鐘）...
".venv\Scripts\python.exe" make_icon.py || goto :fail
set ICON_ARGS=
if exist "icon.ico" set ICON_ARGS=--icon "icon.ico" --add-data "icon.ico;."
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed ^
    --name BlurSorter ^
    --add-data "models;models" ^
    %ICON_ARGS% ^
    blur_sorter.py || goto :fail

echo.
echo ============================================
echo   完成！執行檔位置：dist\BlurSorter.exe
echo   這個 exe 可以單獨複製到其他 Windows 電腦使用
echo.
echo   如果檔案總管還顯示舊圖示，是 Windows 圖示快取的關係，
echo   把 exe 改個名字或重新開機就會更新
echo ============================================
explorer dist
pause
exit /b 0

:fail
echo.
echo [錯誤] 打包失敗，請把上方訊息截圖回報。
pause
exit /b 1
