# AscendC-Pilot unified installer (Windows)
#
# Usage:
#   .\install.ps1 opencode|cursor|codex
#   .\install.ps1 uninstall-opencode
#   .\uninstall.ps1 opencode
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

function Get-OpenCodeHome {
  $xdg = [string]$env:XDG_CONFIG_HOME
  if (-not [string]::IsNullOrWhiteSpace($xdg)) {
    return (Join-Path $xdg.Trim() "opencode")
  }
  return (Join-Path $HOME ".config\opencode")
}

# Compose slash workflows (pilot_run). `/uo-query` is a Command + Action Skill, not a workflow shell.
$workflowSkills = @("uo-init","uo-update","uo-investigate","ce-review","ce-plan","ce-apply","handoff","tg-init","tg-plan","tg-solve")
# Old installs left a workflow skill dir; unlink it. Uninstall still names it for cleanup.
$staleWorkflowSkills = @("uo-query","workflow-orchestration","operator")
# Action Skills are discovered from generated/<host>/cognitive-skills (or skills/) after compose.
# Uninstall still names the old five families so leftover installs are cleaned.
$legacyCognitiveSkills = @("operator-analysis","testcase-generation","source-proof","code-review","code-engineering")
$openCodeCommands = @("uo-init","uo-update","uo-query","uo-investigate","ce-review","ce-plan","ce-apply","handoff","tg-init","tg-plan","tg-solve")
$currentAgents = @("ascendc-pilot","uo-query","uo-heal-analyst","uo-gap-investigator","ce-reviewer","tg-analyst","ce-applier","ce-analyst")
$legacySkills = @("uo-code-review","understand-operator","uo-diff","_policies","ce-intent","ce-impact","ce-verify","ce-handoff","operator")
$legacyAgents = @("ascendc-agent","uo-semantic-resolve","uo-semantic-resolver","uo-gap-resolve","uo-key-resolve","uo-confidence-review","uo-kb-review","uo-code-reviewer","tg-csv-contract","tg-semantic-bind","tg-init-audit","tg-lemma-producer","tg-closure-referee","deterministic-uo-engine","deterministic-tg-engine","deterministic-ce-engine","ce-change-referee","README")
$legacyPlugins = @("ascendc-pilot.ts","zz-uo-query-return-value.ts","uo-query-return-value.ts","ascendc-harness.ts","pilot-driver.ts")

function Get-PythonScriptsDir {
  $dir = python -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>$null
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($dir)) { return $null }
  return ([string]$dir).Trim()
}

function Get-AcpExe {
  $cmd = Get-Command acp -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
    return $cmd.Source
  }
  $scripts = Get-PythonScriptsDir
  if ($scripts) {
    foreach ($name in @("acp.exe", "acp")) {
      $p = Join-Path $scripts $name
      if (Test-Path -LiteralPath $p) { return $p }
    }
  }
  $fromPy = python -c "import pathlib,sysconfig; p=pathlib.Path(sysconfig.get_path('scripts')); print(next((str(p/n) for n in ('acp.exe','acp') if (p/n).is_file()), ''))" 2>$null
  if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($fromPy)) {
    $fromPy = ([string]$fromPy).Trim()
    if (Test-Path -LiteralPath $fromPy) { return $fromPy }
  }
  return $null
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
    "opencode" { Join-Path (Get-OpenCodeHome) "ascendc-pilot-plugin" }
    "cursor" { Join-Path $HOME ".cursor\ascendc-pilot-plugin" }
    "codex" { Join-Path $HOME ".agents\ascendc-pilot-plugin" }
    default { throw "Unknown platform $plat" }
  }
}

function Get-InstallManifest([string]$Plat) {
  $candidates = @(
    (Join-Path (Get-PluginDest $Plat) "install-manifest.json"),
    (Join-Path $BundleRoot "generated\$Plat\install-manifest.json")
  )
  foreach ($p in $candidates) {
    if (Test-Path -LiteralPath $p) {
      try {
        return Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
      } catch {
        Write-Host "WARN: could not parse $p : $_"
      }
    }
  }
  return $null
}

function Convert-ManifestNameList($Raw) {
  $out = @()
  foreach ($n in @($Raw)) {
    if ($null -eq $n) { continue }
    $s = [string]$n
    if ([string]::IsNullOrWhiteSpace($s)) { continue }
    $out += $s
  }
  return $out
}

function Get-OwnedAgentFileNames($Manifest) {
  $names = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  if ($Manifest) {
    foreach ($n in (Convert-ManifestNameList $Manifest.agents)) {
      [void]$names.Add([IO.Path]::GetFileName($n))
    }
    foreach ($n in (Convert-ManifestNameList $Manifest.global_agents)) {
      [void]$names.Add([IO.Path]::GetFileName($n))
    }
    if ($Manifest.legacy) {
      foreach ($n in (Convert-ManifestNameList $Manifest.legacy.agents)) {
        [void]$names.Add([IO.Path]::GetFileName($n))
      }
    }
  } else {
    foreach ($n in ($currentAgents + $legacyAgents)) { [void]$names.Add("$n.md") }
  }
  $normalized = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  foreach ($n in $names) {
    if ($n -match '\.md$') { [void]$normalized.Add($n) } else { [void]$normalized.Add("$n.md") }
  }
  return $normalized
}

function Get-GlobalKeepAgentFileNames($Manifest) {
  $keep = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  if ($Manifest) {
    foreach ($n in (Convert-ManifestNameList $Manifest.global_agents)) {
      $leaf = [IO.Path]::GetFileName([string]$n)
      if ($leaf -notmatch '\.md$') { $leaf = "$leaf.md" }
      if ($leaf) { [void]$keep.Add($leaf) }
    }
  }
  if ($keep.Count -eq 0) { [void]$keep.Add("ascendc-pilot.md") }
  return $keep
}

function Remove-OwnedOpenCodeTabs([string]$AgentsDir, $Manifest) {
  # Delete only agents this install owns. Never glob tg-* / uo-* / ce-*.
  if ([string]::IsNullOrWhiteSpace($AgentsDir) -or -not (Test-Path -LiteralPath $AgentsDir)) { return }
  $owned = Get-OwnedAgentFileNames $Manifest
  $keep = Get-GlobalKeepAgentFileNames $Manifest
  Get-ChildItem -Path $AgentsDir -Filter "*.md" -File -ErrorAction SilentlyContinue | ForEach-Object {
    if ($keep.Contains($_.Name)) { return }
    if ($owned.Contains($_.Name)) {
      Remove-ReparseOrItem $_.FullName
      Write-Host "Removed leftover OpenCode Tab → $($_.FullName)"
    }
  }
}

function Get-SkillsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path (Get-OpenCodeHome) "skills" }
    "cursor" { Join-Path $HOME ".cursor\skills" }
    "codex" { Join-Path $HOME ".agents\skills" }
  }
}
function Get-AgentsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path (Get-OpenCodeHome) "agents" }
    "cursor" { Join-Path $HOME ".cursor\agents" }
    "codex" { Join-Path $HOME ".agents\agents" }
  }
}
function Get-CommandsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path (Get-OpenCodeHome) "commands" }
    default { $null }
  }
}
function Get-PluginsDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path (Get-OpenCodeHome) "plugins" }
    default { $null }
  }
}

function Invoke-CmdQuiet([string]$Line) {
  # Native stderr (e.g. rmdir of a missing path → "系统找不到指定的文件") becomes
  # NativeCommandError under $ErrorActionPreference=Stop, even with 2>$null.
  $prev = $ErrorActionPreference
  $native = $null
  if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $native = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
  }
  $ErrorActionPreference = "Continue"
  try {
    cmd /c $Line 2>$null | Out-Null
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prev
    if ($null -ne $native) {
      $PSNativeCommandUseErrorActionPreference = $native
    }
  }
}

function Remove-ReparseOrItem([string]$Path) {
  # Junction/symlink: rmdir/del the link only. Remove-Item -Recurse on a
  # junction can walk into the plugin dest and delete the real tree.
  # Dangling junctions often make Test-Path return false, so always try rmdir.
  if ([string]::IsNullOrWhiteSpace($Path)) { return }
  Invoke-CmdQuiet "rmdir `"$Path`"" | Out-Null
  if (Test-Path -LiteralPath $Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
      Invoke-CmdQuiet "del /f `"$Path`"" | Out-Null
    }
  }
  if (Test-Path -LiteralPath $Path) {
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Install-DirLink([string]$Link, [string]$Target) {
  Remove-ReparseOrItem $Link
  Invoke-CmdQuiet "mklink /J `"$Link`" `"$Target`"" | Out-Null
  if (Test-Path -LiteralPath $Link) {
    $global:LASTEXITCODE = 0
    return
  }
  Write-Host "WARN: junction failed for $Link; copying instead"
  Remove-ReparseOrItem $Link
  Copy-Item -Recurse -Force -LiteralPath $Target -Destination $Link
  $global:LASTEXITCODE = 0
}

function Install-FileLink([string]$Link, [string]$Target) {
  Remove-ReparseOrItem $Link
  Invoke-CmdQuiet "mklink `"$Link`" `"$Target`"" | Out-Null
  if (Test-Path -LiteralPath $Link) {
    $global:LASTEXITCODE = 0
    return
  }
  Write-Host "WARN: symlink failed for $Link; copying instead"
  Remove-ReparseOrItem $Link
  Copy-Item -Force -LiteralPath $Target -Destination $Link
  $global:LASTEXITCODE = 0
}

function Write-CannHint {
  $local = Join-Path $BundleRoot "_cann\pkg"
  $user = [Environment]::GetEnvironmentVariable("UO_CANN_ROOT", "User")
  if (-not [string]::IsNullOrWhiteSpace($user) -and (Test-Path -LiteralPath $user)) {
    Write-Host "UO_CANN_ROOT (User) = $user"
    return
  }
  if (-not [string]::IsNullOrWhiteSpace($env:UO_CANN_ROOT) -and (Test-Path -LiteralPath $env:UO_CANN_ROOT)) {
    Write-Host "UO_CANN_ROOT (session) = $env:UO_CANN_ROOT"
    Write-Host "This is lost when the terminal closes. Persist with:"
    Write-Host "  [Environment]::SetEnvironmentVariable('UO_CANN_ROOT', '$($env:UO_CANN_ROOT)', 'User')"
    return
  }
  if ((Test-Path -LiteralPath (Join-Path $local "cann-asc-devkit")) -or (Test-Path -LiteralPath (Join-Path $local "cann-metadef"))) {
    Write-Host "CANN headers auto-discovered at $local (no env var needed)"
    return
  }
  Write-Host "WARN: CANN headers not found. Extract into the checkout so doctor can discover it:"
  Write-Host "  python `"$BundleRoot\scripts\cann_extract.py`" <toolkit.run> --dest `"$local`""
  Write-Host "  python `"$BundleRoot\scripts\cann_extract.py`" --fixup --dest `"$local`""
  Write-Host "If already extracted elsewhere, persist (session `$env: is not enough):"
  Write-Host "  [Environment]::SetEnvironmentVariable('UO_CANN_ROOT', '<abs-pkg>', 'User')"
}

function Remove-LegacyAscendcAgentBits([string]$plat, [string]$skills, [string]$agents, [string]$plugins) {
  # Remove previous or deterministic-only entries that would otherwise appear
  # as selectable OpenCode/Cursor agents after an upgrade.
  foreach ($name in $legacySkills) {
    $p = Join-Path $skills $name
    if (Test-Path -LiteralPath $p) {
      Remove-ReparseOrItem $p
      Write-Host "Removed legacy skill → $p"
    }
  }
  foreach ($name in $legacyAgents) {
    $file = if ($name -like "*.md") { $name } else { "$name.md" }
    $p = Join-Path $agents $file
    if (Test-Path -LiteralPath $p) {
      Remove-ReparseOrItem $p
      Write-Host "Removed legacy agent → $p"
    }
  }
  if ($plat -eq "opencode") {
    Remove-OwnedOpenCodeTabs $agents (Get-InstallManifest $plat)
    $legacyPlug = Join-Path (Get-OpenCodeHome) "ascendc-agent-plugin"
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
  $un = Join-Path $BundleRoot "uninstall.ps1"
  if (-not (Test-Path -LiteralPath $un)) { throw "Missing uninstall.ps1 at $un" }
  & $un $plat
  exit $LASTEXITCODE
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
$manSrc = Join-Path $genRoot "install-manifest.json"
if (Test-Path -LiteralPath $manSrc) {
  Copy-Item -Force -LiteralPath $manSrc -Destination (Join-Path $Dest "install-manifest.json")
}

# Purge leftovers from earlier installs before linking the current closure.
Remove-LegacyAscendcAgentBits -plat $Platform -skills $Skills -agents $Agents -plugins (Get-PluginsDest $Platform)

foreach ($name in $workflowSkills) {
  $target = Join-Path $Dest "skills\$name"
  if (-not (Test-Path -LiteralPath $target)) {
    throw "generated skill missing: $target (compose/copy failed)"
  }
  $link = Join-Path $Skills $name
  if ($Platform -eq "opencode") {
    # Keep workflow skills plugin-internal. Linking into ~/.config/opencode/skills
    # puts them on Build/Plan available_skills.
    Remove-ReparseOrItem $link
    continue
  }
  Install-DirLink $link $target
  if (-not (Test-Path -LiteralPath $link)) {
    throw "failed to install skill $name → $link"
  }
}
foreach ($name in $staleWorkflowSkills) {
  Remove-ReparseOrItem (Join-Path $Skills $name)
}

if ($Platform -eq "opencode") {
  foreach ($name in $legacyCognitiveSkills) {
    Remove-ReparseOrItem (Join-Path $Skills $name)
  }
  $cogSrc = Join-Path $genRoot "cognitive-skills"
  if (Test-Path -LiteralPath $cogSrc) {
    $cogDst = Join-Path $Dest "cognitive-skills"
    if (Test-Path -LiteralPath $cogDst) { Remove-Item -Recurse -Force -LiteralPath $cogDst }
    Copy-Item -Recurse -Force -LiteralPath $cogSrc -Destination $cogDst
    Get-ChildItem -LiteralPath $cogSrc -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      Remove-ReparseOrItem (Join-Path $Skills $_.Name)
    }
  }
} else {
  $skillRoot = Join-Path $Dest "skills"
  $cognitiveNames = @()
  if (Test-Path -LiteralPath $skillRoot) {
    $cognitiveNames = @(
      Get-ChildItem -LiteralPath $skillRoot -Directory |
        Where-Object { $workflowSkills -notcontains $_.Name -and $_.Name -notin @("_policies","_shared") } |
        ForEach-Object { $_.Name }
    )
  }
  foreach ($name in $cognitiveNames) {
    $target = Join-Path $Dest "skills\$name"
    if (-not (Test-Path -LiteralPath $target)) {
      throw "generated skill missing: $target (compose/copy failed)"
    }
    $link = Join-Path $Skills $name
    Install-DirLink $link $target
    if (-not (Test-Path -LiteralPath $link)) {
      throw "failed to install skill $name → $link"
    }
  }
}

Remove-ReparseOrItem (Join-Path $Skills "_shared")

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
if ($Platform -eq "opencode") {
  $primarySrc = Join-Path $agentDir "ascendc-pilot.md"
  if (-not (Test-Path -LiteralPath $primarySrc)) {
    throw "generated ascendc-pilot.md missing under $agentDir"
  }
  $primaryLink = Join-Path $Agents "ascendc-pilot.md"
  Install-FileLink $primaryLink $primarySrc
  if (-not (Test-Path -LiteralPath $primaryLink)) {
    throw "failed to install agent ascendc-pilot.md → $primaryLink"
  }
  Remove-OwnedOpenCodeTabs $Agents (Get-InstallManifest $Platform)
} else {
  foreach ($agentFile in $agentFiles) {
    $link = Join-Path $Agents $agentFile.Name
    if (-not $link) { throw "Agents dest unresolved: Agents=$Agents" }
    Install-FileLink $link $agentFile.FullName
    if (-not (Test-Path -LiteralPath $link)) {
      throw "failed to install agent $($agentFile.Name) → $link"
    }
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
    Write-Host "WARN: no rg.exe to seed; Pilot after-hook still loads plugin-internal SKILL.md without rg"
  }
  $commandSrc = Join-Path $Dest "commands"
  if (Test-Path -LiteralPath $commandSrc) {
    Get-ChildItem -Path $commandSrc -Filter "*.md" -File | ForEach-Object {
      Copy-Item -Force -LiteralPath $_.FullName -Destination (Join-Path $commands $_.Name)
    }
    Write-Host "Workflow commands → $commands\{uo-*,tg-*,ce-*}.md"
  }
  Write-Host "Primary agent → $Agents\ascendc-pilot.md (Tab: AscendC-Pilot；未改 opencode.json)"
}

$stampDir = Join-Path $Dest "templates\$Platform"
New-Item -ItemType Directory -Force -Path $stampDir | Out-Null
Set-Content -Path (Join-Path $stampDir "install_stamp.txt") -Value "plugin_root=$Dest"

# Cache absolute acp path for OpenCode plugin (Node often has a thinner PATH).
$acpExe = Get-AcpExe
$cacheDir = Get-OpenCodeHome
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
if ($acpExe) {
  $cacheFile = Join-Path $cacheDir "ascendc-harness-bin"
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($cacheFile, ($acpExe.Trim() + "`n"), $utf8)
  Write-Host "Cached acp bin → $acpExe"
} else {
  Write-Host "WARN: acp not on PATH after pip install; OpenCode may fail to find harness"
}

$cannCandidates = @()
$userCann = [Environment]::GetEnvironmentVariable("UO_CANN_ROOT", "User")
if (-not [string]::IsNullOrWhiteSpace($userCann)) { $cannCandidates += $userCann }
if (-not [string]::IsNullOrWhiteSpace($env:UO_CANN_ROOT)) { $cannCandidates += $env:UO_CANN_ROOT }
$cannCandidates += (Join-Path $BundleRoot "_cann\pkg")
foreach ($cand in $cannCandidates) {
  if (-not $cand) { continue }
  if ((Test-Path -LiteralPath (Join-Path $cand "cann-asc-devkit")) -or (Test-Path -LiteralPath (Join-Path $cand "cann-metadef"))) {
    $cannCache = Join-Path $cacheDir "ascendc-cann-root"
    $resolved = (Resolve-Path -LiteralPath $cand).Path.Trim()
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($cannCache, ($resolved + "`n"), $utf8)
    Write-Host "Cached CANN root → $resolved"
    break
  }
}

Write-Host "Installed AscendC-Pilot → $Dest"
Write-CannHint
if ($Platform -eq "opencode") {
  Write-Host "Run: python -m ascendc_pilot doctor --host opencode"
} else {
  Write-Host "Run: python -m ascendc_pilot doctor"
}
Write-Host "Keep this checkout; pip -e installs point at it. Fully quit and reopen the Host."

# cmd/mklink often leaves LASTEXITCODE=1/2 after a swallowed fallback copy.
# Without an explicit success exit, refresh-opencode.ps1 treats install as failed.
exit 0