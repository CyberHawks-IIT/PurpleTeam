#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Pre-Sysprep script – prepares a Windows 11 image for Proxmox cloud-init and Ansible.
.DESCRIPTION
    Run this BEFORE sysprep /generalize. It:
      1. Enables and configures WinRM for Ansible connectivity
      2. Configures PowerShell remoting
      3. Opens firewall rules for WinRM
      4. Sets execution policy for Ansible scripts
      5. Installs OpenSSH Server
      6. Installs cloudbase-init (reads Proxmox cloud-init drive on first boot
         to configure user, password, IP, DNS, and SSH keys per clone)
      7. Cleans temp/log artifacts so the captured image is lean
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step { param([string]$Msg) Write-Host "`n>>> $Msg" -ForegroundColor Cyan }

# ─── 1. Enable & configure WinRM ────────────────────────────────────────────
Write-Step "Configuring WinRM for Ansible"

# Start the service and set to auto-start
Set-Service -Name WinRM -StartupType Automatic
Start-Service -Name WinRM

# Create an HTTP listener if one doesn't exist
$httpListener = Get-ChildItem WSMan:\localhost\Listener -ErrorAction SilentlyContinue |
    Where-Object { $_.Keys -contains 'Transport=HTTP' }

if (-not $httpListener) {
    Write-Host "  Creating WinRM HTTP listener..."
    winrm create winrm/config/Listener?Address=*+Transport=HTTP | Out-Null
}

# Configure WinRM settings Ansible expects
winrm set winrm/config/service '@{AllowUnencrypted="true"}'   | Out-Null
winrm set winrm/config/service/auth '@{Basic="true"}'         | Out-Null
winrm set winrm/config/service '@{MaxMemoryPerShellMB="1024"}'| Out-Null
winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'  | Out-Null

# Increase envelope size for large Ansible payloads
winrm set winrm/config '@{MaxEnvelopeSizekb="8192"}' | Out-Null

Write-Host "  WinRM configured." -ForegroundColor Green

# ─── 2. PowerShell Remoting ─────────────────────────────────────────────────
Write-Step "Enabling PowerShell Remoting"
Enable-PSRemoting -Force -SkipNetworkProfileCheck | Out-Null
Write-Host "  PS Remoting enabled." -ForegroundColor Green

# ─── 3. Firewall rules ─────────────────────────────────────────────────────
Write-Step "Configuring firewall rules for WinRM"

$rules = @(
    @{ Name = 'WinRM-HTTP-In'; Port = 5985; Protocol = 'TCP'; Direction = 'Inbound' }
    @{ Name = 'WinRM-HTTPS-In'; Port = 5986; Protocol = 'TCP'; Direction = 'Inbound' }
)

foreach ($r in $rules) {
    $existing = Get-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Set-NetFirewallRule -Name $r.Name -Enabled True | Out-Null
    } else {
        New-NetFirewallRule `
            -Name        $r.Name `
            -DisplayName $r.Name `
            -Direction   $r.Direction `
            -Protocol    $r.Protocol `
            -LocalPort   $r.Port `
            -Action      Allow `
            -Profile     Any | Out-Null
    }
    Write-Host "  Firewall rule '$($r.Name)' enabled." -ForegroundColor Green
}

# ─── 4. Execution policy ───────────────────────────────────────────────────
Write-Step "Setting PowerShell execution policy to RemoteSigned"
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Force -Scope LocalMachine
Write-Host "  Execution policy set." -ForegroundColor Green

# ─── 5. Install OpenSSH Server (optional – enables Ansible SSH transport) ──
#Write-Step "Installing OpenSSH Server (optional SSH transport for Ansible)"
#$sshCapability = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
#if ($sshCapability.State -ne 'Installed') {
#    Add-WindowsCapability -Online -Name $sshCapability.Name | Out-Null
#    Set-Service -Name sshd -StartupType Automatic
#    Start-Service sshd
#    Write-Host "  OpenSSH Server installed and started." -ForegroundColor Green
#} else {
#    Write-Host "  OpenSSH Server already installed." -ForegroundColor Yellow
#}

# ─── 6. Install cloudbase-init ─────────────────────────────────────────────
Write-Step "Installing cloudbase-init (Proxmox cloud-init support for Windows)"

$cbInitMsi  = "$env:TEMP\CloudbaseInitSetup.msi"
$cbInitUrl  = "https://cloudbase.it/downloads/CloudbaseInitSetup_Stable_x64.msi"

Write-Host "  Downloading cloudbase-init..."
(New-Object System.Net.WebClient).DownloadFile($cbInitUrl, $cbInitMsi)

Write-Host "  Installing cloudbase-init (unattended)..."
$installArgs = @(
    '/i', $cbInitMsi,
    '/qn',
    '/norestart',
    'LOGGINGLEVEL=5'
)
$proc = Start-Process msiexec.exe -ArgumentList $installArgs -Wait -PassThru
if ($proc.ExitCode -notin @(0, 3010)) {
    throw "cloudbase-init installer exited with code $($proc.ExitCode)"
}

Remove-Item $cbInitMsi -Force -ErrorAction SilentlyContinue
Write-Host "  cloudbase-init installed." -ForegroundColor Green

# ─── 7. Cleanup temp files / logs ──────────────────────────────────────────
Write-Step "Cleaning temp files and logs"

$cleanPaths = @(
    "$env:TEMP\*",
    "C:\Windows\Temp\*",
    "C:\Windows\Logs\CBS\*.log",
    "C:\Windows\Logs\DISM\*.log",
    "C:\Windows\SoftwareDistribution\Download\*"
)

foreach ($p in $cleanPaths) {
    Remove-Item -Path $p -Recurse -Force -ErrorAction SilentlyContinue
}

# Clear event logs
wevtutil el | ForEach-Object { wevtutil cl $_ 2>$null }

Write-Host "  Cleanup complete." -ForegroundColor Green

# ─── 8. Quick WinRM smoke test ─────────────────────────────────────────────
Write-Step "Running WinRM smoke test"
$result = winrm enumerate winrm/config/listener 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  WinRM listener is responding." -ForegroundColor Green
} else {
    Write-Warning "  WinRM listener test returned an error -- review manually."
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Pre-sysprep complete. Ready to generalize." -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan
