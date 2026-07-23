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
function Get-PluginsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path $HOME ".config\opencode\plugins" }
    default { $null }
  }
}

if ($Platform -like "uninstall-*") {
  $plat = $Platform.Substring("uninstall-".Length)
  $dest = Get-PluginDest $plat
  $skills = Get-SkillsDest $plat
  $agents = Get-AgentsDest $plat
  $plugins = Get-PluginsDest $plat
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  foreach ($name in @("uo-init","uo-update","uo-query","uo-code-review","tg-init","tg-plan","tg-solve","operator","_policies","understand-operator","uo-diff")) {
    $p = Join-Path $skills $name
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  foreach ($name in @("ascendc-agent","uo-semantic-resolve","uo-key-resolve","uo-confidence-review","uo-kb-review","uo-code-reviewer","uo-query","tg-csv-contract","tg-semantic-bind","tg-init-audit","deterministic-uo-engine","deterministic-tg-engine")) {
    $p = Join-Path $agents "$name.md"
    if (Test-Path $p) { Remove-Item -Force $p }
  }
  if ($plat -eq "opencode" -and $plugins) {
    $pluginFile = Join-Path $plugins "ascendc-harness.ts"
    if (Test-Path $pluginFile) { Remove-Item -Force $pluginFile }
  }
  Write-Host "Uninstalled $plat"
  exit 0
}

if ($SkipPip -ne "1") {
  python -m pip install -e "$BundleRoot\harness" -e "$BundleRoot\engines\uo" -e "$BundleRoot\engines\tg[solver]"
}

# Compose sources → generated/<platform>/{skills,agents,prompts}
python "$BundleRoot\scripts\compose_runtime.py" --repo "$BundleRoot" --host $Platform
if ($LASTEXITCODE -ne 0) { throw "compose_runtime failed" }

$Dest = Get-PluginDest $Platform
$Skills = Get-SkillsDest $Platform
$Agents = Get-AgentsDest $Platform
New-Item -ItemType Directory -Force -Path $Dest, $Skills, $Agents | Out-Null
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# Bundle sources for offline reference (not runtime authority)
foreach ($name in @("skills-src","prompts-src","agents-src","docs","engines","harness","templates","scripts","opencode-plugin")) {
  $src = Join-Path $BundleRoot $name
  if (Test-Path $src) {
    Copy-Item -Recurse -Force $src (Join-Path $Dest $name)
  }
}

# Install ONLY generated runtime trees
$genRoot = Join-Path $BundleRoot "generated\$Platform"
Copy-Item -Recurse -Force (Join-Path $genRoot "skills") (Join-Path $Dest "skills")
Copy-Item -Recurse -Force (Join-Path $genRoot "agents") (Join-Path $Dest "agents")
if (Test-Path (Join-Path $genRoot "prompts")) {
  Copy-Item -Recurse -Force (Join-Path $genRoot "prompts") (Join-Path $Dest "prompts")
}

# Purge pre-harness legacy skills that teach free-form LLM KB builds (breaks Tab→ascendc-agent flow).
foreach ($legacy in @("understand-operator", "uo-diff")) {
  $legacyLink = Join-Path $Skills $legacy
  if (Test-Path $legacyLink) {
    Remove-Item -Recurse -Force $legacyLink
    Write-Host "Removed legacy skill → $legacyLink"
  }
}

foreach ($name in @("uo-init","uo-update","uo-query","uo-code-review","tg-init","tg-plan","tg-solve","operator")) {
  $target = Join-Path $Dest "skills\$name"
  if (-not (Test-Path $target)) { continue }
  $link = Join-Path $Skills $name
  if (Test-Path $link) { Remove-Item -Recurse -Force $link }
  try {
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
  } catch {
    Copy-Item -Recurse -Force $target $link
  }
}

$agentDir = Join-Path $Dest "agents"
if (-not (Test-Path $agentDir)) {
  throw "generated agents missing under $agentDir (compose may have failed)"
}
$agentFiles = @(Get-ChildItem -Path $agentDir -Filter "*.md" -File)
if ($agentFiles.Count -eq 0) {
  throw "no agent .md files under $agentDir"
}
foreach ($agentFile in $agentFiles) {
  $link = Join-Path $Agents $agentFile.Name
  if (-not $link) { throw "Agents dest unresolved: Agents=$Agents" }
  if (Test-Path -LiteralPath $link) { Remove-Item -Force -LiteralPath $link }
  try {
    New-Item -ItemType SymbolicLink -Path $link -Target $agentFile.FullName -ErrorAction Stop | Out-Null
  } catch {
    # NOTE: inside catch, $_ is the ErrorRecord — must use $agentFile, not $_.FullName
    Copy-Item -Force -LiteralPath $agentFile.FullName -Destination $link
  }
  if (-not (Test-Path -LiteralPath $link)) {
    throw "failed to install agent $($agentFile.Name) → $link"
  }
}

if ($Platform -eq "opencode") {
  $plugins = Get-PluginsDest "opencode"
  New-Item -ItemType Directory -Force -Path $plugins | Out-Null
  $pluginSrc = Join-Path $BundleRoot "opencode-plugin\ascendc-harness.ts"
  if (Test-Path $pluginSrc) {
    Copy-Item -Force $pluginSrc (Join-Path $plugins "ascendc-harness.ts")
    Write-Host "Installed plugin → $plugins\ascendc-harness.ts"
  }
  Write-Host "Primary agent → $Agents\ascendc-agent.md (Tab 切换；未改 opencode.json)"
}

$stampDir = Join-Path $Dest "templates\$Platform"
New-Item -ItemType Directory -Force -Path $stampDir | Out-Null
Set-Content -Path (Join-Path $stampDir "install_stamp.txt") -Value "plugin_root=$Dest"
Write-Host "Installed AscendC Agent Harness → $Dest"
Write-Host "Run: harness doctor"
