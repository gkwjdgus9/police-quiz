@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 app.py) || (python app.py)
if errorlevel 1 (
  echo.
  echo Python 3.11 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치할 때 "Add python.exe to PATH" 를 체크하세요.
  pause
)
