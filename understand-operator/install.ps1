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
$PluginRoot = Join-Path $RepoRoot "understand-operator-plugin"
$SkillsRoot = Join-Path $PluginRoot "skills"
$AgentsSrc = Join-Path $PluginRoot "agents"
$PromptsSrc = Join-Path $PluginRoot "prompts"

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
    opencode = Join-Path $HOME ".config\opencode\agents"
    cursor   = Join-Path $HOME ".cursor\agents"
}

$RequiredAgents = @(
    "uo-boundary-agent",
    "uo-host-extraction",
    "uo-flow-extraction",
    "uo-kernel-overview-agent",
    "uo-kernel-slice-planner",
    "uo-kernel-slice-agent",
    "uo-step2-fact-review-agent",
    "uo-step3-fact-review-agent",
    "uo-behavior-abstraction-agent",
    "uo-graph-review-agent"
)

if (-not $Targets.ContainsKey($Platform)) {
    Write-Error "Unknown platform: $Platform. Supported: $($Targets.Keys -join ', ')"
}

$TargetRoot = $Targets[$Platform]

$PluginLinks = @{
    opencode = Join-Path (Split-Path $TargetRoot -Parent) "understand-operator-plugin"
    codex    = Join-Path (Split-Path $TargetRoot -Parent) "understand-operator-plugin"
    cursor   = Join-Path (Split-Path $TargetRoot -Parent) "understand-operator-plugin"
}

if ($Uninstall) {
    foreach ($name in $SkillNames) {
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
            Get-ChildItem $AgentsDestRoot -Filter "uo-*.md" -ErrorAction SilentlyContinue | Remove-Item -Force
            Write-Host "Removed subagents: $AgentsDestRoot\uo-*.md"
        }
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
    if (Test-Path -LiteralPath $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
        if (Test-Path -LiteralPath $dest) {
            throw "Cleanup failed: $dest still exists"
        }
    }
    New-Item -ItemType Junction -Path $dest -Target $src | Out-Null
    Write-Host "Installed skill: $dest -> $src"
}

# Prompts + agents live under plugin root; agents need them for human-review UX (question UI).
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
    Get-ChildItem $AgentsDestRoot -Filter "uo-*.md" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem $AgentsSrc -Filter "uo-*.md" | ForEach-Object {
        $agentDest = Join-Path $AgentsDestRoot $_.Name
        Copy-Item -Path $_.FullName -Destination $agentDest -Force
    }
    Write-Host "Installed subagents: $AgentsDestRoot\uo-*.md"
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
        if ($text -match "(?m)^model:\s*inherit\s*$") {
            throw "REQUIRED_SUBAGENT_UNAVAILABLE: $agent must omit model: inherit"
        }
    }
    Write-Host "Verified named subagents discoverable: $($RequiredAgents -join ', ')"
}

Write-Host ""
Write-Host "Commands: /uo-init  /uo-query  /uo-update  /uo-diff"
Write-Host "Shared scripts: $(Join-Path $TargetRoot 'understand-operator')\prepare_operator.py"
if ($PluginLinks.ContainsKey($Platform)) {
    Write-Host "Prompts: $(Join-Path $PluginLinks[$Platform] 'prompts')"
}
Write-Host "Agents must NOT search C:\ for scripts; use the path above."
if ($Platform -eq "opencode") {
    Write-Host "OpenCode human review: ensure opencode.json has `"permission`": { `"question`": `"allow`" }"
}
Write-Host "For Cursor: add the repository root as a local plugin, or rely on the installed skill links."
