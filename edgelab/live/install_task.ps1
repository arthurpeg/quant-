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
$ps1 = Join-Path $PSScriptRoot "run_forever.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "edgelab-live" -Action $action -Trigger $trigger `
  -Settings $settings -Description "edgelab.live 3-brick forward-test supervisor" -Force
Write-Host "Registered scheduled task 'edgelab-live' (runs run_forever.ps1 at logon)."
Write-Host "Start it now without logging off:  Start-ScheduledTask -TaskName edgelab-live"
