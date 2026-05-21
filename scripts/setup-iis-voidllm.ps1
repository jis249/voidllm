param(
    [int]$Port = 8081,
    [string]$SiteName = "VoidLLM",
    [string]$BackendUrl = "http://localhost:8080"
)

$ErrorActionPreference = "Stop"

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
    winget install --id $packageId -e --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for $packageId with exit code $LASTEXITCODE"
    }
}

Import-Module WebAdministration

$siteRoot = Join-Path $env:SystemDrive "inetpub\voidllm"
New-Item -ItemType Directory -Path $siteRoot -Force | Out-Null

$rewriteUrl = $BackendUrl.TrimEnd("/") + "/{R:1}"
$webConfigPath = Join-Path $siteRoot "web.config"
@"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToVoidLLM" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="$rewriteUrl" />
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

Write-Host "IIS site '$SiteName' is configured on http://localhost:$Port and proxies to $BackendUrl"
