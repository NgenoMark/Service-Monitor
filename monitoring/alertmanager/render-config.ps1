$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot "..\..\.env"
$templateFile = Join-Path $PSScriptRoot "alertmanager.yml.tpl"
$outputFile = Join-Path $PSScriptRoot "alertmanager.local.yml"

if (-not (Test-Path $envFile)) {
    throw ".env not found at $envFile"
}

if (-not (Test-Path $templateFile)) {
    throw "Template not found at $templateFile"
}

$kv = @{}
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $parts = $line -split "=", 2
    if ($parts.Count -eq 2) {
        $kv[$parts[0].Trim()] = $parts[1].Trim()
    }
}

$required = @("SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL_TO")
foreach ($name in $required) {
    if (-not $kv.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($kv[$name])) {
        throw "Missing required key in .env: $name"
    }
}

$content = Get-Content $templateFile -Raw
$content = $content.Replace('${SMTP_HOST}', $kv["SMTP_HOST"])
$content = $content.Replace('${SMTP_FROM}', $kv["SMTP_FROM"])
$content = $content.Replace('${SMTP_USER}', $kv["SMTP_USER"])
$content = $content.Replace('${SMTP_PASSWORD}', $kv["SMTP_PASSWORD"])
$content = $content.Replace('${ALERT_EMAIL_TO}', $kv["ALERT_EMAIL_TO"])

Set-Content -Path $outputFile -Value $content -NoNewline
Write-Output "Generated $outputFile"
