@echo off
chcp 65001 >nul
echo ========================================================
echo  Встановлення локального сертифіката довіри для SCUM Suite
echo  (Прибирає попередження Windows SmartScreen)
echo ========================================================
echo.

powershell -Command "$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=SCUM Community Tools, O=SCUM Dev, C=UA' -CertStoreLocation 'Cert:\CurrentUser\My'; Export-Certificate -Cert $cert -FilePath '%~dp0scum_app.cer'; Import-Certificate -FilePath '%~dp0scum_app.cer' -CertStoreLocation 'Cert:\CurrentUser\Root'"

echo.
echo [OK] Сертифікат успішно додано до довірених!
echo Тепер Windows SmartScreen не показуватиме попередження.
pause
