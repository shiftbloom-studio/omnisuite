# bundle-python.ps1 — Download and bundle Python 3.12 + CPU deps for OmniSuite
# Run from the project root: .\scripts\bundle-python.ps1

$ErrorActionPreference = "Stop"
$PythonVersion = "3.12.8"
$BundleDir = "python-bundle"
$LibDir = "$BundleDir\lib"

Write-Host "=== OmniSuite Python Bundle Script ===" -ForegroundColor Cyan

# Clean previous bundle
if (Test-Path $BundleDir) {
    Write-Host "Cleaning previous bundle..."
    Remove-Item -Recurse -Force $BundleDir
}
New-Item -ItemType Directory -Path $LibDir -Force | Out-Null

# Download embeddable Python
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonZip = "python-embed.zip"
Write-Host "Downloading Python $PythonVersion embeddable..."
Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip
Expand-Archive -Path $PythonZip -DestinationPath $BundleDir -Force
Remove-Item $PythonZip

# Copy engine module
Write-Host "Copying omnisuite_engine.py..."
Copy-Item "python\omnisuite_engine.py" "$BundleDir\omnisuite_engine.py"

# Install CPU-only PyTorch
Write-Host "Installing PyTorch (CPU)..."
pip install --target=$LibDir torch torchaudio --index-url https://download.pytorch.org/whl/cpu --no-cache-dir

# Install other deps
Write-Host "Installing Python dependencies..."
pip install --target=$LibDir -r python/requirements-cpu.txt --no-cache-dir

# Install OmniVoice (no deps to avoid torch version conflict)
Write-Host "Installing OmniVoice..."
pip install --target=$LibDir omnivoice --no-deps --no-cache-dir

Write-Host "=== Bundle complete ===" -ForegroundColor Green
Write-Host "Output: $BundleDir"
Write-Host "Copy this directory as 'python/' alongside your built exe."
Get-ChildItem $BundleDir -Recurse | Measure-Object -Property Length -Sum |
    ForEach-Object { Write-Host ("Total size: {0:N0} MB" -f ($_.Sum / 1MB)) }
