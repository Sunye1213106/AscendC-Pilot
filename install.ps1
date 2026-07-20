<#
.SYNOPSIS
  Install both understand-operator and testcase-agent for OpenCode / Codex / Cursor.

.DESCRIPTION
  Thin wrapper that runs each agent's install.ps1 in order:
    1) understand-operator
    2) testcase-agent

.EXAMPLE
  ./install.ps1 opencode
  ./install.ps1 cursor -SkipPip
  ./install.ps1 -Uninstall opencode
  ./install.ps1 opencode -Only understand-operator
  ./install.ps1 opencode -Only testcase-agent
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("opencode", "codex", "cursor")]
    [string]$Platform = "opencode",

    [ValidateSet("opencode", "codex", "cursor")]
    [string]$Uninstall,

    [ValidateSet("all", "understand-operator", "testcase-agent")]
    [string]$Only = "all",

    [switch]$SkipPip
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$UoRoot = Join-Path $BundleRoot "understand-operator"
$TgRoot = Join-Path $BundleRoot "testcase-agent"

function Assert-AgentRoot {
    param([string]$Name, [string]$Root)
    $script = Join-Path $Root "install.ps1"
    if (-not (Test-Path -LiteralPath $script)) {
        throw "Missing $Name installer: $script"
    }
}

function Invoke-AgentInstall {
    param(
        [string]$Name,
        [string]$Root,
        [string]$PlatformArg,
        [switch]$DoUninstall,
        [switch]$NoPip
    )
    $script = Join-Path $Root "install.ps1"
    Write-Host ""
    Write-Host "======== $Name ========"
    $argsList = @()
    if ($DoUninstall) {
        $argsList += @("-Uninstall", $PlatformArg)
    } else {
        $argsList += $PlatformArg
        if ($NoPip -and $Name -eq "testcase-agent") {
            $argsList += "-SkipPip"
        }
    }
    & $script @argsList
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "$Name install failed with exit code $LASTEXITCODE"
    }
}

Assert-AgentRoot "understand-operator" $UoRoot
Assert-AgentRoot "testcase-agent" $TgRoot

$targetPlatform = if ($Uninstall) { $Uninstall } else { $Platform }
$doUninstall = [bool]$Uninstall

$agents = @()
if ($Only -in @("all", "understand-operator")) {
    $agents += @{ Name = "understand-operator"; Root = $UoRoot }
}
if ($Only -in @("all", "testcase-agent")) {
    $agents += @{ Name = "testcase-agent"; Root = $TgRoot }
}

Write-Host "Ascendc PR agents bundle install"
Write-Host "  Bundle:   $BundleRoot"
Write-Host "  Platform: $targetPlatform"
Write-Host "  Mode:     $(if ($doUninstall) { 'uninstall' } else { 'install' })"
Write-Host "  Agents:   $($agents.Name -join ', ')"

foreach ($agent in $agents) {
    Invoke-AgentInstall `
        -Name $agent.Name `
        -Root $agent.Root `
        -PlatformArg $targetPlatform `
        -DoUninstall:$doUninstall `
        -NoPip:$SkipPip
}

Write-Host ""
Write-Host "======== Done ========"
if ($doUninstall) {
    Write-Host "Uninstalled: $($agents.Name -join ', ') ($targetPlatform)"
} else {
    Write-Host "Installed: $($agents.Name -join ', ') ($targetPlatform)"
    Write-Host "UO commands: /uo-init  /uo-query  /uo-update  /uo-diff"
    Write-Host "TG commands: /tg-contract  /tg-plan  /tg-solve"
    if ($targetPlatform -eq "opencode") {
        Write-Host 'OpenCode: ensure opencode.json has "permission": { "question": "allow" }'
    }
}
