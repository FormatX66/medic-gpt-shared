# Medic SSH setup - run this in PowerShell
mkdir "$env:USERPROFILE\.ssh" -Force
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/FormatX66/medic-gpt-shared/main/laptop/inbox/medic-ssh-key.txt" -OutFile "$env:USERPROFILE\.ssh\authorized_keys"
Write-Host "Done. Medic can now SSH in."
