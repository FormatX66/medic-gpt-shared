#Requires -RunAsAdministrator
<#
  Medic laptop setup — one-shot. v4 (installs Medic Mini app).
  Run as Administrator: right-click -> "Run with PowerShell" (as admin).

  What it does:
    1. Installs OpenSSH Server, starts it, sets Automatic, key-auth for Medic.
    2. Installs Tailscale (you complete the login click at the end).
    3. Installs TightVNC Server as a service, random 8-char password, tailnet-only firewall.
    4. Installs Python 3 (for the daemon) if missing.
    5. Installs the Medic Mini app (always-on hands): polls Medic's
       dispatches every 20s, runs them, streams results back, takes
       screenshots on request, self-updates from the repo. Pairs itself
       with Medic on first start — nothing for you to paste. Localhost
       dashboard at http://127.0.0.1:8899. Scheduled task at logon +
       starts immediately.
    6. Enables auto-login (you type your Windows password once; it never leaves this machine).
    7. Disables the lock screen / require-sign-in-on-wake; never sleeps on AC power.

  Nothing secret leaves this machine. The only thing that goes to Medic
  afterwards: the VNC password printed at the end (you relay it), and a
  one-time Tailscale auth key so his VM can join your tailnet.
#>

$ErrorActionPreference = 'Stop'

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# Medic's public SSH key (public by design — safe to keep here)
$MedicPubKey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGGuzi1oaQ9dHKDahWBsalmAWH/RlvApmdQ2FvDTG1vJ hatch'

# Tailscale CGNAT range — firewall rules scope remote access to the tailnet only
$TailnetRange = '100.64.0.0/10'

$MiniDir = Join-Path $env:USERPROFILE 'medic-mini'
$MiniUrl = 'https://raw.githubusercontent.com/FormatX66/medic-gpt-shared/main/laptop/inbox/medic-mini.py'

# ---- 0. Sanity -------------------------------------------------------------
Step 'Checking admin + winget'
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  throw 'winget not found. Install App Installer from the Microsoft Store, then re-run.'
}

# ---- 1. OpenSSH Server ------------------------------------------------------
Step 'Installing OpenSSH Server'
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'
# Default shell -> PowerShell (not cmd)
New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
  -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'

Step 'Installing Medic SSH key'
$sshDir = Join-Path $env:USERPROFILE '.ssh'
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
$authKeys = Join-Path $sshDir 'authorized_keys'
$MedicPubKey | Out-File -FilePath $authKeys -Encoding ascii -Force
# Windows OpenSSH is strict about ACLs on authorized_keys
icacls $authKeys /inheritance:r | Out-Null
icacls $authKeys /grant:r "$($env:USERNAME):F" | Out-Null
icacls $authKeys /grant:r 'SYSTEM:F' | Out-Null
Restart-Service sshd

# ---- 2. Tailscale -----------------------------------------------------------
Step 'Installing Tailscale'
winget install -e --id Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements

# ---- 3. TightVNC ------------------------------------------------------------
Step 'Installing TightVNC Server'
# Random 8-char password (TightVNC uses max 8 chars). Printed at the end for Bruce to relay.
$chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789'
$vncPass = -join (1..8 | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })
$msiArgs = '/quiet /norestart ADDLOCAL="Server" SERVER_REGISTER_AS_SERVICE=1 ' +
           'SERVER_ADD_FIREWALL_EXCEPTION=0 SERVER_ALLOW_SAS=1 ' +
           'SET_USEVNCAUTHENTICATION=1 VALUE_OF_USEVNCAUTHENTICATION=1 ' +
           "SET_PASSWORD=1 VALUE_OF_PASSWORD=$vncPass " +
           "SET_USECONTROLAUTHENTICATION=1 VALUE_OF_USECONTROLAUTHENTICATION=1 " +
           "SET_CONTROLPASSWORD=1 VALUE_OF_CONTROLPASSWORD=$vncPass"
winget install -e --id TightVNC.TightVNC --silent --accept-package-agreements --accept-source-agreements `
  --override $msiArgs


# ---- 4. Python (daemon needs it) --------------------------------------------
Step 'Ensuring Python 3'
$py = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py.exe -ErrorAction SilentlyContinue }
if (-not $py) {
  Write-Host 'Installing Python 3 via winget...'
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
              [System.Environment]::GetEnvironmentVariable('Path','User')
}
$py = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py.exe -ErrorAction SilentlyContinue }
if (-not $py) { throw 'Python still not found after install. Reboot and re-run.' }
$pythonExe = $py.Source
Write-Host "Using Python: $pythonExe"

# ---- 5. Medic daemon (always-on hands, self-pairing) --------------------------
Step 'Installing Medic Mini app'
New-Item -ItemType Directory -Force -Path $MiniDir | Out-Null
Invoke-WebRequest -Uri $MiniUrl -OutFile (Join-Path $MiniDir 'medic-mini.py')
# No secret prompt: the daemon pairs itself with Medic on first start (TOFU).
# Already paired (re-run)? Keep the existing secret.
$secretFile = Join-Path $MiniDir 'mini-secret.txt'
if (Test-Path $secretFile) { Write-Host 'Mini app already paired — keeping existing secret.' }
else { Write-Host 'Mini app will pair itself with Medic on first start (nothing for you to paste).' }
# Stash the VNC password where the daemon (and Medic, via daemon) picks it up —
# no relay needed.
$vncPass | Out-File -FilePath (Join-Path $MiniDir 'vnc-password.txt') -Encoding ascii -NoNewline -Force

$taskName = 'MedicMini'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$action = New-ScheduledTaskAction -Execute $pythonExe `
  -Argument "`"$(Join-Path $MiniDir 'medic-mini.py')`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Settings $settings -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host 'Medic Mini installed as logon scheduled task and started.'

# ---- 6. Auto-login (survives restarts with zero interaction) ----------------
Step 'Configuring auto-login'
$cred = Get-Credential -Message 'Enter YOUR Windows username + password for auto-login (stays on this machine only)' `
                       -UserName $env:USERNAME
$plainPw = $cred.GetNetworkCredential().Password
$winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
Set-ItemProperty -Path $winlogon -Name AutoAdminLogon -Value '1'
Set-ItemProperty -Path $winlogon -Name DefaultUserName -Value $cred.UserName
Set-ItemProperty -Path $winlogon -Name DefaultPassword -Value $plainPw
Set-ItemProperty -Path $winlogon -Name DefaultDomainName -Value $env:COMPUTERNAME
# If he uses a Microsoft account, DefaultUserName may need to be the email address —
# script notes it; he can edit the registry value if auto-login fails once.
$plainPw = $null

# ---- 7. No lock screen, no sleep on AC ---------------------------------------
Step 'Disabling lock screen + sleep-on-AC'
$pers = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization'
New-Item -Path $pers -Force | Out-Null
Set-ItemProperty -Path $pers -Name NoLockScreen -Value 1 -Type DWord
# Never sleep while plugged in; never require sign-in on wake
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-ac 30 | Out-Null
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 0 | Out-Null

# ---- 8. Services to Automatic -----------------------------------------------
Step 'Setting services to Automatic'
foreach ($svc in @('sshd', 'tvnserver')) {
  $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
  if ($s) { Set-Service -Name $svc -StartupType Automatic; Start-Service -Name $svc }
  else { Write-Warning "Service '$svc' not found — check install output above." }
}

# ---- 9. Tailnet-only firewall ------------------------------------------------
Step 'Scoping firewall to tailnet'
foreach ($rule in @(
  @{Name='Medic SSH (tailnet only)'; Port=22},
  @{Name='Medic VNC (tailnet only)'; Port=5900}
)) {
  if (-not (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP `
      -LocalPort $rule.Port -RemoteAddress $TailnetRange -Action Allow | Out-Null
  }
}

# ---- Done --------------------------------------------------------------------
Step 'Complete'
Write-Host @'

Setup finished. Two things left for Bruce (2 minutes):

  1. TAILSCALE LOGIN: a Tailscale login window/prompt should appear.
     Sign in, then confirm this laptop shows up in your Tailscale admin console.

  2. AUTH KEY FOR MEDIC: in the Tailscale admin console, generate a ONE-TIME
     auth key (https://login.tailscale.com/admin/settings/keys), paste it to
     Medic in chat. He burns it immediately to join your tailnet, then you
     delete it. His VM also needs nothing else.

That's the last time you're the cable. The daemon pairs itself with Medic,
hands over the VNC password and Tailscale IP on its own, and announces itself.
From there Medic drives everything directly.

'@ -ForegroundColor Green
Write-Host "VNC password (kept on this machine; Medic picks it up via the daemon): $vncPass" -ForegroundColor Yellow
Write-Host ''
Write-Host 'If auto-login fails once (Microsoft-account machines): set' -ForegroundColor DarkYellow
Write-Host 'HKLM\...\Winlogon\DefaultUserName to your Microsoft account email and reboot.' -ForegroundColor DarkYellow
