param([string]$PythonExe)
$ErrorActionPreference = 'Stop'
$desktopRoot = $PSScriptRoot
$venvPython = Join-Path $desktopRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonExe) { & $PythonExe -m venv (Join-Path $desktopRoot '.venv') }
    else { & py -3.12 -m venv (Join-Path $desktopRoot '.venv') }
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or pass -PythonExe with its path.' }
}
& $venvPython -m pip install --requirement (Join-Path $desktopRoot 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Push-Location $desktopRoot
try { & $venvPython -c "from runtime_paths import media_tool; print('FFmpeg:', media_tool('ffmpeg')); print('FFprobe:', media_tool('ffprobe'))" }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Write-Host 'Install FFmpeg in PATH or set MUSIC_FFMPEG_DIR before syncing.' }
Write-Host 'Ready: open desktop/Start-Music.cmd.'
