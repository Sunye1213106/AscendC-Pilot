<#
.SYNOPSIS
  Install understand-operator skill for OpenCode / Codex / compatible agents.

.EXAMPLE
  ./install.ps1 opencode
  ./install.ps1 -Uninstall opencode
#>

param(
    [Parameter(Position = 0)]
    [string]$Platform = "opencode",
    [string]$Uninstall
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillSrc = Join-Path $RepoRoot "understand-operator-plugin\\skills\\understand-operator"
$AgentsSrc = Join-Path $RepoRoot "understand-operator-plugin\\agents"

$Targets = @{
    opencode = Join-Path $HOME ".agents\skills"
    codex    = Join-Path $HOME ".agents\skills"
    cursor   = Join-Path $HOME ".cursor\skills"
}

$AgentTargets = @{
    cursor = Join-Path $HOME ".cursor\agents"
}

if (-not $Targets.ContainsKey($Platform)) {
    Write-Error "Unknown platform: $Platform. Supported: $($Targets.Keys -join ', ')"
}

$SkillDest = Join-Path $Targets[$Platform] "understand-operator"
if ($Uninstall) {
    if (Test-Path $SkillDest) { Remove-Item $SkillDest -Recurse -Force }
    Write-Host "Removed skill link: $SkillDest"
    exit 0
}

New-Item -ItemType Directory -Force -Path $Targets[$Platform] | Out-Null

if (Test-Path $SkillDest) { Remove-Item $SkillDest -Recurse -Force }
New-Item -ItemType Junction -Path $SkillDest -Target $SkillSrc | Out-Null

if ($Platform -eq "cursor" -and (Test-Path $AgentsSrc)) {
    $AgentsDestRoot = $AgentTargets[$Platform]
    New-Item -ItemType Directory -Force -Path $AgentsDestRoot | Out-Null
    Get-ChildItem $AgentsDestRoot -Filter "uo-*.md" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem $AgentsSrc -Filter "uo-*.md" | ForEach-Object {
        $agentDest = Join-Path $AgentsDestRoot $_.Name
        Copy-Item -Path $_.FullName -Destination $agentDest -Force
    }
}

Write-Host "Installed understand-operator skill:"
Write-Host "  $SkillDest -> $SkillSrc"
if ($Platform -eq "cursor") {
    Write-Host "Installed understand-operator subagents:"
    Write-Host "  $AgentsDestRoot\uo-*.md (copied from $AgentsSrc)"
}
Write-Host ""
Write-Host "For Cursor: add the repository root as a local plugin, or rely on the installed ~/.cursor/agents links."
