# exaone-skill installer (Windows PowerShell 5.1+ / PowerShell 7). ASCII only.
# Usage: .\setup.ps1            install plugin + register key (if missing)
#        .\setup.ps1 -SkipKey   install plugin only
#        .\setup.ps1 -Effort low|medium|high|max
param(
    [switch]$SkipKey,
    [string]$Effort = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Market = "exaone-skill-local"
$Plugin = "exaone-skill@$Market"

function Find-Python {
    foreach ($c in @("python", "py", "python3")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            $out = & $c --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$out" -match "Python 3") { return $c }
        }
    }
    return $null
}

$Py = Find-Python
if (-not $Py) { Write-Host "[ERROR] Python 3 not found on PATH."; exit 1 }
Write-Host "[OK] python: $Py"

$Claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $Claude) {
    Write-Host "[WARN] 'claude' CLI not on PATH. Install manually inside Claude Code:"
    Write-Host "  /plugin marketplace add $Root"
    Write-Host "  /plugin install $Plugin"
} else {
    $list = (& claude plugin marketplace list 2>&1) | Out-String
    if ($list -match [regex]::Escape($Market)) {
        Write-Host "[..] marketplace exists; updating"
        & claude plugin marketplace update $Market
    } else {
        Write-Host "[..] adding marketplace $Root"
        & claude plugin marketplace add "$Root"
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] marketplace add/update failed"; exit 1 }
    Write-Host "[..] installing $Plugin"
    & claude plugin install $Plugin
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[..] install returned $LASTEXITCODE; trying update (already installed?)"
        & claude plugin update $Plugin
        if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] plugin install/update failed"; exit 1 }
    }
    Write-Host "[OK] plugin installed. Restart Claude Code to load it."
}

$SetupPy = Join-Path $Root "scripts\setup.py"
if ($Effort -ne "") {
    & $Py $SetupPy --set-effort $Effort
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

if (-not $SkipKey) {
    & $Py $SetupPy --show *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] API key already registered (python scripts\setup.py --key --prompt to replace)"
    } elseif ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        & $Py $SetupPy --key --prompt
        if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] key not stored"; exit 1 }
    } else {
        Write-Host "[WARN] non-interactive shell; register the key later:"
        Write-Host "  $Py `"$SetupPy`" --key --prompt"
    }
}
& $Py $SetupPy --show
exit 0
