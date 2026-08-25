$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectDir "requirements.txt"

Set-Location $ProjectDir

if (-not (Test-Path -LiteralPath $Requirements)) {
    throw "requirements.txt bulunamadi: $Requirements"
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Python 3.10 sanal ortami olusturuluyor..." -ForegroundColor Cyan
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher) {
        & py -3.10 -m venv $VenvDir
    }
    else {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $PythonCommand) {
            throw "Python bulunamadi. Once Python 3.10 kurun ve bu betigi yeniden calistirin."
        }
        & python -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Sanal ortam olusturulamadi. Python 3.10 kurulumunu kontrol edin."
    }
}
else {
    Write-Host "Mevcut .venv sanal ortami kullanilacak." -ForegroundColor Green
}

Write-Host "Gerekli Python kutuphaneleri denetleniyor ve eksikler kuruluyor..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip guncellenemedi."
}

& $VenvPython -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "Python kutuphaneleri kurulamadi."
}

$PythonVersion = & $VenvPython -c "import platform; print(platform.python_version())"
$StreamlitVersion = & $VenvPython -c "import streamlit; print(streamlit.__version__)"

Write-Host ""
Write-Host "Kurulum tamamlandi." -ForegroundColor Green
Write-Host "Python: $PythonVersion"
Write-Host "Streamlit: $StreamlitVersion"
Write-Host "Sonraki adim: .\02_egitim.cmd"
