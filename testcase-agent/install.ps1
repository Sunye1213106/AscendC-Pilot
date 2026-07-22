<#
.SYNOPSIS
  Install testcase-agent skills for OpenCode / Codex / Cursor.

.EXAMPLE
  ./install.ps1 opencode
  ./install.ps1 -Uninstall opencode
#>

param(
    [Parameter(Position = 0)]
    [string]$Platform = "opencode",
    [string]$Uninstall,
    [switch]$SkipPip
)

$ErrorActionPreference = 'Stop'
# Repo root IS the plugin root.
$PluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillsRoot = Join-Path $PluginRoot "skills"
$AgentsSrc = Join-Path $PluginRoot "agents"
$PackageDir = $PluginRoot

$SkillNames = @(
    "tg-init",
    "tg-plan",
    "tg-solve"
)
# Retired user skills: remove stale links on install/uninstall
$RetiredSkillNames = @(
    "tg-contract",
    "tg-domain-review"
)

$Targets = @{
    opencode = Join-Path $HOME ".config\opencode\skills"
    codex    = Join-Path $HOME ".agents\skills"
    cursor   = Join-Path $HOME ".cursor\skills"
}

$AgentTargets = @{
    opencode = Join-Path $HOME ".config\opencode\agents"
    cursor   = Join-Path $HOME ".cursor\agents"
}

$RequiredAgents = @(
    "tg-csv-contract",
    "tg-init-audit"
)

if (-not $Targets.ContainsKey($Platform)) {
    Write-Error "Unknown platform: $Platform. Supported: $($Targets.Keys -join ', ')"
}

$TargetRoot = $Targets[$Platform]

$PluginLinks = @{
    opencode = Join-Path (Split-Path $TargetRoot -Parent) "testcase-agent-plugin"
    codex    = Join-Path (Split-Path $TargetRoot -Parent) "testcase-agent-plugin"
    cursor   = Join-Path (Split-Path $TargetRoot -Parent) "testcase-agent-plugin"
}

if ($Uninstall) {
    foreach ($name in ($SkillNames + $RetiredSkillNames)) {
        $dest = Join-Path $TargetRoot $name
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
            if (Test-Path -LiteralPath $dest) {
                throw "Cleanup failed: $dest still exists"
            }
        }
        Write-Host "Removed skill link: $dest"
    }
    if ($PluginLinks.ContainsKey($Platform)) {
        $pluginDest = $PluginLinks[$Platform]
        if (Test-Path -LiteralPath $pluginDest) {
            Remove-Item -LiteralPath $pluginDest -Recurse -Force
            if (Test-Path -LiteralPath $pluginDest) {
                throw "Cleanup failed: $pluginDest still exists"
            }
        }
        Write-Host "Removed plugin link: $pluginDest"
    }
    if ($AgentTargets.ContainsKey($Platform)) {
        $AgentsDestRoot = $AgentTargets[$Platform]
        if (Test-Path -LiteralPath $AgentsDestRoot) {
            Get-ChildItem $AgentsDestRoot -Filter "tg-*.md" -ErrorAction SilentlyContinue | Remove-Item -Force
            Write-Host "Removed subagents: $AgentsDestRoot\tg-*.md"
        }
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

foreach ($name in $RetiredSkillNames) {
    $dest = Join-Path $TargetRoot $name
    if (Test-Path -LiteralPath $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
        if (Test-Path -LiteralPath $dest) {
            throw "Cleanup failed: $dest still exists"
        }
        Write-Host "Removed retired skill link: $dest"
    }
}

foreach ($name in $SkillNames) {
    $src = Join-Path $SkillsRoot $name
    if (-not (Test-Path $src)) {
        Write-Error "Missing skill source: $src"
    }
    $dest = Join-Path $TargetRoot $name
    if (Test-Path -LiteralPath $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
        if (Test-Path -LiteralPath $dest) {
            throw "Cleanup failed: $dest still exists"
        }
    }
    New-Item -ItemType Junction -Path $dest -Target $src | Out-Null
    Write-Host "Installed skill: $dest -> $src"
}

if ($PluginLinks.ContainsKey($Platform) -and (Test-Path $PluginRoot)) {
    $pluginDest = $PluginLinks[$Platform]
    if (Test-Path -LiteralPath $pluginDest) {
        Remove-Item -LiteralPath $pluginDest -Recurse -Force
        if (Test-Path -LiteralPath $pluginDest) {
            throw "Cleanup failed: $pluginDest still exists"
        }
    }
    New-Item -ItemType Junction -Path $pluginDest -Target $PluginRoot | Out-Null
    Write-Host "Installed plugin: $pluginDest -> $PluginRoot"
}

if ($AgentTargets.ContainsKey($Platform) -and (Test-Path $AgentsSrc)) {
    $AgentsDestRoot = $AgentTargets[$Platform]
    New-Item -ItemType Directory -Force -Path $AgentsDestRoot | Out-Null
    Get-ChildItem $AgentsDestRoot -Filter "tg-*.md" -ErrorAction SilentlyContinue | Remove-Item -Force
    foreach ($agent in $RequiredAgents) {
        $srcAgent = Join-Path $AgentsSrc "$agent.md"
        if (-not (Test-Path -LiteralPath $srcAgent)) {
            throw "REQUIRED_SUBAGENT_UNAVAILABLE: missing source $srcAgent"
        }
        $agentDest = Join-Path $AgentsDestRoot "$agent.md"
        Copy-Item -Path $srcAgent -Destination $agentDest -Force
    }
    Write-Host "Installed subagents (required only): $($RequiredAgents -join ', ')"
    foreach ($agent in $RequiredAgents) {
        $agentPath = Join-Path $AgentsDestRoot "$agent.md"
        if (-not (Test-Path -LiteralPath $agentPath)) {
            throw "REQUIRED_SUBAGENT_UNAVAILABLE: $agent was not installed at $agentPath"
        }
        $text = Get-Content -LiteralPath $agentPath -Raw -Encoding UTF8
        if ($text -notmatch "(?m)^name:\s*$([Regex]::Escape($agent))\s*$") {
            throw "REQUIRED_SUBAGENT_UNAVAILABLE: $agent missing matching frontmatter name"
        }
        if ($text -notmatch "(?m)^type:\s*subagent\s*$") {
            throw "REQUIRED_SUBAGENT_UNAVAILABLE: $agent missing frontmatter type: subagent"
        }
    }
    Write-Host "Verified named subagents discoverable: $($RequiredAgents -join ', ')"
}

if (-not $SkipPip) {
    Write-Host "Installing Python package (editable)..."
    python -m pip install -e "$PackageDir[solver]" -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "solver extra failed; falling back to base install..."
        python -m pip install -e "$PackageDir" -q
        if ($LASTEXITCODE -ne 0) {
            throw "pip install -e . failed"
        }
    }
    Write-Host "Python entrypoints: tg-init, tg-plan, tg-solve (tg-contract=compat CLI only)"
}

Write-Host ""
Write-Host "Commands: /tg-init  /tg-plan  /tg-solve"
if ($PluginLinks.ContainsKey($Platform)) {
    Write-Host "PLUGIN_ROOT: $($PluginLinks[$Platform])"
    Write-Host "Package: $(Join-Path $PluginLinks[$Platform] 'testcase_agent')"
}
Write-Host "Agents must NOT search C:\ for scripts; use PLUGIN_ROOT above."
if ($Platform -eq "opencode") {
    Write-Host "OpenCode human review: ensure opencode.json has `"permission`": { `"question`": `"allow`" }"
}
Write-Host "For Cursor: add this repository root as a local plugin, or rely on the installed skill links."
