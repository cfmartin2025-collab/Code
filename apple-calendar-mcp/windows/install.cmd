@echo off
REM Double-click to install the Apple Calendar MCP server for Claude Desktop.
REM Run "install.cmd -Uninstall" to remove it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
