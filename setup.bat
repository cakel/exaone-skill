@echo off
rem exaone-skill installer wrapper -> setup.ps1 (args are passed through, e.g. -SkipKey -Effort high)
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
)
exit /b %ERRORLEVEL%
