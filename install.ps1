# AscendC-Pilot unified installer (Windows)
#
# Usage:
#   .\install.ps1 opencode|cursor|codex
#   .\install.ps1 cbm
#   .\install.ps1 uninstall-opencode
#   $env:SKIP_PIP=1; .\install.ps1 cursor
param(
  [Parameter(Position = 0)]
  [string]$Platform = "opencode"
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkipPip = $env:SKIP_PIP

function Install-CbmMcp {
  # Download upstream installer to TEMP - never overwrite this repo's install.ps1.
  $uri = "https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.ps1"
  $cbmScript = Join-Path $env:TEMP "ascendc-pilot-cbm-install.ps1"
  Write-Host "Downloading CBM installer → $cbmScript"
  Invoke-WebRequest -Uri $uri -OutFile $cbmScript
  Unblock-File -LiteralPath $cbmScript -ErrorAction SilentlyContinue
  Write-Host "Running upstream CBM installer..."
  $proc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $cbmScript) `
    -Wait -PassThru -NoNewWindow
  if ($proc.ExitCode -ne 0) {
    throw "CBM upstream installer failed with exit $($proc.ExitCode)"
  }
  Write-Host ""
  Write-Host "CBM binary install finished. Verify:"
  Write-Host "  codebase-memory-mcp --help"
  Write-Host "  opencode mcp list"
  Write-Host "Check MCP config: $env:USERPROFILE\.config\opencode\opencode.json"
  Write-Host "See: docs\cbm-mcp-setup.md"
}

if ($Platform -eq "cbm") {
  Install-CbmMcp
  exit 0
}

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
  # Pre-pilot ascendc-agent leftovers (show up as Tab agents / wrong harness).
  foreach ($name in @("uo-code-review", "understand-operator", "uo-diff")) {
    $p = Join-Path $skills $name
    if (Test-Path -LiteralPath $p) {
      Remove-Item -Recurse -Force -LiteralPath $p
      Write-Host "Removed legacy skill → $p"
    }
  }
  foreach ($name in @("ascendc-agent", "uo-code-reviewer", "README")) {
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
  foreach ($name in @("uo-init","uo-update","uo-query","ce-review","tg-init","tg-plan","tg-solve","operator","_policies","understand-operator","uo-diff","uo-code-review")) {
    $p = Join-Path $skills $name
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  foreach ($name in @("ascendc-pilot","ascendc-agent","uo-semantic-resolve","uo-key-resolve","uo-confidence-review","uo-kb-review","ce-reviewer","uo-query","uo-code-reviewer","tg-csv-contract","tg-semantic-bind","tg-init-audit","deterministic-uo-engine","deterministic-tg-engine","README")) {
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
  python -m pip install -e "$BundleRoot\engines\common" `
    -e "$BundleRoot\pilot" `
    -e "$BundleRoot\engines\understand-operator" `
    -e "$BundleRoot\engines\testcase-generation[solver,ml]" `
    -e "$BundleRoot\engines\code-engineering"
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
foreach ($name in @("skills","prompts","agents","docs","pilot","templates","scripts","opencode-plugin")) {
  $src = Join-Path $BundleRoot $name
  if (Test-Path $src) {
    Copy-Item -Recurse -Force $src (Join-Path $Dest $name)
  }
}
# Engines: only packages still installed / required (no understand-operator-old / codebase-memory-mcp)
$enginesDest = Join-Path $Dest "engines"
New-Item -ItemType Directory -Force -Path $enginesDest | Out-Null
foreach ($eng in @("common","understand-operator","testcase-generation","code-engineering")) {
  $src = Join-Path $BundleRoot "engines\$eng"
  if (Test-Path $src) {
    Copy-Item -Recurse -Force $src (Join-Path $enginesDest $eng)
  }
}

# Install ONLY generated runtime trees.
# Windows Copy-Item nests (dest/skills/skills) when dest already exists from the
# source bundle above — remove first so generated becomes runtime authority.
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

# Purge pre-pilot leftovers (wrong Tab agents / free-form LLM KB skills).
Remove-LegacyAscendcAgentBits -plat $Platform -skills $Skills -agents $Agents -plugins (Get-PluginsDest $Platform)

foreach ($name in @("uo-init","uo-update","uo-query","ce-review","tg-init","tg-plan","tg-solve","operator")) {
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

$agentDir = Join-Path $Dest "agents"
if (-not (Test-Path $agentDir)) {
  throw "generated agents missing under $agentDir (compose may have failed)"
}
# OpenCode treats every .md under agents/ as a Tab entry — never install README.md etc.
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