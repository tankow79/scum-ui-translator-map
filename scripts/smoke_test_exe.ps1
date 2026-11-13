# Starts a built executable in --smoke-test mode (isolated data folder) and fails unless it reports OK.
# Usage: pwsh scripts/smoke_test_exe.ps1 dist/SCUM_Chat_Translator.exe [dist/other.exe ...]
param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Exes)
$ErrorActionPreference = "Stop"
$base = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
foreach ($exe in $Exes) {
    $data = Join-Path $base ("smoke_" + [guid]::NewGuid())
    New-Item -ItemType Directory -Force $data | Out-Null
    $env:SCUM_DATA_DIR = $data
    $p = Start-Process $exe -ArgumentList "--smoke-test" -PassThru
    if (-not $p.WaitForExit(120000)) { taskkill /PID $p.Id /T /F | Out-Null; throw "$exe did not finish its self-test" }
    $reportFile = Join-Path $data "smoke-result.txt"
    $report = if (Test-Path $reportFile) { (Get-Content $reportFile -Raw).Trim() } else { "" }
    if ($p.ExitCode -ne 0 -or $report -notmatch "^OK") { throw "$exe failed its self-test (exit $($p.ExitCode)): $report" }
    Write-Host "$exe self-test: $report"
}
