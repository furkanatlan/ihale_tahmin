$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$AppFile = Join-Path $ProjectDir "tahmin_uygulamasi.py"
$OutputDir = Join-Path $ProjectDir "sonuclar"
$ModelBundle = Join-Path $OutputDir "en_iyi_3_model.joblib"
$ManifestFile = Join-Path $OutputDir "model_manifest.json"

Set-Location $ProjectDir

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw ".venv bulunamadi. Once .\01_kurulum.cmd komutunu calistirin."
}
if (-not (Test-Path -LiteralPath $AppFile)) {
    throw "Streamlit uygulamasi bulunamadi: $AppFile"
}
if (-not (Test-Path -LiteralPath $ModelBundle) -or -not (Test-Path -LiteralPath $ManifestFile)) {
    throw "Egitilmis uc model bulunamadi. Once .\02_egitim.cmd komutunu calistirin."
}

$Manifest = Get-Content -LiteralPath $ManifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
$TopModels = @($Manifest.en_iyi_3_model)
if ($TopModels.Count -ne 3) {
    throw "Model manifestinde tam olarak uc model yok. .\02_egitim.cmd ile yeniden egitim yapin."
}

Write-Host "Hazir model paketi bulundu: $($Manifest.olusturma_tarihi)" -ForegroundColor Green
Write-Host "Uygulamanin kullanacagi modeller:"
foreach ($Model in $TopModels) {
    Write-Host "  $($Model.sira). $($Model.model_adi)"
}
Write-Host ""
Write-Host "Streamlit aciliyor. Durdurmak icin bu terminalde Ctrl+C tuslarina basin." -ForegroundColor Cyan

& $VenvPython -m streamlit run $AppFile
if ($LASTEXITCODE -ne 0) {
    throw "Streamlit uygulamasi hata ile kapandi."
}
