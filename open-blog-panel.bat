@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0scripts\blog_panel.py"
  if errorlevel 1 pause
  goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0scripts\blog_panel.py"
  if errorlevel 1 pause
  goto :done
)

echo.
echo Could not find Python.
echo Please install Python 3, then double-click this file again.
echo.
pause

:done
endlocal
