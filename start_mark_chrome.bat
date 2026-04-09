@echo off
echo ========================================
echo  MARK-XXXV Chrome Launcher
echo ========================================
echo.
echo Killing all Chrome processes...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

:CHECK
tasklist /FI "IMAGENAME eq chrome.exe" 2>nul | find /I "chrome.exe" >nul
if not errorlevel 1 (
    echo Waiting for Chrome to close...
    timeout /t 1 /nobreak >nul
    goto CHECK
)

echo Chrome closed. Starting with debug port...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\Users\bobul\AppData\Local\Google\Chrome\User Data"
echo.
echo Chrome opened with port 9222.
echo.
echo Testing connection...
timeout /t 3 >nul
curl -s --max-time 3 http://localhost:9222/json/version >nul 2>&1
if errorlevel 1 (
    echo WARNING: Could not verify port 9222.
    echo Please restore your tabs manually in Chrome.
    echo Then check: http://localhost:9222/json
) else (
    echo SUCCESS: Port 9222 is open.
)
echo.
echo Keep this window open. Close to exit.
pause
