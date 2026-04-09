@echo off
echo ========================================
echo Starting Chrome with Remote Debugging
echo ========================================
echo.
echo This will open Chrome with remote debugging enabled.
echo You can use your existing Chrome profile, extensions, and logged-in sites.
echo.
echo Press Ctrl+C to cancel, or any key to continue...
pause >nul

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

echo.
echo Chrome is starting with debug port 9222...
echo You can now use MARK XXV browser control.
echo.
pause
