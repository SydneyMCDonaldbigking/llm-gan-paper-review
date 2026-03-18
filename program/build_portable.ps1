param(
  [string]$PythonExe = "D:\anaconda\envs\for_codeX\python.exe"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceDir = Split-Path -Parent $scriptDir
$distRoot = Join-Path $workspaceDir "dist"
$portableRoot = Join-Path $distRoot "LLM_GAN_Paper_Review_Portable"

Set-Location $scriptDir

& $PythonExe -m pip install pyinstaller

if (Test-Path "$scriptDir\build") {
  Remove-Item "$scriptDir\build" -Recurse -Force
}
if (Test-Path "$scriptDir\dist") {
  Remove-Item "$scriptDir\dist" -Recurse -Force
}

& $PythonExe -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --name "LLM_GAN_Paper_Review" `
  --add-data "web;web" `
  launcher.py

New-Item -ItemType Directory -Force -Path $portableRoot | Out-Null

Copy-Item "$scriptDir\dist\LLM_GAN_Paper_Review\*" $portableRoot -Recurse -Force

foreach ($folder in @("essay", "api_settings", "final_report")) {
  New-Item -ItemType Directory -Force -Path (Join-Path $portableRoot $folder) | Out-Null
}

if (Test-Path "$workspaceDir\api_settings\llm_api_config.json") {
  Copy-Item "$workspaceDir\api_settings\llm_api_config.json" (Join-Path $portableRoot "api_settings\llm_api_config.json") -Force
}

Copy-Item "$workspaceDir\USER_QUICKSTART.md" (Join-Path $portableRoot "USER_QUICKSTART.md") -Force
Copy-Item "$workspaceDir\AGENT_ENV_SETUP.md" (Join-Path $portableRoot "AGENT_ENV_SETUP.md") -Force

@"
Double-click:
LLM_GAN_Paper_Review.exe

The app will:
1. start the local server
2. open the browser
3. use the local folders next to the exe:
   - essay
   - api_settings
   - final_report
"@ | Set-Content -Path (Join-Path $portableRoot "START_HERE.txt") -Encoding UTF8

Write-Host ""
Write-Host "Portable package created at:"
Write-Host $portableRoot
