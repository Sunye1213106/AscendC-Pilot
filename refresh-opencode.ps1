# Refresh AscendC-Pilot for OpenCode — uninstall → reinstall → verify.
#
# Use after agent code changes, before re-testing in OpenCode:
#   1. Fully quit OpenCode (not just close a chat tab)
#   2. From this repo root:
#        .\refresh-opencode.ps1
#   3. Start OpenCode again
#
# Options:
#   -SkipPip     Skip pip reinstall (editable acp usually already live)
#   -ForcePip    Force pip reinstall even if SKIP_PIP=1 is set in env
#   -WhatIf      Show plan only
#
param(
  [switch]$SkipPip,
  [switch]$ForcePip,
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $BundleRoot
$InstallPs1 = Join-Path $BundleRoot "install.ps1"

function Invoke-InstallPs1 {
  param(
    [Parameter(Mandatory = $true)][string]$Arg,
    [hashtable]$EnvExtra = @{}
  )
  # install.ps1 uses `exit` — must run in a child process so parent refresh continues.
  $envAssign = ""
  foreach ($k in $EnvExtra.Keys) {
    $val = [string]$EnvExtra[$k]
    $envAssign += "`$env:$k='$val'; "
  }
  if ($envAssign) {
    $cmd = "$envAssign & `"$InstallPs1`" $Arg; exit `$LASTEXITCODE"
    $p = Start-Process -FilePath "powershell.exe" `
      -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd) `
      -WorkingDirectory $BundleRoot `
      -Wait -PassThru -NoNewWindow
  } else {
    $p = Start-Process -FilePath "powershell.exe" `
      -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $InstallPs1,
        $Arg
      ) `
      -WorkingDirectory $BundleRoot `
      -Wait -PassThru -NoNewWindow
  }
  if ($null -eq $p -or $p.ExitCode -ne 0) {
    $code = if ($null -eq $p) { "null" } else { $p.ExitCode }
    throw "install.ps1 $Arg failed with exit $code"
  }
}

function Get-FileSha256([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-True([bool]$Cond, [string]$Msg) {
  if (-not $Cond) { throw "VERIFY FAIL: $Msg" }
  Write-Host "  OK  $Msg"
}

Write-Host ""
Write-Host "=== AscendC OpenCode refresh ==="
Write-Host "Repo: $BundleRoot"
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""
Write-Host "Prerequisite: OpenCode must be fully exited (plugin is loaded at process start)."
Write-Host ""

if ($WhatIf) {
  Write-Host "[WhatIf] Would run:"
  Write-Host "  1. install.ps1 uninstall-opencode"
  Write-Host "  2. install.ps1 opencode   (pip + compose + plugin/skills/agents)"
  Write-Host "  3. Verify plugin hash, acp import, observation module"
  exit 0
}

if (-not (Test-Path -LiteralPath $InstallPs1)) {
  throw "Missing install.ps1 at $InstallPs1"
}

# --- 1) Uninstall ---
Write-Host "[1/3] Uninstall OpenCode AscendC bits..."
Invoke-InstallPs1 -Arg "uninstall-opencode"

# --- 2) Reinstall ---
Write-Host ""
Write-Host "[2/3] Reinstall OpenCode AscendC bits..."
$envExtra = @{}
if ($ForcePip) {
  Write-Host "  pip: FORCED reinstall"
} elseif ($SkipPip -or $env:SKIP_PIP -eq "1") {
  $envExtra["SKIP_PIP"] = "1"
  Write-Host "  pip: SKIPPED (editable packages assumed current)"
} else {
  Write-Host "  pip: reinstall editable acp / uo / tg"
}

Invoke-InstallPs1 -Arg "opencode" -EnvExtra $envExtra

# --- 3) Verify this install matches THIS repo ---
Write-Host ""
Write-Host "[3/3] Verify install matches current repo..."

$pluginSrc = Join-Path $BundleRoot "opencode-plugin\ascendc-pilot.ts"
$pluginDst = Join-Path $HOME ".config\opencode\plugins\ascendc-pilot.ts"
$srcHash = Get-FileSha256 $pluginSrc
$dstHash = Get-FileSha256 $pluginDst

Assert-True (Test-Path -LiteralPath $pluginSrc) "plugin source exists: $pluginSrc"
Assert-True (Test-Path -LiteralPath $pluginDst) "plugin installed: $pluginDst"
Assert-True ($null -ne $srcHash -and $srcHash -eq $dstHash) "plugin SHA256 matches repo ($srcHash)"

# Containment markers must be present in installed plugin
$pluginText = Get-Content -LiteralPath $pluginDst -Raw -Encoding UTF8
Assert-True ($pluginText -match 'tool === "read"') "installed plugin intercepts read"
Assert-True ($pluginText -match 'shell:\s*false') "installed plugin uses shell:false (Windows-safe)"
Assert-True ($pluginText -match 'resolveAcpBin|never use shell:true') "installed plugin documents Windows spawn fix"
Assert-True ($pluginText -match '\["acp"\]') "installed plugin resolves acp (not legacy pilot)"
Assert-True ($pluginText -notmatch '\["pilot"\]') "installed plugin no longer looks up pilot binary"

# Skills / primary agent
$skillLink = Join-Path $HOME ".config\opencode\skills\uo-init"
$agentLink = Join-Path $HOME ".config\opencode\agents\ascendc-pilot.md"
Assert-True (Test-Path -LiteralPath $skillLink) "uo-init skill linked"
Assert-True (Test-Path -LiteralPath $agentLink) "ascendc-pilot.md installed"

# Pilot Python must be THIS repo (editable) and include new modules
$pyCheck = @"
import ascendc_pilot, pathlib
p = pathlib.Path(ascendc_pilot.__file__).resolve()
root = pathlib.Path(r'''$BundleRoot''').resolve()
print('HARNESS_FILE=' + str(p))
assert str(p).lower().startswith(str(root).lower()), (p, root)
import ascendc_pilot.observation as obs
import ascendc_pilot.authorize.lease as lease
assert hasattr(obs, 'apply_observation')
assert hasattr(lease, 'issue_containment_lease')
print('HARNESS_OK')
"@
$pyOut = & python -c $pyCheck 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host $pyOut
  throw "VERIFY FAIL: acp python import / module check failed"
}
Assert-True ("$pyOut" -match "HARNESS_OK") "acp imports from this repo + observation/lease present"

# acp CLI on PATH
$harnessCmd = Get-Command acp -ErrorAction SilentlyContinue
Assert-True ($null -ne $harnessCmd) "acp CLI is on PATH ($($harnessCmd.Source))"

Write-Host ""
Write-Host "=== Refresh complete ==="
Write-Host "Plugin hash : $dstHash"
Write-Host "Next steps  :"
Write-Host "  1. Start OpenCode"
Write-Host "  2. Tab → ascendc-pilot (primary)"
Write-Host "  3. Run your uo-init / acp test"
Write-Host ""
