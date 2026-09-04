$ErrorActionPreference = "Stop"

# Start the gateway from this checkout regardless of the caller's working directory.
$ScriptDir = $PSScriptRoot
Set-Location -LiteralPath $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$SettingsPath = Join-Path $ScriptDir "gateway-settings.toml"

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    throw "Cannot find virtual-environment Python: $VenvPython. Run 'uv sync' in $ScriptDir before starting the gateway."
}

if (-not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) {
    throw "Cannot find gateway settings: $SettingsPath. Copy gateway-settings.toml.template to gateway-settings.toml and configure it."
}

$env:PYTHONUNBUFFERED = "1"
Write-Host "Starting the SPD3000 gateway from: $ScriptDir"

& $VenvPython -m siglent_spd3000.cli gateway serve --config $SettingsPath @args
$GatewayExitCode = $LASTEXITCODE

exit $GatewayExitCode
