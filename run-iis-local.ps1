param(
    [string]$Version = "v0.0.19",
    [string]$PostgresUser = "postgres",
    [string]$PostgresPassword = "",
    [string]$DatabaseName = "wai",
    [int]$Port = 8081,
    [string]$SiteName = "wai",
    [string]$BackendUrl = "http://localhost:8080"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $Root "data"
$RunLocalScript = Join-Path $Root "run-local.ps1"
$SetupIisScript = Join-Path $Root "scripts\setup-iis-voidllm.ps1"

if (-not (Test-Path $RunLocalScript)) {
    throw "Could not find $RunLocalScript."
}
if (-not (Test-Path $SetupIisScript)) {
    throw "Could not find $SetupIisScript."
}

$backendUri = [Uri]$BackendUrl
$backendPort = $backendUri.Port
if ($backendPort -le 0) {
    $backendPort = if ($backendUri.Scheme -eq "https") { 443 } else { 80 }
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Start-LocalBackend {
    $runLocalArgs = @{
        Version = $Version
        PostgresUser = $PostgresUser
        DatabaseName = $DatabaseName
        BackendDetached = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($PostgresPassword)) {
        $runLocalArgs.PostgresPassword = $PostgresPassword
    }

    Write-Host "Starting wai backend on $BackendUrl..."
    & $RunLocalScript @runLocalArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$backend = Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue
if ($backend) {
    $backendProcessId = ($backend | Select-Object -First 1).OwningProcess
    $backendProcess = Get-Process -Id $backendProcessId -ErrorAction SilentlyContinue
    $backendPath = if ($backendProcess) { $backendProcess.Path } else { "" }
    $binDir = Join-Path $Root "bin"

    if ($backendProcess -and $backendPath -and $backendPath.StartsWith($binDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "Restarting wai backend on $BackendUrl so local model config is refreshed..."
        Stop-Process -Id $backendProcessId -Force
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 500
            $backend = Get-NetTCPConnection -LocalPort $backendPort -State Listen -ErrorAction SilentlyContinue
            if (-not $backend) {
                break
            }
        }
        Start-LocalBackend
    } else {
        throw "Port $backendPort is already in use by process $backendProcessId ($($backendProcess.ProcessName)). Stop it or choose a different -BackendUrl."
    }
} else {
    Start-LocalBackend
}

Write-Host "Configuring IIS site '$SiteName' on http://localhost:$Port..."
& $SetupIisScript -Port $Port -SiteName $SiteName -BackendUrl $BackendUrl
exit $LASTEXITCODE
