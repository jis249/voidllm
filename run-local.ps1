param(
    [string]$Version = "v0.0.19",
    [string]$PostgresUser = "postgres",
    [string]$PostgresPassword = "",
    [string]$DatabaseName = "wai",
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BinDir = Join-Path $Root "bin"
$DataDir = Join-Path $Root "data"
$EnvFile = Join-Path $Root ".env.local"
$Exe = Join-Path $BinDir "voidllm.exe"
$Config = Join-Path $Root "voidllm.yaml"
$UiDir = Join-Path $Root "ui"

function Get-PostgresTool {
    param([string]$Name)

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $commonPaths = @(
        "C:\Program Files\PostgreSQL\18\bin\$Name",
        "C:\Program Files\PostgreSQL\17\bin\$Name",
        "C:\Program Files\PostgreSQL\16\bin\$Name",
        "C:\Program Files\PostgreSQL\15\bin\$Name"
    )

    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    throw "$Name was not found. Install PostgreSQL client tools or add them to PATH."
}

function New-Secret {
    $bytes = [byte[]]::new(32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    [Convert]::ToBase64String($bytes)
}

function Read-LocalEnv {
    if (-not (Test-Path $EnvFile)) {
        return @{}
    }

    $values = @{}
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $values[$matches[1].Trim()] = $matches[2].Trim()
        }
    }
    $values
}

New-Item -ItemType Directory -Force -Path $BinDir, $DataDir | Out-Null

$envValues = Read-LocalEnv
if (-not $envValues.ContainsKey("VOIDLLM_ADMIN_KEY")) {
    $envValues["VOIDLLM_ADMIN_KEY"] = New-Secret
}
if (-not $envValues.ContainsKey("VOIDLLM_ENCRYPTION_KEY")) {
    $envValues["VOIDLLM_ENCRYPTION_KEY"] = New-Secret
}
if (-not $envValues.ContainsKey("POSTGRES_PASSWORD")) {
    if ([string]::IsNullOrWhiteSpace($PostgresPassword)) {
        throw "Set POSTGRES_PASSWORD in .env.local or pass -PostgresPassword."
    }
    $envValues["POSTGRES_PASSWORD"] = $PostgresPassword
}

$envValues.GetEnumerator() |
    Sort-Object Name |
    ForEach-Object { "$($_.Name)=$($_.Value)" } |
    Set-Content -Path $EnvFile -Encoding ASCII

foreach ($entry in $envValues.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Name)" -Value $entry.Value
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama is not installed or is not on PATH."
}

try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 | Out-Null
} catch {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Minimized
    Start-Sleep -Seconds 3
}

$psql = Get-PostgresTool "psql.exe"
$pgIsReady = Get-PostgresTool "pg_isready.exe"

& $pgIsReady -h localhost -p 5432 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL is not accepting connections on localhost:5432."
}

$env:PGPASSWORD = $envValues["POSTGRES_PASSWORD"]
$exists = & $psql -h localhost -p 5432 -U $PostgresUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DatabaseName'"
if ($exists -ne "1") {
    & $psql -h localhost -p 5432 -U $PostgresUser -d postgres -c "CREATE DATABASE $DatabaseName;"
}

if (-not (Test-Path $Exe)) {
    $zip = Join-Path $BinDir "voidllm-windows-amd64.zip"
    $url = "https://github.com/voidmind-io/voidllm/releases/download/$Version/voidllm-windows-amd64.zip"
    Write-Host "Downloading VoidLLM $Version..."
    Invoke-WebRequest -Uri $url -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $BinDir -Force
    Remove-Item $zip
}

if ($BackendOnly) {
    Write-Host "Starting wai backend locally..."
    Write-Host "Embedded UI/API: http://localhost:8080"
    Write-Host "Database: PostgreSQL localhost:5432/$DatabaseName"
    Write-Host "Models: default/local -> qwen3-coder:30b, gemma4/local-gemma -> gemma4:31b, local-embedding -> bge-m3:latest"
    & $Exe --config $Config
    exit $LASTEXITCODE
}

$backend = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if (-not $backend) {
    $backendLog = Join-Path $DataDir "wai-backend.log"
    $backendErr = Join-Path $DataDir "wai-backend.err.log"
    Start-Process -FilePath $Exe `
        -ArgumentList @("--config", $Config) `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErr

    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        $backend = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
        if ($backend) {
            break
        }
    }

    if (-not $backend) {
        throw "wai backend did not start on port 8080. Check $backendLog and $backendErr."
    }

    Write-Host "wai backend started on http://localhost:8080"
    Write-Host "Backend logs: $backendLog"
} else {
    Write-Host "wai backend already running on http://localhost:8080"
}

if (-not (Test-Path (Join-Path $UiDir "node_modules"))) {
    Push-Location $UiDir
    try {
        npm ci
    } finally {
        Pop-Location
    }
}

Write-Host "Starting wai source UI locally..."
Write-Host "WAI UI: http://127.0.0.1:5173"
Write-Host "Backend API: http://localhost:8080"
Write-Host "Database: PostgreSQL localhost:5432/$DatabaseName"
Write-Host "Models: default/local -> qwen3-coder:30b, gemma4/local-gemma -> gemma4:31b, local-embedding -> bge-m3:latest"
Push-Location $UiDir
try {
    npm run dev -- --host 127.0.0.1
} finally {
    Pop-Location
}
