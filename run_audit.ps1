param(
    [switch]$RefreshData,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv-project\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) { throw "Python was not found. Install Python and project dependencies first." }
    $Python = $PythonCommand.Source
}

if ($RefreshData) {
    & $Python -m pipeline.run_all
    $PipelineExitCode = $LASTEXITCODE
    # Always rebuild the report after processing. The report builder verifies
    # source hashes and clears stale comparison findings when current scope is
    # unavailable, so a failed refresh cannot leave old results on screen.
    & $Python build_market_report.py
    if ($LASTEXITCODE -ne 0) { throw "Report generation failed. See the error above." }
    if ($PipelineExitCode -ne 0) {
        throw "The dashboard report was refreshed, but the data pipeline is incomplete. Add the missing official source files shown above and rerun with -RefreshData. No replacement data was generated."
    }
}
elseif ((Test-Path "data\mart\comparison.parquet") -and
        (Test-Path "data\hpt\norm\hpt_file_quality.parquet") -and
        (Test-Path "data\mart\run_info.json")) {
    # Rebuild from saved outputs. The report generator verifies the current
    # CMS Part B selection evidence before presenting rankings.
    & $Python build_market_report.py
    if ($LASTEXITCODE -ne 0) { throw "Report generation failed. See the error above." }
}
else {
    Write-Warning "No complete pipeline outputs are available. The dashboard will show its empty state."
}

$BaseUrl = "http://127.0.0.1:$Port/"
$DashboardUrl = "${BaseUrl}dashboard/"
$WildcardProbeUrl = "${DashboardUrl}**"
$serverReady = $false
try {
    $null = Invoke-WebRequest -Uri $WildcardProbeUrl -TimeoutSec 2 -UseBasicParsing
    $serverReady = $true
    Write-Host "Using the dashboard server at $DashboardUrl"
}
catch {
    # Replace only this project's older Python static server. Do not stop an
    # unrelated process that happens to own the configured port.
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        $isOldProjectServer = $owner -and $owner.CommandLine -like "*http.server*" -and
            $owner.CommandLine.IndexOf($ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
        if ($isOldProjectServer) {
            Stop-Process -Id $listener.OwningProcess -Force
        }
        else {
            throw "Port $Port is already used by another process. Close it or choose another port with -Port."
        }
    }
    $ServerScript = Join-Path $ProjectRoot "scripts\dashboard_server.py"
    Start-Process -FilePath $Python `
        -ArgumentList @("`"$ServerScript`"", "--port", "$Port", "--bind", "127.0.0.1", "--directory", "`"$ProjectRoot`"") `
        -WorkingDirectory $ProjectRoot -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 300
        try {
            $null = Invoke-WebRequest -Uri $WildcardProbeUrl -TimeoutSec 2 -UseBasicParsing
            $serverReady = $true
            break
        }
        catch { }
    }
    if (-not $serverReady) { throw "Dashboard server did not become ready at $DashboardUrl" }
}

Write-Host "Dashboard: $DashboardUrl"
Write-Host "For fresh source processing, run: .\run_audit.ps1 -RefreshData"
