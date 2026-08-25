$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$TrainingScript = Join-Path $ProjectDir "ihale_maliyet_modelleme.py"
$OutputDir = Join-Path $ProjectDir "sonuclar"

Set-Location $ProjectDir

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw ".venv bulunamadi. Once .\01_kurulum.cmd komutunu calistirin."
}
if (-not (Test-Path -LiteralPath $TrainingScript)) {
    throw "Egitim kodu bulunamadi: $TrainingScript"
}
$ExcelCandidates = @(
    Get-ChildItem -LiteralPath $ProjectDir -Filter "*.xlsx" -File |
        Where-Object { $_.Name -ne "veriler.xlsx" }
)
if ($ExcelCandidates.Count -ne 1) {
    throw "Guncel egitim Excel dosyasi tekil olarak bulunamadi. Proje klasorunde veriler.xlsx disinda tam bir xlsx dosyasi olmali."
}
$ExcelFile = $ExcelCandidates[0].FullName

Write-Host "Model egitimi ve degerlendirme baslatiliyor..." -ForegroundColor Cyan
Write-Host "Excel: $ExcelFile"
Write-Host "Cikti: $OutputDir"
Write-Host ""

& $VenvPython $TrainingScript --excel $ExcelFile --output $OutputDir
if ($LASTEXITCODE -ne 0) {
    throw "Egitim basarisiz oldu. Yukaridaki hata mesajlarini kontrol edin."
}

$RequiredOutputs = @(
    (Join-Path $OutputDir "model_performanslari.txt"),
    (Join-Path $OutputDir "model_performanslari.csv"),
    (Join-Path $OutputDir "en_iyi_3_model.joblib"),
    (Join-Path $OutputDir "model_manifest.json"),
    (Join-Path $OutputDir "grafikler")
)
foreach ($RequiredOutput in $RequiredOutputs) {
    if (-not (Test-Path -LiteralPath $RequiredOutput)) {
        throw "Beklenen egitim ciktisi olusturulmadi: $RequiredOutput"
    }
}

$GraphCount = (Get-ChildItem -LiteralPath (Join-Path $OutputDir "grafikler") -Filter "*.png" -File).Count
$Manifest = Get-Content -LiteralPath (Join-Path $OutputDir "model_manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json

Write-Host ""
Write-Host "Egitim ve cikti uretimi tamamlandi." -ForegroundColor Green
Write-Host "Metin raporu: $(Join-Path $OutputDir 'model_performanslari.txt')"
Write-Host "Grafik sayisi: $GraphCount"
Write-Host "Kaydedilen en iyi 3 model:"
foreach ($Model in $Manifest.en_iyi_3_model) {
    $RmseMillion = [math]::Round($Model.RMSE_TL / 1000000, 2)
    Write-Host "  $($Model.sira). $($Model.model_adi) | RMSE: $RmseMillion milyon TL"
}
Write-Host ""
Write-Host "Tahmin uygulamasini acmak icin: .\03_uygulamayi_baslat.cmd"
