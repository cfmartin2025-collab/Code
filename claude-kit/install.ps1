# Installs the token-efficiency kit into your user-level Claude Code config (Windows).
# Usage (PowerShell, from this folder):  powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = 'Stop'
$cc    = Join-Path $HOME '.claude'
$hooks = Join-Path $cc 'hooks'
$cfg   = Join-Path $cc 'settings.json'
New-Item -ItemType Directory -Force -Path $hooks | Out-Null
Copy-Item "$PSScriptRoot\trim_output.py","$PSScriptRoot\statusline.py" $hooks -Force

# Pick a Python that actually runs (python3 on Windows is often the Store stub).
$py = $null
foreach ($c in 'py','python','python3') {
  try { & $c -c "print(1)" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch {}
}
if (-not $py) { throw 'No working Python found. Install Python 3 and re-run.' }

if (Test-Path $cfg) {
  Copy-Item $cfg "$cfg.bak-$(Get-Date -Format yyyyMMddHHmmss)"
  $s = Get-Content $cfg -Raw | ConvertFrom-Json
} else { $s = [pscustomobject]@{} }

$trimCmd = "$py ~/.claude/hooks/trim_output.py"
$hook = [pscustomobject]@{ matcher = 'Bash'; hooks = @([pscustomobject]@{ type='command'; command=$trimCmd; timeout=10 }) }
if (-not $s.PSObject.Properties['hooks']) { $s | Add-Member hooks ([pscustomobject]@{}) }
$existing = @()
if ($s.hooks.PSObject.Properties['PostToolUse']) {
  $existing = @($s.hooks.PostToolUse | Where-Object { ($_.hooks.command -join ' ') -notmatch 'trim_output\.py' })
}
$s.hooks | Add-Member PostToolUse (@($existing) + $hook) -Force
$s | Add-Member statusLine ([pscustomobject]@{ type='command'; command="$py ~/.claude/hooks/statusline.py" }) -Force

$s | ConvertTo-Json -Depth 20 | Set-Content $cfg -Encoding UTF8
Write-Host "Installed. Python: $py  Settings: $cfg (backup saved). Restart Claude Code."
