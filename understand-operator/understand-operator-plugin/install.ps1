$ErrorActionPreference = "Stop"

$PluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$PluginRoot\skills\understand-operator\verify_required_scripts.py" --plugin-root "$PluginRoot"
