# start_mark_chrome.ps1
# Run this ONCE before starting Mark-XXXV. It launches Chrome with debug port.
# Chrome will keep running with debug port until you close it.

$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$UserData = "$env:LOCALAPPDATA\Google\Chrome\User Data"
$DebugPort = 9222

Write-Host "=========================================="
Write-Host "MARK-XXXV Chrome Launcher"
Write-Host "=========================================="
Write-Host ""

# Step 1: Kill all Chrome processes
Write-Host "[1/3] Killing Chrome..."
Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# Check if Chrome service is trying to restart
$ChromeRunning = Get-Process chrome -ErrorAction SilentlyContinue
if ($ChromeRunning) {
    Write-Host "Chrome still running, forcing kill again..."
    Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

# Step 2: Disable Chrome's auto-restart so we can control it
Write-Host "[2/3] Disabling Chrome background services..."
$PrefsPath = "$UserData\Default\Preferences"
if (Test-Path $PrefsPath) {
    try {
        $Prefs = Get-Content $PrefsPath -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        # Temporarily disable background mode
        $Prefs.profile.exited_cleanly = $true
        $Prefs.profile.exit_type = "Normal"
        $Prefs | ConvertTo-Json -Depth 10 | Set-Content $PrefsPath -ErrorAction SilentlyContinue
    } catch {
        # Continue even if prefs edit fails
    }
}

# Also create a Local State override to disable metrics
$LocalState = "$UserData\Local State"
if (Test-Path $LocalState) {
    try {
        $LS = Get-Content $LocalState -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        $LS.profile.$($Prefs.profile.name).$("Default") | Add-Member -Force -NotePropertyName "exited_cleanly" -NotePropertyValue $true
    } catch {}
}

# Step 3: Launch Chrome with debug port
Write-Host "[3/3] Launching Chrome with debug port $DebugPort..."
$Args = @(
    "--remote-debugging-port=$DebugPort",
    "--user-data-dir=$UserData",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-experiments",
    "--no-crash-reporter",
    "--disable-crash-reporter",
    "--disable-background-networking",
    "--disable-client-side-phishing-detection"
)

$Proc = Start-Process -FilePath $ChromePath -ArgumentList $Args -PassThru -WindowStyle Normal
Write-Host "       Chrome PID: $($Proc.Id)"
Start-Sleep -Seconds 4

# Verify debug port
try {
    $Response = Invoke-WebRequest -Uri "http://localhost:$DebugPort/json/version" -TimeoutSec 5 -ErrorAction Stop
    $Data = $Response.Content | ConvertFrom-Json
    Write-Host ""
    Write-Host "SUCCESS! Debug port $DebugPort is open." -ForegroundColor Green
    Write-Host "Browser: $($Data.Browser)"
    Write-Host ""
    Write-Host "Chrome is ready. Keep this window open." -ForegroundColor Yellow
    Write-Host "Close this window to stop MARK-XXXV's browser automation."
} catch {
    Write-Host ""
    Write-Host "Chrome started but debug port not responding yet." -ForegroundColor Yellow
    Write-Host "If Chrome shows a 'Restore pages' dialog, click 'Restore pages'."
    Write-Host "Then this script will detect the port."
    Write-Host ""
    Write-Host "Waiting up to 15 seconds for Chrome to fully start..."

    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        try {
            $Response = Invoke-WebRequest -Uri "http://localhost:$DebugPort/json/version" -TimeoutSec 2 -ErrorAction Stop
            Write-Host "Debug port $DebugPort is now open!" -ForegroundColor Green
            break
        } catch {
            Write-Host "  ... waiting ($($i+1)/15)"
        }
    }
}

Write-Host ""
Write-Host "Press Enter to close this window..."
Read-Host
