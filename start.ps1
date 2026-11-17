$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 server.py --port 8765 --open
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python server.py --port 8765 --open
    exit $LASTEXITCODE
}

if (Get-Command python3 -ErrorAction SilentlyContinue) {
    & python3 server.py --port 8765 --open
    exit $LASTEXITCODE
}

Write-Error "Python 3 was not found. Install Python 3 and run this script again."
