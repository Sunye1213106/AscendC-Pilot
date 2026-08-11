# AscendC-Pilot unified installer (Windows)
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
    "opencode" { Join-Path $HOME ".config\opencode\ascendc-pilot-plugin" }
    "cursor" { Join-Path $HOME ".cursor\ascendc-pilot-plugin" }
    "codex" { Join-Path $HOME ".agents\ascendc-pilot-plugin" }
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

function Remove-LegacyAscendcAgentBits([string]$plat, [string]$skills, [string]$agents, [string]$plugins) {
  # Remove previous or deterministic-only entries that would otherwise appear
  # as selectable OpenCode/Cursor agents after an upgrade.
  foreach ($name in @("uo-code-review", "understand-operator", "uo-diff")) {
    $p = Join-Path $skills $name
    if (Test-Path -LiteralPath $p) {
      Remove-Item -Recurse -Force -LiteralPath $p
      Write-Host "Removed legacy skill → $p"
    }
  }
  foreach ($name in @(
    "ascendc-agent", "uo-code-reviewer", "deterministic-uo-engine", "deterministic-tg-engine",
    "uo-semantic-resolve", "uo-gap-resolve", "uo-key-resolve", "uo-confidence-review", "uo-kb-review", "README"
  )) {
    $p = Join-Path $agents "$name.md"
    if (Test-Path -LiteralPath $p) {
      Remove-Item -Force -LiteralPath $p
      Write-Host "Removed legacy agent → $p"
    }
  }
  if ($plat -eq "opencode") {
    $legacyPlug = Join-Path $HOME ".config\opencode\ascendc-agent-plugin"
    if (Test-Path -LiteralPath $legacyPlug) {
      Remove-Item -Recurse -Force -LiteralPath $legacyPlug
      Write-Host "Removed legacy plugin tree → $legacyPlug"
    }
    if ($plugins) {
      $harness = Join-Path $plugins "ascendc-harness.ts"
      if (Test-Path -LiteralPath $harness) {
        Remove-Item -Force -LiteralPath $harness
        Write-Host "Removed legacy plugin → $harness"
      }
    }
  }
}

if ($Platform -like "uninstall-*") {
  $plat = $Platform.Substring("uninstall-".Length)
  $dest = Get-PluginDest $plat
  $skills = Get-SkillsDest $plat
  $agents = Get-AgentsDest $plat
  $plugins = Get-PluginsDest $plat
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  foreach ($name in @("uo-init","uo-update","uo-query","uo-investigate","ce-review","tg-init","tg-plan","tg-solve","operator","_policies","understand-operator","uo-diff","uo-code-review")) {
    $p = Join-Path $skills $name
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  foreach ($name in @("ascendc-pilot","ascendc-agent","uo-semantic-resolve","uo-semantic-resolver","uo-gap-investigator","uo-gap-resolve","uo-key-resolve","uo-confidence-review","uo-kb-review","ce-reviewer","uo-query","uo-code-reviewer","tg-csv-contract","tg-semantic-bind","tg-init-audit","deterministic-uo-engine","deterministic-tg-engine","README")) {
    $p = Join-Path $agents "$name.md"
    if (Test-Path $p) { Remove-Item -Force $p }
  }
  if ($plat -eq "opencode" -and $plugins) {
    foreach ($pluginName in @("ascendc-pilot.ts", "ascendc-harness.ts")) {
      $pluginFile = Join-Path $plugins $pluginName
      if (Test-Path $pluginFile) { Remove-Item -Force $pluginFile }
    }
    $legacyPlug = Join-Path $HOME ".config\opencode\ascendc-agent-plugin"
    if (Test-Path -LiteralPath $legacyPlug) { Remove-Item -Recurse -Force -LiteralPath $legacyPlug }
  }
  Write-Host "Uninstalled $plat"
  exit 0
}

if ($SkipPip -ne "1") {
  python -m pip install -r "$BundleRoot\requirements.txt"
}

# Compose sources, then retain only model-reachable runtime context.
python "$BundleRoot\scripts\compose_runtime.py" --repo "$BundleRoot" --host $Platform
if ($LASTEXITCODE -ne 0) { throw "compose_runtime failed" }
python "$BundleRoot\scripts\prune_runtime_context.py" --repo "$BundleRoot" --host $Platform
if ($LASTEXITCODE -ne 0) { throw "prune_runtime_context failed" }

$Dest = Get-PluginDest $Platform
$Skills = Get-SkillsDest $Platform
$Agents = Get-AgentsDest $Platform
New-Item -ItemType Directory -Force -Path $Dest, $Skills, $Agents | Out-Null
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# Bundle runtime implementation only.  Agent-facing skills/prompts/agents are
# copied exclusively from generated/<host> below; docs/templates are not runtime context.
foreach ($name in @("pilot","scripts","opencode-plugin")) {
  $src = Join-Path $BundleRoot $name
  if (Test-Path $src) {
    Copy-Item -Recurse -Force $src (Join-Path $Dest $name)
  }
}
# Engines bundled by the runtime installer.
$enginesDest = Join-Path $Dest "engines"
New-Item -ItemType Directory -Force -Path $enginesDest | Out-Null
foreach ($eng in @("common","understand-operator","testcase-generation","code-engineering")) {
  $src = Join-Path $BundleRoot "engines\$eng"
  if (Test-Path $src) {
    Copy-Item -Recurse -Force $src (Join-Path $enginesDest $eng)
  }
}

# Install ONLY generated runtime trees.
$genRoot = Join-Path $BundleRoot "generated\$Platform"
foreach ($name in @("skills", "agents", "prompts")) {
  $p = Join-Path $Dest $name
  if (Test-Path -LiteralPath $p) { Remove-Item -Recurse -Force -LiteralPath $p }
}
Copy-Item -Recurse -Force (Join-Path $genRoot "skills") (Join-Path $Dest "skills")
Copy-Item -Recurse -Force (Join-Path $genRoot "agents") (Join-Path $Dest "agents")
if (Test-Path (Join-Path $genRoot "prompts")) {
  Copy-Item -Recurse -Force (Join-Path $genRoot "prompts") (Join-Path $Dest "prompts")
}

# Purge leftovers from earlier installs before linking the current closure.
Remove-LegacyAscendcAgentBits -plat $Platform -skills $Skills -agents $Agents -plugins (Get-PluginsDest $Platform)

$workflowSkills = @("uo-init","uo-update","uo-query","uo-investigate","ce-review","tg-init","tg-plan","tg-solve","operator")
$cognitiveSkills = @("operator-analysis","testcase-generation","source-proof","code-review","_shared")

foreach ($name in $workflowSkills) {
  $target = Join-Path $Dest "skills\$name"
  if (-not (Test-Path -LiteralPath $target)) {
    throw "generated skill missing: $target (compose/copy failed)"
  }
  $link = Join-Path $Skills $name
  if (Test-Path -LiteralPath $link) { Remove-Item -Recurse -Force -LiteralPath $link }
  try {
    New-Item -ItemType Junction -Path $link -Target $target -ErrorAction Stop | Out-Null
  } catch {
    Copy-Item -Recurse -Force -LiteralPath $target -Destination $link
  }
  if (-not (Test-Path -LiteralPath $link)) {
    throw "failed to install skill $name → $link"
  }
}

if ($Platform -eq "opencode") {
  foreach ($name in $cognitiveSkills) {
    $link = Join-Path $Skills $name
    if (Test-Path -LiteralPath $link) { Remove-Item -Recurse -Force -LiteralPath $link }
  }
  $cogSrc = Join-Path $genRoot "cognitive-skills"
  if (Test-Path -LiteralPath $cogSrc) {
    $cogDst = Join-Path $Dest "cognitive-skills"
    if (Test-Path -LiteralPath $cogDst) { Remove-Item -Recurse -Force -LiteralPath $cogDst }
    Copy-Item -Recurse -Force -LiteralPath $cogSrc -Destination $cogDst
  }
} else {
  foreach ($name in $cognitiveSkills) {
    $target = Join-Path $Dest "skills\$name"
    if (-not (Test-Path -LiteralPath $target)) {
      throw "generated skill missing: $target (compose/copy failed)"
    }
    $link = Join-Path $Skills $name
    if (Test-Path -LiteralPath $link) { Remove-Item -Recurse -Force -LiteralPath $link }
    try {
      New-Item -ItemType Junction -Path $link -Target $target -ErrorAction Stop | Out-Null
    } catch {
      Copy-Item -Recurse -Force -LiteralPath $target -Destination $link
    }
    if (-not (Test-Path -LiteralPath $link)) {
      throw "failed to install skill $name → $link"
    }
  }
}

$agentDir = Join-Path $Dest "agents"
if (-not (Test-Path $agentDir)) {
  throw "generated agents missing under $agentDir (compose may have failed)"
}
# OpenCode treats every .md under agents/ as a Tab entry.
$agentFiles = @(Get-ChildItem -Path $agentDir -Filter "*.md" -File | Where-Object {
  $_.Name -ne "README.md" -and $_.Name -notmatch '(?i)^readme'
})
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
    Copy-Item -Force -LiteralPath $agentFile.FullName -Destination $link
  }
  if (-not (Test-Path -LiteralPath $link)) {
    throw "failed to install agent $($agentFile.Name) → $link"
  }
}

if ($Platform -eq "opencode") {
  $plugins = Get-PluginsDest "opencode"
  New-Item -ItemType Directory -Force -Path $plugins | Out-Null
  $pluginSrc = Join-Path $BundleRoot "opencode-plugin\ascendc-pilot.ts"
  if (Test-Path $pluginSrc) {
    Copy-Item -Force $pluginSrc (Join-Path $plugins "ascendc-pilot.ts")
    Write-Host "Installed plugin → $plugins\ascendc-pilot.ts"
  }
  Write-Host "Primary agent → $Agents\ascendc-pilot.md (Tab 切换；未改 opencode.json)"
}

$stampDir = Join-Path $Dest "templates\$Platform"
New-Item -ItemType Directory -Force -Path $stampDir | Out-Null
Set-Content -Path (Join-Path $stampDir "install_stamp.txt") -Value "plugin_root=$Dest"
Write-Host "Installed AscendC-Pilot → $Dest"
Write-Host "Run: acp doctor"

# optional native walker (best-effort)
$uoWalkSrc = Join-Path $Dest "engines\understand-operator\native\uo_walk"
$uoWalkBuild = Join-Path $uoWalkSrc "build"
if (Get-Command cmake -ErrorAction SilentlyContinue) {
  New-Item -ItemType Directory -Force -Path $uoWalkBuild | Out-Null
  cmake -S $uoWalkSrc -B $uoWalkBuild
  if ($LASTEXITCODE -eq 0) {
    cmake --build $uoWalkBuild
    if ($LASTEXITCODE -eq 0) {
      Write-Host "Built optional uo_walk → $uoWalkBuild"
    } else {
      Write-Host "uo_walk optional build skipped"
    }
  } else {
    Write-Host "uo_walk optional build skipped"
  }
}
