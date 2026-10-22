param([ValidateSet('fake', 'live')][string]$Mode = 'fake')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$demoExecutable = Join-Path (Get-Location) '.venv\Scripts\datapilot-web.exe'
if (Test-Path -LiteralPath $demoExecutable) {
    & $demoExecutable launch --mode $Mode
} else {
    uv run --locked datapilot-web launch --mode $Mode
}
