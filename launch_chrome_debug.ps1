# launch_chrome_debug.ps1
# Run as Administrator for best results
# Opens Chrome with debug port enabled, preserving your profile

$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$userDataDir = "$env:LOCALAPPDATA\Google\Chrome\User Data"

Write-Host "========================================"
Write-Host "MARK-XXXV Chrome Debug Launcher"
Write-Host "========================================"
Write-Host ""

# Kill all Chrome processes
Write-Host "[1/4] Closing Chrome..."
Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Verify Chrome is closed
$remaining = (Get-Process chrome -ErrorAction SilentlyContinue).Count
if ($remaining -gt 0) {
    Write-Host "WARNING: Some Chrome processes still running. Will try anyway..."
    Start-Sleep -Seconds 2
}

# Launch Chrome with debug port
Write-Host "[2/4] Launching Chrome with debug port..."
$proc = Start-Process $chromePath -ArgumentList "--remote-debugging-port=9222","--user-data-dir=`"$userDataDir`"" -PassThru
Write-Host "       Process ID: $($proc.Id)"

# Wait for Chrome to start
Write-Host "[3/4] Waiting for Chrome to initialize..."
Start-Sleep -Seconds 4

# Check if debug port is open
Write-Host "[4/4] Checking debug port..."
try {
    $response = Invoke-WebRequest -Uri "http://localhost:9222/json/version" -TimeoutSec 5 -ErrorAction Stop
    $data = $response.Content | ConvertFrom-Json
    Write-Host ""
    Write-Host "SUCCESS! Debug port 9222 is open." -ForegroundColor Green
    Write-Host "Browser: $($data.Browser)"
    Write-Host "WebKit: $($data['WebKit-Version'])"
    Write-Host ""
    Write-Host "Chrome is ready. Keep this window open." -ForegroundColor Yellow
    Write-Host "Close this window to stop MARK-XXXV's browser automation."
} catch {
    Write-Host ""
    Write-Host "WARNING: Debug port not responding yet." -ForegroundColor Yellow
    Write-Host "Chrome might still be initializing or showing the restore page."
    Write-Host "Please click 'Restore pages' in Chrome if prompted."
    Write-Host "Then check http://localhost:9222/json in your browser."
}

Write-Host ""
