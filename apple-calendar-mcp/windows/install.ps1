<#
.SYNOPSIS
  Installs the Apple Calendar MCP server for Claude Desktop (and Claude Code if present) on Windows.

.DESCRIPTION
  1. Finds Python 3.10+ (installs 3.12 via winget if missing)
  2. Copies the server to %LOCALAPPDATA%\apple-calendar-mcp and builds a venv there
  3. Prompts for Apple ID + app-specific password, writes them to a locked-down .env
  4. Tests the iCloud login (--check)
  5. Adds "apple-calendar" to claude_desktop_config.json (backs it up first)
  6. Optionally registers with Claude Code and restarts Claude Desktop

  Credentials never go into the Claude config; it only holds the path to the .env.
  Safe to re-run: it upgrades in place and keeps your existing .env unless you choose to replace it.

.PARAMETER Uninstall
  Removes the Claude Desktop/Claude Code entries and deletes the install folder.

.NOTES
  Target: Windows PowerShell 5.1+ (stock Windows 10/11). No admin rights needed.
#>
[CmdletBinding()]
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$ServerName = 'apple-calendar'
$Dest       = Join-Path $env:LOCALAPPDATA 'apple-calendar-mcp'
$EnvFile    = Join-Path $Dest '.env'
$Exe        = Join-Path $Dest '.venv\Scripts\apple-calendar-mcp.exe'
$Src        = Split-Path -Parent $PSScriptRoot      # repo's apple-calendar-mcp folder
$Utf8NoBom  = New-Object System.Text.UTF8Encoding($false)

function Say  ($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "    $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "    $m" -ForegroundColor Yellow }
function Die  ($m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

# Native commands: PS 5.1 turns stderr into terminating errors under 'Stop', so relax it per call.
function Invoke-Native {
    param([string]$File, [string[]]$ArgList)
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try   { $out = & $File @ArgList 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $prev }
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = ($out -join "`n") }
}

function Ask-YesNo ($prompt, [bool]$default = $true) {
    $hint = if ($default) { '[Y/n]' } else { '[y/N]' }
    $a = Read-Host "$prompt $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return $a.Trim().ToLower().StartsWith('y')
}

# --------------------------------------------------------------------------
# Claude Desktop config locations (standard installer + Microsoft Store/MSIX)
# --------------------------------------------------------------------------
function Get-ClaudeConfigPaths {
    $paths = @()
    $std = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
    if (Test-Path (Split-Path $std)) { $paths += $std }
    $pkgRoot = Join-Path $env:LOCALAPPDATA 'Packages'
    if (Test-Path $pkgRoot) {
        Get-ChildItem $pkgRoot -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue | ForEach-Object {
            $d = Join-Path $_.FullName 'LocalCache\Roaming\Claude'
            if (Test-Path $d) { $paths += (Join-Path $d 'claude_desktop_config.json') }
        }
    }
    if ($paths.Count -eq 0) { $paths += $std }   # Claude not launched yet: create the standard one
    return $paths
}

function Read-JsonFile ($path) {
    if (-not (Test-Path $path)) { return New-Object psobject }
    $raw = [IO.File]::ReadAllText($path)
    if ([string]::IsNullOrWhiteSpace($raw)) { return New-Object psobject }
    try { return $raw | ConvertFrom-Json }
    catch { Die "Could not parse $path (invalid JSON). Fix or delete it, then re-run.`n$($_.Exception.Message)" }
}

function Write-JsonFile ($path, $obj) {
    $dir = Split-Path $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    # No BOM: Claude Desktop's JSON parser rejects it.
    [IO.File]::WriteAllText($path, ($obj | ConvertTo-Json -Depth 50), $Utf8NoBom)
}

function Set-ClaudeDesktopEntry ([bool]$remove) {
    foreach ($cfgPath in Get-ClaudeConfigPaths) {
        $cfg = Read-JsonFile $cfgPath
        if (Test-Path $cfgPath) {
            $bak = "$cfgPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
            Copy-Item $cfgPath $bak
        }
        if (-not ($cfg.PSObject.Properties.Name -contains 'mcpServers')) {
            if ($remove) { continue }
            $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object psobject)
        }
        if ($cfg.mcpServers.PSObject.Properties.Name -contains $ServerName) {
            $cfg.mcpServers.PSObject.Properties.Remove($ServerName)
        }
        if (-not $remove) {
            $entry = [pscustomobject]@{
                command = $Exe
                args    = @()
                env     = [pscustomobject]@{ APPLE_CAL_ENV_FILE = $EnvFile }
            }
            $cfg.mcpServers | Add-Member -NotePropertyName $ServerName -NotePropertyValue $entry
        }
        Write-JsonFile $cfgPath $cfg
        if ($remove) { Ok "Removed from $cfgPath" } else { Ok "Updated $cfgPath" }
    }
}

function Restart-ClaudeDesktop {
    $procs = Get-Process -Name 'claude' -ErrorAction SilentlyContinue |
             Where-Object { $_.Path -and $_.Path -match 'AnthropicClaude|WindowsApps|\\Claude\\' }
    if (-not $procs) { Warn 'Claude Desktop is not running. Start it and the calendar tools will load.'; return }
    if (-not (Ask-YesNo 'Restart Claude Desktop now so it picks up the new server?')) {
        Warn 'Fully quit Claude Desktop (tray icon > Quit, not just closing the window) and reopen it.'
        return
    }
    $exePath = ($procs | Where-Object { $_.Path } | Select-Object -First 1).Path
    $procs | Stop-Process -Force
    Start-Sleep -Seconds 2
    if ($exePath -and (Test-Path $exePath) -and ($exePath -notlike '*\WindowsApps\*')) {
        Start-Process $exePath
        Ok 'Claude Desktop restarted.'
    } else {
        Warn 'Closed Claude Desktop. Reopen it from the Start menu.'
    }
}

function Get-ClaudeCodeCli {
    $cmd = Get-Command claude -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source } else { return $null }
}

# ==========================================================================
# Uninstall
# ==========================================================================
if ($Uninstall) {
    Say 'Removing Apple Calendar MCP'
    Set-ClaudeDesktopEntry $true
    $cc = Get-ClaudeCodeCli
    if ($cc) { Invoke-Native $cc @('mcp', 'remove', '--scope', 'user', $ServerName) | Out-Null; Ok 'Removed from Claude Code (if it was registered).' }
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force; Ok "Deleted $Dest" }
    Warn 'Also revoke the app-specific password at appleid.apple.com > Sign-In and Security.'
    Restart-ClaudeDesktop
    exit 0
}

# ==========================================================================
# 1. Python
# ==========================================================================
Say 'Checking for Python 3.10+'
if (-not (Test-Path (Join-Path $Src 'apple_calendar_mcp\server.py'))) {
    Die "Can't find the server source next to this script. Run install.cmd from inside the extracted apple-calendar-mcp\windows folder."
}

function Find-Python {
    $candidates = @(
        @{ f = 'py';     a = @('-3') },
        @{ f = 'python'; a = @() },
        @{ f = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'); a = @() },
        @{ f = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'); a = @() }
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.f -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        # Skip the Microsoft Store "python.exe" stub that just opens the Store
        if ($cmd.Source -like '*\WindowsApps\python*.exe') { continue }
        $r = Invoke-Native $cmd.Source ($c.a + @('-c', 'import sys; print(sys.version_info >= (3,10)); print(sys.executable)'))
        if ($r.Code -eq 0 -and $r.Output -match '^True') {
            return ($r.Output -split "`n")[1].Trim()
        }
    }
    return $null
}

$Py = Find-Python
if (-not $Py) {
    Warn 'Python 3.10+ not found.'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Die 'winget is not available. Install Python 3.12 from python.org (check "Add to PATH"), then re-run.'
    }
    if (-not (Ask-YesNo 'Install Python 3.12 (per-user, no admin) via winget?')) { Die 'Python is required.' }
    $r = Invoke-Native 'winget' @('install', '-e', '--id', 'Python.Python.3.12', '--scope', 'user',
                                  '--accept-package-agreements', '--accept-source-agreements', '--silent')
    $Py = Find-Python
    if (-not $Py) { Die "Python install did not complete.`n$($r.Output)" }
}
Ok "Using $Py"

# ==========================================================================
# 2. Copy source + venv
# ==========================================================================
Say "Installing to $Dest"
New-Item -ItemType Directory -Path $Dest -Force | Out-Null
foreach ($item in 'apple_calendar_mcp', 'pyproject.toml', 'README.md', '.env.example') {
    $from = Join-Path $Src $item
    if (Test-Path $from) { Copy-Item $from $Dest -Recurse -Force }
}
Get-ChildItem (Join-Path $Dest 'apple_calendar_mcp') -Recurse -File | Unblock-File -ErrorAction SilentlyContinue  # strip internet flag

$VenvPy = Join-Path $Dest '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    $r = Invoke-Native $Py @('-m', 'venv', (Join-Path $Dest '.venv'))
    if ($r.Code -ne 0) { Die "venv creation failed:`n$($r.Output)" }
}
Say 'Installing dependencies (about a minute)'
Invoke-Native $VenvPy @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip') | Out-Null
$r = Invoke-Native $VenvPy @('-m', 'pip', 'install', '--quiet', '--upgrade', '-e', $Dest)
if ($r.Code -ne 0 -or -not (Test-Path $Exe)) { Die "pip install failed:`n$($r.Output)" }
Ok 'Dependencies installed.'

# ==========================================================================
# 3. Credentials -> .env (locked to this user)
# ==========================================================================
function Write-EnvFile {
    Write-Host ''
    Write-Host '  You need an Apple app-specific password (NOT your normal Apple ID password):' -ForegroundColor White
    Write-Host '  appleid.apple.com > Sign-In and Security > App-Specific Passwords > +  (name it "claude-calendar")'
    Write-Host ''
    do { $user = (Read-Host 'Apple ID email').Trim() } while ($user -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$')
    do {
        $sec  = Read-Host 'App-specific password (xxxx-xxxx-xxxx-xxxx)' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        try   { $pw = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if ($pw -notmatch '^[a-z]{4}-?[a-z]{4}-?[a-z]{4}-?[a-z]{4}$') { Warn 'That does not look like an app-specific password (16 lowercase letters).' }
    } while ([string]::IsNullOrWhiteSpace($pw))

    $tz = (Read-Host 'Time zone [America/Chicago]').Trim()
    if (-not $tz) { $tz = 'America/Chicago' }
    $ro  = if (Ask-YesNo 'Read-only mode? (Claude can view but not create/edit/delete events)' $false) { '1' } else { '0' }
    $only = (Read-Host 'Limit Claude to specific calendars? Comma list, or Enter for all').Trim()

    $content = @(
        "ICLOUD_USERNAME=$user",
        "ICLOUD_APP_PASSWORD=$pw",
        "CAL_TIMEZONE=$tz",
        "CAL_READ_ONLY=$ro",
        "CAL_ALLOWED_CALENDARS=$only"
    ) -join "`r`n"
    [IO.File]::WriteAllText($EnvFile, $content + "`r`n", $Utf8NoBom)
    $pw = $null

    # Only the current user can read it
    Invoke-Native 'icacls' @($EnvFile, '/inheritance:r', '/grant:r', "$($env:USERDOMAIN)\$($env:USERNAME):(M)") | Out-Null
    Ok "Saved credentials to $EnvFile (readable only by $($env:USERNAME))"
}

Say 'Apple credentials'
if ((Test-Path $EnvFile) -and -not (Ask-YesNo 'Existing credentials found. Replace them?' $false)) {
    Ok 'Keeping existing .env'
} else {
    Write-EnvFile
}

# ==========================================================================
# 4. Test login
# ==========================================================================
Say 'Testing iCloud connection'
while ($true) {
    $env:APPLE_CAL_ENV_FILE = $EnvFile
    $r = Invoke-Native $Exe @('--check')
    if ($r.Code -eq 0) { $r.Output -split "`n" | ForEach-Object { Ok $_ }; break }
    Write-Host $r.Output -ForegroundColor Red
    if ($r.Output -match 'Unauthorized|401|Authoriz') {
        Warn 'Apple rejected the login. Use the app-specific password, not your Apple ID password.'
    }
    if (-not (Ask-YesNo 'Re-enter credentials and try again?')) { Die 'Login test failed. Re-run install.cmd when ready.' }
    Write-EnvFile
}

# ==========================================================================
# 5. Register with Claude Desktop / Claude Code
# ==========================================================================
Say 'Registering with Claude Desktop'
Set-ClaudeDesktopEntry $false

$cc = Get-ClaudeCodeCli
if ($cc -and (Ask-YesNo 'Claude Code CLI found. Register the calendar there too?')) {
    Invoke-Native $cc @('mcp', 'remove', '--scope', 'user', $ServerName) | Out-Null
    $r = Invoke-Native $cc @('mcp', 'add', '--scope', 'user', $ServerName, '-e', "APPLE_CAL_ENV_FILE=$EnvFile", '--', $Exe)
    if ($r.Code -eq 0) { Ok 'Registered with Claude Code (user scope).' } else { Warn "Claude Code registration failed:`n$($r.Output)" }
}

Restart-ClaudeDesktop

Write-Host ''
Write-Host 'Done. In Claude Desktop, open a new chat and try:' -ForegroundColor Green
Write-Host '  "What''s on my calendar this week?"'
Write-Host ''
Write-Host "Change settings:  notepad `"$EnvFile`"   (then restart Claude Desktop)"
Write-Host 'Uninstall:        install.cmd -Uninstall'
