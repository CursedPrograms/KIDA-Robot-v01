# run.ps1 - launch the KIDA-01 remote controller (creates its own venv on first run)
# Usage: .\run.ps1 <robot-ip-or-url> [--port 5004] [--emulate]
#        .\run.ps1          no robot: EMULATE, her pretend self on this PC
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path venv)) {
    python -m venv venv
    & .\venv\Scripts\python.exe -m pip install -r requirements.txt
}
& .\venv\Scripts\python.exe main.py @args
exit $LASTEXITCODE
