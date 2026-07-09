<#
.SYNOPSIS
  Install understand-operator skills for OpenCode / Codex / Cursor.

.EXAMPLE
  ./install.ps1 cursor
  ./install.ps1 -Uninstall cursor
#>

param(
    [Parameter(Position = 0)]
    [string]$Platform = "opencode",
    [string]$Uninstall
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillsRoot = Join-Path $RepoRoot "understand-operator-plugin\\skills"
$AgentsSrc = Join-Path $RepoRoot "understand-operator-plugin\\agents"

$SkillNames = @(
    "uo-init",
    "uo-query",
    "uo-update",
    "uo-diff",
    "understand-operator"
)

$Targets = @{
    # OpenCode primary global skills dir (also discovers ~/.agents/skills)
    opencode = Join-Path $HOME ".config\opencode\skills"
    codex    = Join-Path $HOME ".agents\skills"
    cursor   = Join-Path $HOME ".cursor\skills"
}

$AgentTargets = @{
    cursor = Join-Path $HOME ".cursor\agents"
}

if (-not $Targets.ContainsKey($Platform)) {
    Write-Error "Unknown platform: $Platform. Supported: $($Targets.Keys -join ', ')"
}

$TargetRoot = $Targets[$Platform]

if ($Uninstall) {
    foreach ($name in $SkillNames) {
        $dest = Join-Path $TargetRoot $name
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Write-Host "Removed skill link: $dest"
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

foreach ($name in $SkillNames) {
    $src = Join-Path $SkillsRoot $name
    if (-not (Test-Path $src)) {
        Write-Error "Missing skill source: $src"
    }
    $dest = Join-Path $TargetRoot $name
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Junction -Path $dest -Target $src | Out-Null
    Write-Host "Installed skill: $dest -> $src"
}

if ($Platform -eq "cursor" -and (Test-Path $AgentsSrc)) {
    $AgentsDestRoot = $AgentTargets[$Platform]
    New-Item -ItemType Directory -Force -Path $AgentsDestRoot | Out-Null
    Get-ChildItem $AgentsDestRoot -Filter "uo-*.md" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem $AgentsSrc -Filter "uo-*.md" | ForEach-Object {
        $agentDest = Join-Path $AgentsDestRoot $_.Name
        Copy-Item -Path $_.FullName -Destination $agentDest -Force
    }
    Write-Host "Installed subagents: $AgentsDestRoot\uo-*.md"
}

Write-Host ""
Write-Host "Commands: /uo-init  /uo-query  /uo-update  /uo-diff"
Write-Host "For Cursor: add the repository root as a local plugin, or rely on the installed skill links."
