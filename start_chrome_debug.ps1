# start_chrome_debug.ps1
# Run this ONCE before starting Mark-XXXV. It launches Chrome with debug port.
# Uses your EXISTING Chrome profile - all your sessions are preserved!

param(
    [int]$DebugPort = 9222
)

$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$UserData = "$env:LOCALAPPDATA\Google\Chrome\User Data"

Write-Host "=========================================="
Write-Host "MARK-XXXV Chrome Debug Launcher"
Write-Host "=========================================="
Write-Host "Debug Port: $DebugPort"
Write-Host ""

# Check if Chrome is already running with debug port
Write-Host "[1/3] Checking for existing Chrome with debug port..."
$ChromeRunning = Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowHandle -ne 0
} | Select-Object -First 1

if ($ChromeRunning) {
    Write-Host "[OK] Chrome already running (PID: $($ChromeRunning.Id))"
    Write-Host "[OK] Your sessions are preserved!"
} else {
    Write-Host "[2/3] Launching Chrome with debug port $DebugPort..."
    $Args = @(
        "--remote-debugging-port=$DebugPort",
        "--user-data-dir=$UserData",
        "--no-first-run",
        "--no-default-browser-check"
    )
    $Proc = Start-Process -FilePath $ChromePath -ArgumentList $Args -PassThru -WindowStyle Normal
    Write-Host "       Chrome PID: $($Proc.Id)"
}

# Wait for debug port to be ready using .NET HttpWebRequest (more reliable)
Write-Host ""
Write-Host "Waiting for debug port..."
$Ready = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 1
    try {
        $Req = [System.Net.HttpWebRequest]::Create("http://localhost:$DebugPort/json/version")
        $Req.Timeout = 2000
        $Resp = $Req.GetResponse()
        $Status = $Resp.StatusCode
        $Resp.Close()
        if ($Status -eq 200) {
            $Ready = $true
            Write-Host ""
            Write-Host "SUCCESS! Debug port $DebugPort is open." -ForegroundColor Green
            Write-Host ""
            Write-Host "SUCCESS! Debug port $DebugPort is ready." -ForegroundColor Green
            Write-Host ""
            Write-Host "Chrome is connected with debug port." -ForegroundColor Yellow
            Write-Host "Close this window to stop the debug browser." -ForegroundColor Yellow
            Write-Host ""
            Write-Host "Press Enter to close Chrome and exit..."
            Read-Host
            Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue
            exit 0
        }
    } catch {}
    Write-Host "  ... waiting ($($i+1)/10)"
}

Write-Host ""
Write-Host "Timeout waiting for debug port." -ForegroundColor Red
Write-Host "Try closing Chrome manually and running this script again."
Write-Host "Press Enter to exit..."
Read-Host
