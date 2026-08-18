# AscendC-Pilot uninstaller (Windows)
#
# Usage:
#   .\uninstall.ps1                 # OpenCode (default)
#   .\uninstall.ps1 opencode|cursor|codex
#
# Deletes only files listed in the installed install-manifest.json (or the
# explicit builtin fallback). Never globs tg-* / uo-* / ce-* in the user's
# ~/.config/opencode/agents.
param(
  [Parameter(Position = 0)]
  [string]$Platform = "opencode"
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $BundleRoot

if ($Platform -like "uninstall-*") {
  $Platform = $Platform.Substring("uninstall-".Length)
}
if ($Platform -notin @("opencode", "cursor", "codex")) {
  throw "Usage: .\uninstall.ps1 opencode|cursor|codex"
}

function Get-OpenCodeHome {
  $xdg = [string]$env:XDG_CONFIG_HOME
  if (-not [string]::IsNullOrWhiteSpace($xdg)) {
    return (Join-Path $xdg.Trim() "opencode")
  }
  return (Join-Path $HOME ".config\opencode")
}

function Get-PluginDest([string]$plat) {
  switch ($plat) {
    "opencode" { Join-Path (Get-OpenCodeHome) "ascendc-pilot-plugin" }
    "cursor" { Join-Path $HOME ".cursor\ascendc-pilot-plugin" }
    "codex" { Join-Path $HOME ".agents\ascendc-pilot-plugin" }
    default { throw "Unknown platform $plat" }
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

$workflowSkills = @("uo-init","uo-update","uo-query","uo-investigate","ce-review","ce-plan","ce-apply","handoff","tg-init","tg-plan","tg-solve")
$cognitiveSkills = @("operator-analysis","testcase-generation","source-proof","code-review","code-engineering")
$openCodeCommands = @("uo-init","uo-update","uo-query","uo-investigate","ce-review","ce-plan","ce-apply","handoff","tg-init","tg-plan","tg-solve")
$currentAgents = @("ascendc-pilot","uo-query","uo-heal-analyst","uo-gap-investigator","ce-reviewer","tg-analyst","ce-applier","ce-analyst")
$legacySkills = @("uo-code-review","understand-operator","uo-diff","_policies","ce-intent","ce-impact","ce-verify","ce-handoff","operator")
$legacyAgents = @("ascendc-agent","uo-semantic-resolve","uo-semantic-resolver","uo-gap-resolve","uo-key-resolve","uo-confidence-review","uo-kb-review","uo-code-reviewer","tg-csv-contract","tg-semantic-bind","tg-init-audit","tg-lemma-producer","tg-closure-referee","deterministic-uo-engine","deterministic-tg-engine","deterministic-ce-engine","ce-change-referee","README")
$legacyPlugins = @("ascendc-pilot.ts","zz-uo-query-return-value.ts","uo-query-return-value.ts","ascendc-harness.ts","pilot-driver.ts")

function Invoke-CmdQuiet([string]$Line) {
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

function Read-JsonFile([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    Write-Host "WARN: could not parse $Path : $_"
    return $null
  }
}

$dest = Get-PluginDest $Platform
$skills = Get-SkillsDest $Platform
$agents = Get-AgentsDest $Platform
$plugins = Get-PluginsDest $Platform
$commands = Get-CommandsDest $Platform

$manifest = Read-JsonFile (Join-Path $dest "install-manifest.json")
if (-not $manifest) {
  $manifest = Read-JsonFile (Join-Path $BundleRoot "generated\$Platform\install-manifest.json")
}

$skillNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$agentFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$commandFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$pluginFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$pluginTrees = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

if ($manifest) {
  foreach ($n in (Convert-ManifestNameList $manifest.skills)) { [void]$skillNames.Add($n) }
  foreach ($n in (Convert-ManifestNameList $manifest.cognitive_skills)) { [void]$skillNames.Add($n) }
  if ($manifest.legacy) {
    foreach ($n in (Convert-ManifestNameList $manifest.legacy.skills)) { [void]$skillNames.Add($n) }
    foreach ($n in (Convert-ManifestNameList $manifest.legacy.agents)) {
      $leaf = [IO.Path]::GetFileName([string]$n)
      if ($leaf -notmatch '\.md$') { $leaf = "$leaf.md" }
      [void]$agentFiles.Add($leaf)
    }
    foreach ($n in (Convert-ManifestNameList $manifest.legacy.plugins)) { [void]$pluginFiles.Add($n) }
    foreach ($n in (Convert-ManifestNameList $manifest.legacy.plugin_trees)) { [void]$pluginTrees.Add($n) }
  }
  foreach ($n in ((Convert-ManifestNameList $manifest.agents) + (Convert-ManifestNameList $manifest.global_agents))) {
    $leaf = [IO.Path]::GetFileName([string]$n)
    if ($leaf -notmatch '\.md$') { $leaf = "$leaf.md" }
    [void]$agentFiles.Add($leaf)
  }
  foreach ($n in (Convert-ManifestNameList $manifest.commands)) {
    $leaf = [IO.Path]::GetFileName([string]$n)
    if ($leaf -notmatch '\.md$') { $leaf = "$leaf.md" }
    [void]$commandFiles.Add($leaf)
  }
  foreach ($n in (Convert-ManifestNameList $manifest.plugins)) { [void]$pluginFiles.Add($n) }
} else {
  foreach ($n in ($workflowSkills + $legacySkills + $cognitiveSkills + @("_shared"))) { [void]$skillNames.Add($n) }
  foreach ($n in ($currentAgents + $legacyAgents)) { [void]$agentFiles.Add("$n.md") }
  foreach ($n in $openCodeCommands) { [void]$commandFiles.Add("$n.md") }
  foreach ($n in $legacyPlugins) { [void]$pluginFiles.Add($n) }
  [void]$pluginTrees.Add("ascendc-agent-plugin")
}
[void]$skillNames.Add("_shared")

Write-Host "Uninstalling AscendC-Pilot ($Platform) from owned manifest only"

foreach ($name in $skillNames) {
  Remove-ReparseOrItem (Join-Path $skills $name)
}
foreach ($name in $agentFiles) {
  Remove-ReparseOrItem (Join-Path $agents $name)
}
if ($Platform -eq "opencode") {
  if ($commands) {
    foreach ($name in $commandFiles) {
      $p = Join-Path $commands $name
      if (Test-Path -LiteralPath $p) { Remove-Item -Force -LiteralPath $p }
    }
  }
  if ($plugins) {
    foreach ($pluginName in $pluginFiles) {
      $pluginFile = Join-Path $plugins $pluginName
      if (Test-Path -LiteralPath $pluginFile) { Remove-Item -Force -LiteralPath $pluginFile }
    }
  }
  foreach ($tree in $pluginTrees) {
    $legacyPlug = Join-Path (Get-OpenCodeHome) $tree
    if (Test-Path -LiteralPath $legacyPlug) { Remove-Item -Recurse -Force -LiteralPath $legacyPlug }
  }
}
if (Test-Path -LiteralPath $dest) { Remove-Item -Recurse -Force -LiteralPath $dest }

Write-Host "Uninstalled $Platform"
exit 0
