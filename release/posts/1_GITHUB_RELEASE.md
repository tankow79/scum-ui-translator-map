# 🗺️ SCUM Tactical Map & Real-Time Chat Translator v2.0.0

## 📦 Release Information
- **Tag:** `v2.0.0`
- **Release Name:** `SCUM Tactical Map & Real-Time Chat Translator v2.0.0 (Enterprise Multi-Language)`
- **Target OS:** Windows 10 / 11 (64-bit)
- **Binary Assets:** `SCUM_Chat_Translator_v2.0.0.zip`, `SCUM_Chat_Translator.exe`, `install_cert.bat`

---

## 🚀 Key Highlights & Changelog

### 🗺️ Standalone Tactical Map & GPS Interceptor
- **Tray-based Map Access:** Open, inspect, and manage coordinates and points directly from the Windows system tray without having SCUM.exe running.
- **In-App Color Picker Fix:** The pin color dialog is now constrained with `WindowStaysOnTopHint`, eliminating accidental fullscreen game minimization (Alt-Tab drop).
- **Flexible Hotkeys:** Added one-click clearing for hotkeys (`T`, `F8`, `F9`, `Ctrl+M`), allowing users to completely unbind actions.

### 🌐 Multi-Language Architecture (i18n)
- Native modular interface localization with instant language switching in Settings:
  - 🇺🇦 **Українська** (Ukrainian)
  - 🇬🇧 **English** (English)
  - 🇷🇺 **Русский** (Russian)
- Expandable JSON dictionary engine (`assets/locales/*.json`) prepared for future community translations.

### 💬 Real-Time Chat & Translation Engine
- **Squad / Team In-Game Green Highlighting:** Messages in squad channel (`[Squad]`, `(Team)`) are automatically identified and colored in genuine SCUM Green (`#4ade80`).
- **Instant Blacklist Bypass:** Messages from players on your blacklisted list now appear in chat immediately in their original form with zero translation lag.
- **"Map Only" Mode:** Option to completely disable the chat overlay and cease all log file polling, saving CPU cycles and SSD operations.

### 🛡️ Windows Autostart & SmartScreen Compliance
- **Safe Autostart:** Seamless Windows startup integration using the current user registry hive (`HKCU\...\Run`), requiring no administrator privileges.
- **SmartScreen Mitigation:** Embedded PE metadata (Company, Description, Version 2.0.0.0) and provided `install_cert.bat` helper to establish local root certificate trust.

---

## 📋 Installation
1. Download `SCUM_Chat_Translator_v2.0.0.zip`.
2. Extract to any directory.
3. (Optional) Run `install_cert.bat` once to eliminate Windows Defender SmartScreen warnings.
4. Launch `SCUM_Chat_Translator.exe`.
