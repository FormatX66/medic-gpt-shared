#Requires -RunAsAdministrator
<#
  Medic laptop setup — one-shot.
  Run as Administrator: right-click -> "Run with PowerShell" (as admin).

  What it does:
    1. Installs OpenSSH Server, starts it, sets Automatic, key-auth for Medic.
    2. Installs Tailscale (you complete the login click at the end).
    3. Installs TightVNC Server as a service, random 8-char password, tailnet-only firewall.
    4. Enables auto-login (you type your Windows password once; it never leaves this machine).
    5. Disables the lock screen / require-sign-in-on-wake; never sleeps on AC power.

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

# ---- 4. Auto-login (survives restarts with zero interaction) ----------------
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

# ---- 5. No lock screen, no sleep on AC ---------------------------------------
Step 'Disabling lock screen + sleep-on-AC'
$pers = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization'
New-Item -Path $pers -Force | Out-Null
Set-ItemProperty -Path $pers -Name NoLockScreen -Value 1 -Type DWord
# Never sleep while plugged in; never require sign-in on wake
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-ac 30 | Out-Null
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_NONE CONSOLELOCK 0 | Out-Null

# ---- 6. Services to Automatic -----------------------------------------------
Step 'Setting services to Automatic'
foreach ($svc in @('sshd', 'tvnserver')) {
  $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
  if ($s) { Set-Service -Name $svc -StartupType Automatic; Start-Service -Name $svc }
  else { Write-Warning "Service '$svc' not found — check install output above." }
}

# ---- 7. Tailnet-only firewall ------------------------------------------------
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

Then tell Medic: the VNC password below (relay once in chat) + the laptop's
Tailscale IP (run `tailscale ip -4` in PowerShell).

'@ -ForegroundColor Green
Write-Host "VNC password (relay to Medic once): $vncPass" -ForegroundColor Yellow
Write-Host ''
Write-Host 'If auto-login fails once (Microsoft-account machines): set' -ForegroundColor DarkYellow
Write-Host 'HKLM\...\Winlogon\DefaultUserName to your Microsoft account email and reboot.' -ForegroundColor DarkYellow
