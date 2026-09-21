# Medic SSH setup - paste into PowerShell and run
mkdir "C:\Users\bruce\.ssh" -Force
"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGGuzi1oaQ9dHKDahWBsalmAWH/RlvApmdQ2FvDTG1vJ hatch" | Out-File "C:\Users\bruce\.ssh\authorized_keys" -Encoding ascii -Force
icacls "C:\Users\bruce\.ssh\authorized_keys" /inheritance:r
icacls "C:\Users\bruce\.ssh\authorized_keys" /grant:r "bruce:F"
Write-Host "Done."
