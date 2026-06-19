param(
    [string]$HostAddress = "127.0.0.1:11434",
    [string]$KeepAlive = "24h",
    [int]$MaxLoadedModels = 1,
    [int]$NumParallel = 1
)

$ErrorActionPreference = "Stop"

$settings = @{
    OLLAMA_FLASH_ATTENTION = "1"
    OLLAMA_KEEP_ALIVE = $KeepAlive
    OLLAMA_MAX_LOADED_MODELS = [string]$MaxLoadedModels
    OLLAMA_NUM_PARALLEL = [string]$NumParallel
    OLLAMA_HOST = $HostAddress
}

foreach ($entry in $settings.GetEnumerator()) {
    Set-Item -Path "Env:$($entry.Name)" -Value $entry.Value
    [Environment]::SetEnvironmentVariable($entry.Name, $entry.Value, "User")
}

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    throw "Ollama is not installed or is not on PATH."
}

$running = Get-Process -Name ollama -ErrorAction SilentlyContinue
if ($running) {
    try {
        $running | Stop-Process -Force -ErrorAction Stop
    } catch {
        throw "Ollama GPU settings were saved, but the running ollama.exe process could not be stopped. Close Ollama from the system tray or run this script from an Administrator PowerShell, then run it again."
    }
}
Start-Sleep -Seconds 2

Start-Process -FilePath $ollama.Source `
    -ArgumentList "serve" `
    -WindowStyle Minimized

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        Invoke-RestMethod -Uri "http://$HostAddress/api/tags" -TimeoutSec 2 | Out-Null
        Write-Host "Ollama restarted with GPU performance settings."
        Write-Host "OLLAMA_FLASH_ATTENTION=$($settings.OLLAMA_FLASH_ATTENTION)"
        Write-Host "OLLAMA_KEEP_ALIVE=$($settings.OLLAMA_KEEP_ALIVE)"
        Write-Host "OLLAMA_MAX_LOADED_MODELS=$($settings.OLLAMA_MAX_LOADED_MODELS)"
        Write-Host "OLLAMA_NUM_PARALLEL=$($settings.OLLAMA_NUM_PARALLEL)"
        Write-Host "OLLAMA_HOST=$($settings.OLLAMA_HOST)"
        exit 0
    } catch {
        # Keep waiting for the server to accept requests.
    }
}

throw "Ollama did not start on http://$HostAddress within 30 seconds."
