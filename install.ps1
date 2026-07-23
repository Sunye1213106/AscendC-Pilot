# AscendC Agent unified installer (Windows)
#
# Usage:
#   .\install.ps1 opencode|cursor|codex
#   .\install.ps1 uninstall-opencode
#   $env:SKIP_PIP=1; .\install.ps1 cursor
param(
  [Parameter(Position = 0)]
  [string]$Platform = "opencode"
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkipPip = $env:SKIP_PIP

function Get-PluginDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path $HOME ".config\opencode\ascendc-agent-plugin" }
    "cursor" { Join-Path $HOME ".cursor\ascendc-agent-plugin" }
    "codex" { Join-Path $HOME ".agents\ascendc-agent-plugin" }
    default { throw "Unknown platform $plat" }
  }
}
function Get-SkillsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path $HOME ".config\opencode\skills" }
    "cursor" { Join-Path $HOME ".cursor\skills" }
    "codex" { Join-Path $HOME ".agents\skills" }
  }
}
function Get-AgentsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path $HOME ".config\opencode\agents" }
    "cursor" { Join-Path $HOME ".cursor\agents" }
    "codex" { Join-Path $HOME ".agents\agents" }
  }
}

if ($Platform -like "uninstall-*") {
  $plat = $Platform.Substring("uninstall-".Length)
  $dest = Get-PluginDest $plat
  $skills = Get-SkillsDest $plat
  $agents = Get-AgentsDest $plat
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  foreach ($name in @("uo-init","uo-update","uo-query","uo-code-review","uo-diff","tg-init","tg-plan","tg-solve","understand-operator")) {
    $p = Join-Path $skills $name
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  foreach ($name in @("uo-semantic-resolve","uo-key-resolve","uo-confidence-review","uo-kb-review","uo-code-reviewer","tg-csv-contract","tg-init-audit")) {
    $p = Join-Path $agents "$name.md"
    if (Test-Path $p) { Remove-Item -Force $p }
  }
  Write-Host "Uninstalled $plat"
  exit 0
}

if ($SkipPip -ne "1") {
  python -m pip install -e "$BundleRoot\harness" -e "$BundleRoot\engines\uo" -e "$BundleRoot\engines\tg[solver]"
}

$Dest = Get-PluginDest $Platform
$Skills = Get-SkillsDest $Platform
$Agents = Get-AgentsDest $Platform
New-Item -ItemType Directory -Force -Path $Dest, $Skills, $Agents | Out-Null
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

foreach ($name in @("skills","prompts","agents","docs","engines","harness","templates")) {
  Copy-Item -Recurse -Force (Join-Path $BundleRoot $name) (Join-Path $Dest $name)
}

foreach ($name in @("uo-init","uo-update","uo-query","uo-code-review","tg-init","tg-plan","tg-solve")) {
  $target = Join-Path $Dest "skills\$name"
  $link = Join-Path $Skills $name
  if (Test-Path $link) { Remove-Item -Recurse -Force $link }
  try {
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
  } catch {
    Copy-Item -Recurse -Force $target $link
  }
}

Get-ChildItem (Join-Path $Dest "agents\*.md") | ForEach-Object {
  if ($_.Name -eq "tg-domain-review.md") { return }
  $link = Join-Path $Agents $_.Name
  if (Test-Path $link) { Remove-Item -Force $link }
  try {
    New-Item -ItemType SymbolicLink -Path $link -Target $_.FullName | Out-Null
  } catch {
    Copy-Item -Force $_.FullName $link
  }
}

$stampDir = Join-Path $Dest "templates\$Platform"
New-Item -ItemType Directory -Force -Path $stampDir | Out-Null
Set-Content -Path (Join-Path $stampDir "install_stamp.txt") -Value "plugin_root=$Dest"
Write-Host "Installed AscendC Agent Harness → $Dest"
Write-Host "Run: harness doctor"
