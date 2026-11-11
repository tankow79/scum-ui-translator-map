@echo off
chcp 65001 >nul
title SCUM Chat Translator - Встановлення цифрового сертифіката

echo ====================================================================
echo   SCUM Chat Translator - Встановлення сертифіката довіри
echo   (Обхід блокування Windows SmartScreen / "Синій екран захисту")
echo ====================================================================
echo.

:: Перевірка прав адміністратора
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [i] Потрібні права адміністратора для додавання сертифіката в систему.
    echo [i] Запит підвищення привілеїв UAC...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\" %*\"' -Verb RunAs"
    exit /b
)

set "CER_FILE=%~dp0SCUM_Chat_Translator.cer"

if not exist "%CER_FILE%" (
    echo [!] ПОМИЛКА: Файл сертифіката не знайдено:
    echo     "%CER_FILE%"
    echo     Переконайтеся, що файл SCUM_Chat_Translator.cer лежить поруч із цим .bat файлом.
    echo.
    pause
    exit /b 1
)

echo [+] Додавання сертифіката до Довірених кореневих центрів сертифікації (Root)...
certutil.exe -addstore -f "Root" "%CER_FILE%" >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] Помилка додавання в сховище Root.
) else (
    echo [✓] Сховище Root: успішно.
)

echo [+] Додавання сертифіката до Довірених видавців (TrustedPublisher)...
certutil.exe -addstore -f "TrustedPublisher" "%CER_FILE%" >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] Помилка додавання в сховище TrustedPublisher.
) else (
    echo [✓] Сховище TrustedPublisher: успішно.
)

echo.
echo ====================================================================
echo   [✓] Сертифікат успішно встановлено!
echo   Тепер Windows SmartScreen визнає програму безпечною
echo   і дозволить запускати SCUM_Chat_Translator.exe без попереджень.
echo ====================================================================
echo.
pause
