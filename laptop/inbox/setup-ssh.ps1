# Medic SSH setup - paste into PowerShell (as Administrator) and run
# User location
mkdir "C:\Users\bruce\.ssh" -Force
"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGGuzi1oaQ9dHKDahWBsalmAWH/RlvApmdQ2FvDTG1vJ hatch" | Out-File "C:\Users\bruce\.ssh\authorized_keys" -Encoding ascii -Force
icacls "C:\Users\bruce\.ssh" /inheritance:r /grant:r "bruce:F" /grant:r "SYSTEM:F"
icacls "C:\Users\bruce\.ssh\authorized_keys" /inheritance:r /grant:r "bruce:F" /grant:r "SYSTEM:F"
# Admin location (Windows OpenSSH uses this for admin accounts)
"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGGuzi1oaQ9dHKDahWBsalmAWH/RlvApmdQ2FvDTG1vJ hatch" | Out-File "C:\ProgramData\ssh\administrators_authorized_keys" -Encoding ascii -Force
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r /grant:r "SYSTEM:F" /grant:r "Administrators:F"
Restart-Service sshd
Write-Host "Done."
