# Windows entrypoint: install Python if absent, then use the shared setup engine.
# ExecutionPolicy is scoped to this process by setup.cmd, not changed on the machine.
$ErrorActionPreference = 'Stop'
$forwarded = @($args)
$root = Split-Path -Parent $PSScriptRoot

function Find-CelluloidPython {
    $candidates = @(
        @{ Exe = 'py'; Prefix = @('-3') },
        @{ Exe = "$env:ProgramFiles\LibreOffice\program\python.exe"; Prefix = @() },
        @{ Exe = 'python'; Prefix = @() },
        @{ Exe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"; Prefix = @() },
        @{ Exe = "$env:ProgramFiles\Python312\python.exe"; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
        if ($command) {
            $prefix = $candidate.Prefix
            try {
                & $command.Source @prefix -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' *> $null
            } catch {
                continue
            }
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $command.Source; Prefix = $prefix }
            }
        }
    }
    return $null
}

try {
    $python = Find-CelluloidPython
    if (-not $python) {
        if (($forwarded -contains '--dry-run') -or ($forwarded -contains '--check') -or
            ($forwarded -contains '--no-install') -or ($forwarded -contains '--help')) {
            throw 'Python 3.10+ is required. No changes made. Install Python, then rerun setup.cmd.'
        }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Install App Installer (WinGet) from Microsoft Store, then rerun setup.cmd.'
        }
        Write-Host 'Installing Python first; Windows may request administrator approval.'
        & winget install --id Python.Python.3.12 --exact --source winget
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. Resolve the WinGet message and rerun.' }
        $python = Find-CelluloidPython
        if (-not $python) { throw 'Open a new terminal after Python installation and rerun setup.cmd.' }
    }
    $prefix = $python.Prefix
    & $python.Exe @prefix (Join-Path $root 'setup_celluloid.py') @forwarded
    exit $LASTEXITCODE
} catch {
    Write-Host "Celluloid setup: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
