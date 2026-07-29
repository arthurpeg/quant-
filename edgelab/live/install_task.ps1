# =============================================================================
# Register a Windows Scheduled Task that auto-starts the edgelab.live supervisor
# at logon and keeps it running. Run this ONCE (normal user is fine, no admin):
#   powershell -NoProfile -ExecutionPolicy Bypass -File edgelab\live\install_task.ps1
#
# Remove later with:  Unregister-ScheduledTask -TaskName "edgelab-live" -Confirm:$false
#
# PREREQUISITES for headless restart:
#  * MT5 (Pepperstone demo) must auto-login. Either leave the terminal running, or
#    set  mt5_path:  in config_live.yaml so mt5.initialize() can launch it, and make
#    sure the terminal has "save account/password" enabled so it connects on its own.
# =============================================================================
# Registering a scheduled task needs an ELEVATED session. Self-elevate if we aren't.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Host "Not elevated -> relaunching as administrator (accept the UAC prompt)..."
  Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  exit
}

$ps1 = Join-Path $PSScriptRoot "run_forever.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)
try {
  Register-ScheduledTask -TaskName "edgelab-live" -Action $action -Trigger $trigger `
    -Settings $settings -Description "edgelab.live 3-brick forward-test supervisor" -Force -ErrorAction Stop
  Write-Host "OK: registered scheduled task 'edgelab-live' (runs run_forever.ps1 at logon)."
  Write-Host "Start it now without logging off:  Start-ScheduledTask -TaskName edgelab-live"
} catch {
  Write-Host "FAILED to register the task: $($_.Exception.Message)"
  Write-Host "Open PowerShell as Administrator (right-click -> Run as administrator) and re-run this script."
  exit 1
}
Read-Host "Done. Press Enter to close"
