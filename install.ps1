[CmdletBinding()]
param(
    [Parameter()]
    [string]$Source = $env:LOOM_INSTALL_SOURCE,

    [Parameter()]
    [string]$Python = $env:LOOM_PYTHON
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DefaultSource = "git+https://github.com/rj-Anurag/Loom.git"

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Executable,

        [Parameter()]
        [string[]]$Arguments = @()
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable"
    }
}

if ([string]::IsNullOrWhiteSpace($Source)) {
    $ProjectFile = Join-Path $PSScriptRoot "pyproject.toml"
    $PackageDirectory = Join-Path $PSScriptRoot "loom"
    if ($PSScriptRoot -and (Test-Path -LiteralPath $ProjectFile -PathType Leaf) -and
        (Test-Path -LiteralPath $PackageDirectory -PathType Container)) {
        $Source = $PSScriptRoot
    }
    else {
        $Source = $DefaultSource
    }
}

$PythonExecutable = $null
$PythonPrefix = @()
if (-not [string]::IsNullOrWhiteSpace($Python)) {
    $PythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        throw "Python command was not found: $Python"
    }
    $PythonExecutable = $PythonCommand.Source
}
else {
    $PyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher) {
        & $PyLauncher.Source -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
        if ($LASTEXITCODE -eq 0) {
            $PythonExecutable = $PyLauncher.Source
            $PythonPrefix = @("-3")
        }
    }

    if ($null -eq $PythonExecutable) {
        $PythonCommand = Get-Command "python" -ErrorAction SilentlyContinue
        if ($null -ne $PythonCommand) {
            $PythonExecutable = $PythonCommand.Source
        }
    }
}

if ($null -eq $PythonExecutable) {
    throw "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/."
}

& $PythonExecutable @PythonPrefix -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11 or newer is required."
}

$PipxCommand = Get-Command "pipx" -ErrorAction SilentlyContinue
$PipxAsModule = $false
if ($null -eq $PipxCommand) {
    & $PythonExecutable @PythonPrefix -m pipx --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing pipx for the current user..."
        Invoke-Checked -Executable $PythonExecutable -Arguments @(
            $PythonPrefix + @("-m", "pip", "install", "--user", "pipx")
        )
    }
    $PipxAsModule = $true
}

function Invoke-Pipx {
    param(
        [Parameter()]
        [string[]]$Arguments = @()
    )

    if ($PipxAsModule) {
        Invoke-Checked -Executable $PythonExecutable -Arguments @(
            $PythonPrefix + @("-m", "pipx") + $Arguments
        )
    }
    else {
        Invoke-Checked -Executable $PipxCommand.Source -Arguments $Arguments
    }
}

Write-Host "Installing Loom CLI..."
Invoke-Pipx -Arguments @("install", "--force", $Source)
Invoke-Pipx -Arguments @("ensurepath")

Write-Host ""
Write-Host "Loom is installed. Restart the terminal if 'loom' is not yet on PATH."
Write-Host "Verify it with: loom --version"
Write-Host "Install the browser extension with:"
Write-Host "  loom extension install --api-url https://loom-api-zzy0.onrender.com"
Write-Host "Then run 'loom extension path' and load that directory at chrome://extensions."
