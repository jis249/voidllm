param(
    [string]$PostgresUser = "postgres",
    [string]$PostgresPassword = "",
    [string]$DatabaseName = "wai",
    [string]$Config = "",
    [switch]$BackendOnly,
    [switch]$BackendDetached,
    [switch]$DevUi
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $Root "data"
$EnvFile = Join-Path $Root ".env.local"
if ([string]::IsNullOrWhiteSpace($Config)) {
    $Config = Join-Path $Root "wai.yaml"
}
$UiDir = Join-Path $Root "ui"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

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

function Set-OllamaPerformanceDefaults {
    param([hashtable]$Values)

    $defaults = @{
        OLLAMA_FLASH_ATTENTION = "1"
        OLLAMA_KEEP_ALIVE = "24h"
        OLLAMA_MAX_LOADED_MODELS = "1"
        OLLAMA_NUM_PARALLEL = "1"
        OLLAMA_HOST = "127.0.0.1:11434"
    }

    foreach ($entry in $defaults.GetEnumerator()) {
        if (-not $Values.ContainsKey($entry.Name)) {
            $Values[$entry.Name] = $entry.Value
        }
    }
}

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

function Test-PostgresPort {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", 5432)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Start-DockerPostgres {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $false
    }

    $compose = Join-Path $Root "docker-compose.yml"
    if (-not (Test-Path $compose)) {
        return $false
    }

    Write-Host "Starting PostgreSQL via Docker Compose..."
    docker compose -f $compose up -d postgres | Out-Null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-PostgresPort) {
            return $true
        }
    }

    return $false
}

function Ensure-PostgresDatabase {
    param(
        [string]$User,
        [string]$Password,
        [string]$DbName
    )

    if (-not (Test-PostgresPort)) {
        if (-not (Start-DockerPostgres)) {
            throw "PostgreSQL is not accepting connections on localhost:5432. Start PostgreSQL or run: docker compose up -d postgres"
        }
    }

    $psql = Get-PostgresTool "psql.exe"
    $env:PGPASSWORD = $Password
    $exists = & $psql -h localhost -p 5432 -U $User -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'"
    if ($exists -ne "1") {
        Write-Host "Creating PostgreSQL database '$DbName'..."
        & $psql -h localhost -p 5432 -U $User -d postgres -c "CREATE DATABASE $DbName;"
    }
}

function Ensure-PythonEnv {
    if (-not (Test-Path $VenvPython)) {
        Write-Host "Creating Python virtual environment..."
        python -m venv (Join-Path $Root ".venv")
        & $VenvPython -m pip install --upgrade pip
        & $VenvPython -m pip install -e $Root
    }
}

function Get-ProxyPort {
    param([string]$ConfigPath)
    if (-not (Test-Path $ConfigPath)) {
        return 8090
    }
    $match = Select-String -Path $ConfigPath -Pattern '^\s*port:\s*(\d+)\s*$' | Select-Object -First 1
    if ($match -and $match.Matches.Groups.Count -gt 1) {
        return [int]$match.Matches.Groups[1].Value
    }
    return 8090
}

function Start-BackendDetached {
    param(
        [int]$Port = 8090,
        [string]$LogName = "wai-backend.log",
        [string]$ErrorLogName = "wai-backend.err.log"
    )

    $backend = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($backend) {
        Write-Host "wai backend already running on http://localhost:$Port"
        return
    }

    $backendLog = Join-Path $DataDir $LogName
    $backendErr = Join-Path $DataDir $ErrorLogName
    $env:WAI_DEV = "true"
    $backendProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList @("-m", "wai", "--config", $Config, "--host", "0.0.0.0", "--port", "$Port") `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErr `
        -PassThru

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        $backend = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($backend) {
            break
        }

        if ($backendProcess.HasExited) {
            $message = "wai backend exited before it started listening on port $Port."
            if (Test-Path $backendErr) {
                $errorText = Get-Content -Path $backendErr -Raw
                if (-not [string]::IsNullOrWhiteSpace($errorText)) {
                    $message = "$message`n$errorText"
                }
            }
            throw $message
        }
    }

    if (-not $backend) {
        throw "wai backend did not start on port $Port. Check $backendLog and $backendErr."
    }

    Write-Host "wai backend started on http://localhost:$Port"
    Write-Host "Backend process id: $($backendProcess.Id)"
    Write-Host "Backend logs: $backendLog"
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$envValues = Read-LocalEnv
if (-not $envValues.ContainsKey("WAI_ADMIN_KEY")) {
    $envValues["WAI_ADMIN_KEY"] = New-Secret
}
if (-not $envValues.ContainsKey("WAI_ENCRYPTION_KEY")) {
    $envValues["WAI_ENCRYPTION_KEY"] = New-Secret
}
if (-not $envValues.ContainsKey("POSTGRES_PASSWORD")) {
    if (-not [string]::IsNullOrWhiteSpace($PostgresPassword)) {
        $envValues["POSTGRES_PASSWORD"] = $PostgresPassword
    } else {
        throw "Set POSTGRES_PASSWORD in .env.local or pass -PostgresPassword."
    }
}
Set-OllamaPerformanceDefaults -Values $envValues

$envValues.GetEnumerator() |
    Sort-Object Name |
    ForEach-Object { "$($_.Name)=$($_.Value)" } |
    Set-Content -Path $EnvFile -Encoding ASCII

foreach ($entry in $envValues.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Name)" -Value $entry.Value
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Warning "Ollama is not installed or is not on PATH."
} else {
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 | Out-Null
    } catch {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Minimized
        Start-Sleep -Seconds 3
    }
}

Ensure-PythonEnv

if (-not $envValues.ContainsKey("POSTGRES_PASSWORD")) {
    throw "POSTGRES_PASSWORD is required for PostgreSQL."
}

& $VenvPython (Join-Path $Root "scripts\db\ensure_pg_db.py")
if ($LASTEXITCODE -ne 0) { throw "Failed to ensure PostgreSQL database exists." }

try {
    Ensure-PostgresDatabase -User $PostgresUser -Password $envValues["POSTGRES_PASSWORD"] -DbName $DatabaseName
} catch {
    Write-Warning "psql/pg_isready not available; database was ensured via Python script."
}

$Port = Get-ProxyPort -ConfigPath $Config

if ($BackendDetached) {
    Write-Host "Starting wai backend in the background..."
    Write-Host "API: http://localhost:$Port"
    Write-Host "Database: PostgreSQL localhost:5432/$DatabaseName"
    Start-BackendDetached -Port $Port
    exit 0
}

if ($BackendOnly) {
    Write-Host "Starting wai backend locally..."
    Write-Host "API: http://localhost:$Port"
    Write-Host "Database: PostgreSQL localhost:5432/$DatabaseName"
    $env:WAI_DEV = "true"
    & $VenvPython -m wai --config $Config --host 0.0.0.0 --port $Port
    exit $LASTEXITCODE
}

Start-BackendDetached -Port $Port

if (-not (Test-Path (Join-Path $UiDir "node_modules"))) {
    Push-Location $UiDir
    try {
        npm ci
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path (Join-Path $UiDir "dist\index.html"))) {
    Write-Host "Building wai UI..."
    Push-Location $UiDir
    try {
        npm run build
    } finally {
        Pop-Location
    }
}

Write-Host "WAI dashboard: http://localhost:$Port"
Write-Host "Database: PostgreSQL localhost:5432/$DatabaseName"

if (-not $DevUi) {
    Write-Host "Backend running in background. Use -DevUi for Vite hot-reload on port 5173."
    exit 0
}

Write-Host "WAI dev UI: http://127.0.0.1:5173"
Write-Host "Backend API: http://localhost:$Port"
Push-Location $UiDir
try {
    npm run dev -- --host 127.0.0.1
} finally {
    Pop-Location
}
