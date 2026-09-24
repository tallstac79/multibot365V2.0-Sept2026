param(
  [string]$Adb = "C:\Users\WINDOWS11\Desktop\platform-tools\adb.exe",
  [string]$Serial = "R5CT61TE14Z"
)
$ErrorActionPreference = "Stop"
# Dedicated test-phone harness: clears Chrome app data (cookies/session), then opens Bet365 login.
& $Adb -s $Serial shell am force-stop com.android.chrome
& $Adb -s $Serial shell pm clear com.android.chrome
if ($LASTEXITCODE -ne 0) { throw "Could not clear Chrome app data" }
& $Adb -s $Serial shell am start -a android.intent.action.VIEW -d "https://www.bet365.com/#/HO/" com.android.chrome
if ($LASTEXITCODE -ne 0) { throw "Could not open Bet365 home" }
Write-Output "Intentional LOGGED_OUT state prepared on $Serial; Chrome cookies/app data cleared."
