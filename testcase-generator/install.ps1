<#
.SYNOPSIS
  Install testcase-generator skills for OpenCode / Codex / Cursor.

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
$SkillsRoot = Join-Path $RepoRoot "testcase-generator-plugin\skills"

$SkillNames = @(
    "tg-init",
    "tg-plan",
    "tg-generate",
    "tg-probe",
    "tg-audit",
    "tg-repair",
    "tg-pr",
    "testcase-generator"
)

$Targets = @{
    opencode = Join-Path $HOME ".config\opencode\skills"
    codex    = Join-Path $HOME ".agents\skills"
    cursor   = Join-Path $HOME ".cursor\skills"
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

Write-Host ""
Write-Host "Commands: /tg-init  /tg-plan  /tg-generate  /tg-probe  /tg-audit  /tg-repair  /tg-pr"
Write-Host "Shared scripts: $(Join-Path $TargetRoot 'testcase-generator')"
Write-Host "For Cursor: add the repository root as a local plugin, or rely on the installed skill links."
