# AscendC-Pilot unified installer (Windows)
#
# Usage:
#   .\install.ps1 opencode|cursor|codex
#   .\install.ps1 uninstall-opencode
#   $env:SKIP_PIP=1; .\install.ps1 cursor
#   $env:ASCENDC_FAST_INSTALL=1; $env:SKIP_PIP=1; .\install.ps1 opencode
param(
  [Parameter(Position = 0)]
  [string]$Platform = "opencode"
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkipPip = $env:SKIP_PIP
$FastInstall = $env:ASCENDC_FAST_INSTALL -eq "1"

function Get-PythonScriptsDir {
  $dir = python -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>$null
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($dir)) { return $null }
  return ([string]$dir).Trim()
}

function Stop-AcpConsoleScriptProcesses {
  $scripts = Get-PythonScriptsDir
  $targets = @()
  if ($scripts) {
    foreach ($name in @("acp.exe", "ascendc-pilot.exe")) {
      $targets += (Join-Path $scripts $name)
    }
  }
  $stopped = 0
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    $exe = $_.ExecutablePath
    if (-not $exe) { return }
    $hit = $false
    foreach ($t in $targets) {
      if ($t -and ($exe -ieq $t)) { $hit = $true; break }
    }
    if (-not $hit -and ($exe -match '[\\/](acp|ascendc-pilot)\.exe$')) { $hit = $true }
    if (-not $hit) { return }
    Write-Host ("  stopping PID {0} {1} (releases {2} for pip)" -f $_.ProcessId, $_.Name, $exe)
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    $stopped++
  }
  if ($stopped -gt 0) { Start-Sleep -Milliseconds 600 }
  return $stopped
}

function Unlock-AcpConsoleScripts {
  # Windows cannot overwrite a running console-script wrapper. OpenCode's
  # leftover `acp serve-authorize` holds E:\...\Scripts\acp.exe and pip then
  # dies with WinError 5. Stop the wrapper, then rename it so pip can write
  # a new one even if OpenCode immediately tries to respawn.
  $scripts = Get-PythonScriptsDir
  if (-not $scripts -or -not (Test-Path -LiteralPath $scripts)) { return }
  [void](Stop-AcpConsoleScriptProcesses)
  Get-ChildItem -LiteralPath $scripts -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(acp|ascendc-pilot)\.exe\.old-' } |
    ForEach-Object {
      try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop } catch { }
    }
  $purelib = python -c "import sysconfig; print(sysconfig.get_path('purelib'))" 2>$null
  if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($purelib)) {
    $purelib = ([string]$purelib).Trim()
    Get-ChildItem -LiteralPath $purelib -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match '^~scendc_pilot' } |
      ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop } catch { }
      }
  }
  $stamp = Get-Date -Format "yyyyMMddHHmmss"
  foreach ($name in @("acp.exe", "ascendc-pilot.exe")) {
    $p = Join-Path $scripts $name
    if (-not (Test-Path -LiteralPath $p)) { continue }
    $bak = "$p.old-$stamp"
    try {
      Move-Item -LiteralPath $p -Destination $bak -Force
      Write-Host "  moved $name → $(Split-Path $bak -Leaf) so pip can install a new wrapper"
    } catch {
      Write-Host "  WARN: could not move locked $name : $_"
    }
  }
}

function Invoke-PipRequirements {
  Unlock-AcpConsoleScripts
  $ErrorActionPreference = "Continue"
  $output = & python -m pip install -r "$BundleRoot\requirements.txt" 2>&1
  $code = $LASTEXITCODE
  $ErrorActionPreference = "Stop"
  $output | ForEach-Object { Write-Host $_ }
  if ($code -eq 0) { return }
  $text = ($output | Out-String)
  if ($text -match 'WinError 5|拒绝访问|Access is denied') {
    Write-Host "pip hit a locked console-script; unlocking and retrying..."
    Unlock-AcpConsoleScripts
    $ErrorActionPreference = "Continue"
    $output2 = & python -m pip install --upgrade --force-reinstall -r "$BundleRoot\requirements.txt" 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    $output2 | ForEach-Object { Write-Host $_ }
    if ($code -eq 0) { return }
  }
  throw "pip install failed"
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
function Get-CommandsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path $HOME ".config\opencode\commands" }
    default { $null }
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
  $commands = Get-CommandsDest $plat
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  foreach ($name in @("uo-init","uo-update","uo-query","uo-investigate","ce-review","tg-init","tg-plan","tg-solve","operator","_policies","understand-operator","uo-diff","uo-code-review")) {
    $p = Join-Path $skills $name
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  foreach ($name in @("ascendc-pilot","ascendc-agent","uo-semantic-resolve","uo-semantic-resolver","uo-gap-investigator","uo-gap-resolve","uo-key-resolve","uo-confidence-review","uo-kb-review","ce-reviewer","uo-query","uo-code-reviewer","tg-csv-contract","tg-semantic-bind","tg-init-audit","deterministic-uo-engine","deterministic-tg-engine","README")) {
    $p = Join-Path $agents "$name.md"
    if (Test-Path $p) { Remove-Item -Force $p }
  }
  if ($plat -eq "opencode") {
    if ($commands) {
      foreach ($name in @("uo-init","uo-update","uo-query","uo-investigate","ce-review","tg-init","tg-plan","tg-solve")) {
        $p = Join-Path $commands "$name.md"
        if (Test-Path -LiteralPath $p) { Remove-Item -Force -LiteralPath $p }
      }
    }
    if ($plugins) {
      foreach ($pluginName in @("ascendc-pilot.ts", "zz-uo-query-return-value.ts", "ascendc-harness.ts", "pilot-driver.ts")) {
        $pluginFile = Join-Path $plugins $pluginName
        if (Test-Path $pluginFile) { Remove-Item -Force $pluginFile }
      }
    }
    $legacyPlug = Join-Path $HOME ".config\opencode\ascendc-agent-plugin"
    if (Test-Path -LiteralPath $legacyPlug) { Remove-Item -Recurse -Force -LiteralPath $legacyPlug }
  }
  Write-Host "Uninstalled $plat"
  exit 0
}

if ($SkipPip -ne "1") {
  Invoke-PipRequirements
}

if (-not $FastInstall) {
  # Fail before Host composition if execution ownership is internally inconsistent.
  python "$BundleRoot\scripts\check_execution_contracts.py"
  if ($LASTEXITCODE -ne 0) { throw "execution contract audit failed" }
}

# Compose sources, then retain only model-reachable runtime context.
python "$BundleRoot\scripts\compose_runtime.py" --repo "$BundleRoot" --host $Platform
if ($LASTEXITCODE -ne 0) { throw "compose_runtime failed" }
python "$BundleRoot\scripts\prune_runtime_context.py" --repo "$BundleRoot" --host $Platform
if ($LASTEXITCODE -ne 0) { throw "prune_runtime_context failed" }
if ($Platform -eq "opencode") {
  python "$BundleRoot\scripts\compose_opencode_commands.py"
  if ($LASTEXITCODE -ne 0) { throw "compose_opencode_commands failed" }
}

$Dest = Get-PluginDest $Platform
$Skills = Get-SkillsDest $Platform
$Agents = Get-AgentsDest $Platform
New-Item -ItemType Directory -Force -Path $Dest, $Skills, $Agents | Out-Null

$bundleReady = (
  (Test-Path -LiteralPath (Join-Path $Dest "pilot")) -and
  (Test-Path -LiteralPath (Join-Path $Dest "scripts")) -and
  (Test-Path -LiteralPath (Join-Path $Dest "engines"))
)

function Copy-RuntimeBundle {
  if (Test-Path -LiteralPath $Dest) { Remove-Item -Recurse -Force -LiteralPath $Dest }
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  # Bundle runtime implementation only. Agent-facing skills/prompts/agents are
  # copied exclusively from generated/<host> below; docs/templates are not runtime context.
  foreach ($name in @("pilot","scripts","opencode-plugin")) {
    $src = Join-Path $BundleRoot $name
    if (Test-Path $src) {
      Copy-Item -Recurse -Force $src (Join-Path $Dest $name)
    }
  }
  $enginesDest = Join-Path $Dest "engines"
  New-Item -ItemType Directory -Force -Path $enginesDest | Out-Null
  foreach ($eng in @("common","understand-operator","testcase-generation","code-engineering")) {
    $src = Join-Path $BundleRoot "engines\$eng"
    if (Test-Path $src) {
      Copy-Item -Recurse -Force $src (Join-Path $enginesDest $eng)
    }
  }
}

if ($FastInstall -and $bundleReady) {
  Write-Host "fast install: reuse engines/pilot/scripts under $Dest"
  $pluginSrc = Join-Path $BundleRoot "opencode-plugin"
  if (Test-Path -LiteralPath $pluginSrc) {
    $pluginDst = Join-Path $Dest "opencode-plugin"
    if (Test-Path -LiteralPath $pluginDst) { Remove-Item -Recurse -Force -LiteralPath $pluginDst }
    Copy-Item -Recurse -Force -LiteralPath $pluginSrc -Destination $pluginDst
  }
} else {
  if ($FastInstall) {
    Write-Host "fast install: plugin dest incomplete, copying runtime bundle once"
  }
  Copy-RuntimeBundle
}

# Install ONLY generated runtime trees.
$genRoot = Join-Path $BundleRoot "generated\$Platform"
foreach ($name in @("skills", "agents", "prompts", "commands")) {
  $p = Join-Path $Dest $name
  if (Test-Path -LiteralPath $p) { Remove-Item -Recurse -Force -LiteralPath $p }
}
Copy-Item -Recurse -Force (Join-Path $genRoot "skills") (Join-Path $Dest "skills")
Copy-Item -Recurse -Force (Join-Path $genRoot "agents") (Join-Path $Dest "agents")
if (Test-Path (Join-Path $genRoot "prompts")) {
  Copy-Item -Recurse -Force (Join-Path $genRoot "prompts") (Join-Path $Dest "prompts")
}
if (Test-Path (Join-Path $genRoot "commands")) {
  Copy-Item -Recurse -Force (Join-Path $genRoot "commands") (Join-Path $Dest "commands")
}

# Purge leftovers from earlier installs before linking the current closure.
Remove-LegacyAscendcAgentBits -plat $Platform -skills $Skills -agents $Agents -plugins (Get-PluginsDest $Platform)

$workflowSkills = @("uo-init","uo-update","uo-query","uo-investigate","ce-review","ce-intent","ce-impact","ce-verify","tg-init","tg-plan","tg-solve","operator")
$cognitiveSkills = @("operator-analysis","testcase-generation","source-proof","code-review","code-engineering")

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

$legacyShared = Join-Path $Skills "_shared"
if (Test-Path -LiteralPath $legacyShared) { Remove-Item -Recurse -Force -LiteralPath $legacyShared }

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
  $commands = Get-CommandsDest "opencode"
  New-Item -ItemType Directory -Force -Path $plugins, $commands | Out-Null
  # OpenCode autoloads every *.ts in this directory as a plugin factory.
  # Copy only real plugins. pilot-driver.ts is a library loaded from
  # ascendc-pilot-plugin/opencode-plugin/ (already copied into $Dest above).
  foreach ($pluginName in @("ascendc-pilot.ts")) {
    $src = Join-Path $BundleRoot "opencode-plugin\$pluginName"
    Copy-Item -Force -LiteralPath $src -Destination (Join-Path $plugins $pluginName)
    Write-Host "Installed plugin → $plugins\$pluginName"
  }
  $legacyDriver = Join-Path $plugins "pilot-driver.ts"
  if (Test-Path -LiteralPath $legacyDriver) {
    Remove-Item -Force -LiteralPath $legacyDriver
    Write-Host "Removed autoloaded library → $legacyDriver"
  }
  foreach ($stalePlugin in @("zz-uo-query-return-value.ts", "uo-query-return-value.ts")) {
    $stalePath = Join-Path $plugins $stalePlugin
    if (Test-Path -LiteralPath $stalePath) {
      Remove-Item -Force -LiteralPath $stalePath
      Write-Host "Removed folded plugin leftover → $stalePath"
    }
  }
  # OpenCode 1.18 RipgrepBinary uses xdgCache/opencode/bin (Windows:
  # %LOCALAPPDATA%\opencode\bin), not ~/.local/share/opencode/bin.
  # Seed every candidate so skill/grep do not wait on GitHub zip.
  $exeName = "rg.exe"
  $rgSources = @(
    (Get-Command rg -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $HOME ".local\share\opencode\bin\$exeName"),
    "$env:LOCALAPPDATA\Programs\cursor\resources\app\node_modules\@vscode\ripgrep\bin\rg.exe",
    "$env:LOCALAPPDATA\Programs\Microsoft VS Code\resources\app\node_modules\@vscode\ripgrep\bin\rg.exe"
  )
  $rgSrc = $null
  foreach ($cand in $rgSources) {
    if ($cand -and (Test-Path -LiteralPath $cand)) { $rgSrc = $cand; break }
  }
  $ocBins = @(
    (Join-Path $HOME ".local\share\opencode\bin"),
    (Join-Path $HOME ".cache\opencode\bin"),
    (Join-Path $env:LOCALAPPDATA "opencode\bin")
  )
  $seeded = $false
  foreach ($ocBin in $ocBins) {
    $ocRg = Join-Path $ocBin $exeName
    if (Test-Path -LiteralPath $ocRg) { $seeded = $true; continue }
    if (-not $rgSrc) { continue }
    New-Item -ItemType Directory -Force -Path $ocBin | Out-Null
    Copy-Item -Force -LiteralPath $rgSrc -Destination $ocRg
    Write-Host "Seeded OpenCode rg → $ocRg"
    $seeded = $true
  }
  if (-not $seeded) {
    Write-Host "WARN: no rg.exe to seed; plugin skill tool still loads SKILL.md without rg"
  }
  $commandSrc = Join-Path $Dest "commands"
  if (Test-Path -LiteralPath $commandSrc) {
    Get-ChildItem -Path $commandSrc -Filter "*.md" -File | ForEach-Object {
      Copy-Item -Force -LiteralPath $_.FullName -Destination (Join-Path $commands $_.Name)
    }
    Write-Host "Workflow commands → $commands\{uo-*,tg-*,ce-review}.md"
  }
  Write-Host "Primary agent → $Agents\ascendc-pilot.md (Tab 切换；未改 opencode.json)"
}

$stampDir = Join-Path $Dest "templates\$Platform"
New-Item -ItemType Directory -Force -Path $stampDir | Out-Null
Set-Content -Path (Join-Path $stampDir "install_stamp.txt") -Value "plugin_root=$Dest"

# Cache absolute acp path for OpenCode plugin (Node often has a thinner PATH).
$acpCmd = Get-Command acp -ErrorAction SilentlyContinue
if ($acpCmd -and $acpCmd.Source) {
  $cacheDir = Join-Path $HOME ".config\opencode"
  New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
  Set-Content -Path (Join-Path $cacheDir "ascendc-harness-bin") -Value $acpCmd.Source -Encoding utf8
  Write-Host "Cached acp bin → $($acpCmd.Source)"
} else {
  Write-Host "WARN: acp not on PATH after pip install; OpenCode may fail to find harness"
}

Write-Host "Installed AscendC-Pilot → $Dest"
Write-Host "Run: acp doctor"

# optional native walker (best-effort). Skip on fast refresh; Python path is enough.
if (-not $FastInstall) {
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
}