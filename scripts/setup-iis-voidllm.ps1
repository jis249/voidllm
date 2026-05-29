param(
    [int]$Port = 8081,
    [string]$SiteName = "wai",
    [string]$BackendUrl = "http://localhost:8080"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$UiDir = Join-Path $Root "ui"
$UiDist = Join-Path $UiDir "dist"

function Test-WingetPackageInstalled {
    param([string]$PackageId)

    winget list --id $PackageId -e --accept-source-agreements | Out-Null
    return $LASTEXITCODE -eq 0
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This script must be run as Administrator."
}

$features = @(
    "IIS-WebServerRole",
    "IIS-WebServer",
    "IIS-CommonHttpFeatures",
    "IIS-DefaultDocument",
    "IIS-StaticContent",
    "IIS-HttpErrors",
    "IIS-HttpLogging",
    "IIS-RequestFiltering",
    "IIS-ManagementConsole",
    "IIS-ManagementScriptingTools"
)

foreach ($featureName in $features) {
    $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName
    if ($feature.State -ne "Enabled") {
        Enable-WindowsOptionalFeature -Online -FeatureName $featureName -All -NoRestart | Out-Null
    }
}

$packages = @(
    "Microsoft.IIS.URLRewrite",
    "Microsoft.IIS.ApplicationRequestRouting"
)

foreach ($packageId in $packages) {
    if (Test-WingetPackageInstalled $packageId) {
        Write-Host "$packageId is already installed."
        continue
    }

    winget install --id $packageId -e --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0 -and -not (Test-WingetPackageInstalled $packageId)) {
        throw "winget install failed for $packageId with exit code $LASTEXITCODE"
    }
}

Import-Module WebAdministration

$siteRoot = Join-Path $env:SystemDrive "inetpub\wai"
New-Item -ItemType Directory -Path $siteRoot -Force | Out-Null

if (-not (Test-Path (Join-Path $UiDist "index.html"))) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "WAI UI build was not found at $UiDist and npm is not on PATH."
    }

    Push-Location $UiDir
    try {
        if (-not (Test-Path (Join-Path $UiDir "node_modules"))) {
            npm ci
        }
        npm run build
    } finally {
        Pop-Location
    }
}

Copy-Item -Path (Join-Path $UiDist "*") -Destination $siteRoot -Recurse -Force

$rewriteApiUrl = $BackendUrl.TrimEnd("/") + "/{R:0}"
$webConfigPath = Join-Path $siteRoot "web.config"
@"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ProxyWaiApi" stopProcessing="true">
          <match url="^(api|v1)(/.*)?$" />
          <action type="Rewrite" url="$rewriteApiUrl" />
        </rule>
        <rule name="WaiSpaFallback" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
            <add input="{REQUEST_FILENAME}" matchType="IsDirectory" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
"@ | Set-Content -Path $webConfigPath -Encoding UTF8

$appPoolName = "${SiteName}AppPool"
if (-not (Test-Path "IIS:\AppPools\$appPoolName")) {
    New-WebAppPool -Name $appPoolName | Out-Null
}
Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name managedRuntimeVersion -Value ""
Set-ItemProperty "IIS:\AppPools\$appPoolName" -Name processModel.identityType -Value "ApplicationPoolIdentity"

$bindingInfo = "*:${Port}:"
$conflictingBinding = Get-WebBinding -Protocol "http" |
    Where-Object { $_.bindingInformation -eq $bindingInfo -and $_.ItemXPath -notmatch "name='$SiteName'" } |
    Select-Object -First 1
if ($conflictingBinding) {
    throw "Port $Port is already used by another IIS binding: $($conflictingBinding.ItemXPath)"
}

if (Test-Path "IIS:\Sites\$SiteName") {
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $siteRoot
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name applicationPool -Value $appPoolName
    Get-WebBinding -Name $SiteName -Protocol "http" | Remove-WebBinding
    New-WebBinding -Name $SiteName -Protocol "http" -Port $Port -IPAddress "*"
} else {
    New-Website -Name $SiteName -PhysicalPath $siteRoot -ApplicationPool $appPoolName -Port $Port -IPAddress "*" | Out-Null
}

$appcmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
& $appcmd set config -section:system.webServer/proxy /enabled:"True" /preserveHostHeader:"True" /reverseRewriteHostInResponseHeaders:"False" /commit:apphost
if ($LASTEXITCODE -ne 0) {
    throw "Failed to enable IIS ARR proxy."
}

Start-Service W3SVC
Start-Website -Name $SiteName

Write-Host "IIS site '$SiteName' is configured on http://localhost:$Port"
Write-Host "Serving WAI UI from $UiDist"
Write-Host "Proxying WAI API requests to $BackendUrl"
