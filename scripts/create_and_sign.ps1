# Скрипт генерації сертифіката та цифрового підпису виконуваних файлів
$certSubject = "CN=SCUM Chat Translator, O=AndraX Dev, C=UA"
$cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object { $_.Subject -like "*SCUM Chat Translator*" } | Select-Object -First 1

if (-not $cert) {
    Write-Host "[+] Створення нового сертифіката підпису коду..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $certSubject -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(10)
} else {
    Write-Host "[i] Знайдено існуючий сертифікат: $($cert.Thumbprint)" -ForegroundColor Green
}

# Експорт публічного сертифіката .cer у папку release
$cerPath = "release\SCUM_Chat_Translator.cer"
$parentDir = Split-Path $cerPath
if (-not (Test-Path $parentDir)) {
    New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
}

Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
Write-Host "[+] Публічний сертифікат збережено: $cerPath" -ForegroundColor Green

# Підпис виконуваних файлів у dist та release
$exeFiles = @(
    "dist\SCUM_Chat_Translator.exe",
    "dist\SCUM_Chat_Translator_Portable.exe",
    "release\SCUM_Chat_Translator.exe"
)

foreach ($exe in $exeFiles) {
    if (Test-Path $exe) {
        Write-Host "[+] Підпис файлу: $exe ..." -ForegroundColor Cyan
        $sig = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256
        Write-Host "    Статус: $($sig.StatusMessage)" -ForegroundColor Yellow
    }
}

Write-Host "[✓] Готово! Усі файли успішно підписані." -ForegroundColor Green
