# =============================================================================
# edgelab.live SUPERVISOR — keeps the runner alive on Windows.
# Restarts the runner if it CRASHES; stops cleanly on user interrupt or a blown
# account. To STOP it at any time: create the file edgelab\live\_out\STOP
# (or just close this window / Ctrl+C).
#
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File edgelab\live\run_forever.ps1
# =============================================================================
$ErrorActionPreference = "Continue"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $repo
$outDir = Join-Path $PSScriptRoot "_out"
New-Item -ItemType Directory -Force $outDir | Out-Null
$log  = Join-Path $outDir "supervisor.log"
$stop = Join-Path $outDir "STOP"

# Resolve a REAL python interpreter. NEVER the bare 'python' (on this box it's the
# Microsoft Store app-execution alias, which spawns a stub + a detached child -> two
# processes and flaky supervision). Prefer the py launcher, then a pythoncore install.
$PYEXE = $null; $PYPRE = @()
# Prefer the DIRECT pythoncore interpreter. The Store 'py.exe'/'python.exe' aliases are
# flaky when called with splatted args from a script -> intermittent "can't open file py.exe".
$cand = Get-ChildItem "$env:LOCALAPPDATA\Python\pythoncore-*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
if ($cand) { $PYEXE = $cand.FullName; $PYPRE = @() }
elseif (Get-Command py.exe -ErrorAction SilentlyContinue) { $PYEXE = (Get-Command py.exe).Source; $PYPRE = @("-3") }
else { $PYEXE = "python"; $PYPRE = @() }

function Log($m) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $m"
  Write-Host $line
  Add-Content -Path $log -Value $line
}

if (Test-Path $stop) { Remove-Item $stop -Force }   # clear a stale stop flag

# CONTRAT AVEC LE RUNNER (ajoute 2026-08-17). La sortie 75 (UPDATE) est un contrat a deux :
# le runner sort, NOUS faisons le git pull + la relance. Sans nous, cette sortie est
# DEFINITIVE. Le runner ne peut pas deviner s'il a un superviseur -- son parent est un
# powershell.exe dans les deux cas -- donc on le lui DIT ici. `_check_update` refuse de
# sortir en 75 quand cette variable est absente et continue de trader sur le commit
# courant. Contexte : superviseur mort le 12/08 a 23:41, runner relance a la main pendant
# 5 jours, `auto_update: true` -> le prochain push aurait eteint le book en silence.
$env:EDGELAB_SUPERVISED = "1"

$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
# Empreinte de CE script au moment ou PowerShell l'a parse. Le `git reset --hard` ci-dessous
# peut mettre a jour run_forever.ps1 SUR LE DISQUE, mais PowerShell ne relit jamais un script
# en cours d'execution : le superviseur continuerait donc de tourner sur l'ancienne version
# en croyant etre a jour. C'est exactement ce qui s'est passe le 2026-08-17 -- la ligne
# EDGELAB_SUPERVISED est arrivee sur le disque et le processus vivant ne la posait pas, donc
# le runner se croyait non supervise. On ne peut pas se relancer sans risquer une boucle de
# spawn sur un VPS de trading, alors on le DIT, fort.
$selfHash = (Get-FileHash $PSCommandPath -Algorithm SHA256).Hash
$selfWarned = $false
Log "supervisor started (repo: $repo) | python: $PYEXE $($PYPRE -join ' ') | git: $hasGit"
while ($true) {
  if (Test-Path $stop) { Log "STOP file found -> supervisor exiting"; Remove-Item $stop -Force; break }

  # --- AUTO-UPDATE: sync to origin/main, but roll back if the new code won't import
  # (keeps trading on the last-good version if a push is broken). config_live.yaml is
  # untracked/gitignored -> git never touches it.
  if ($hasGit -and (Test-Path (Join-Path $repo ".git"))) {
    $prev = (git -C $repo rev-parse HEAD 2>$null)
    git -C $repo fetch --quiet origin main 2>$null
    git -C $repo reset --hard origin/main 2>$null | Out-Null
    & $PYEXE @PYPRE -c "import edgelab.live.runner" 2>$null
    if ($LASTEXITCODE -ne 0 -and $prev) {
      Log "pulled code FAILS to import -> rolling back to $($prev.Substring(0,7))"
      git -C $repo reset --hard $prev 2>$null | Out-Null
    } else {
      Log "on commit $(git -C $repo rev-parse --short HEAD 2>$null)"
    }
    if (-not $selfWarned) {
      $nowHash = (Get-FileHash $PSCommandPath -Algorithm SHA256).Hash
      if ($nowHash -ne $selfHash) {
        $selfWarned = $true
        Log "*** run_forever.ps1 A CHANGE sur le disque et CE processus tourne encore sur"
        Log "*** l'ancienne version (PowerShell ne relit pas un script en cours). Le runner"
        Log "*** peut donc voir un environnement perime -- p.ex. EDGELAB_SUPERVISED absent,"
        Log "*** ce qui lui fait desactiver auto_update. RELANCER CE SCRIPT une fois de plus"
        Log "*** pour appliquer sa propre mise a jour (le fichier a jour est deja la)."
      }
    }
  }

  Log "launching runner"
  & $PYEXE @PYPRE -m edgelab.live.runner
  $code = $LASTEXITCODE
  if ($code -eq 42) { Log "runner exited 42 (ACCOUNT FAILED) -> NOT restarting"; break }
  if ($code -eq 0)  { Log "runner exited 0 (clean/interrupt) -> NOT restarting"; break }
  if ($code -eq 75) { Log "runner exited 75 (UPDATE) -> pulling + relaunching now"; continue }
  Log "runner CRASHED (code $code) -> restarting in 15s"
  Start-Sleep -Seconds 15
}
Log "supervisor stopped"
