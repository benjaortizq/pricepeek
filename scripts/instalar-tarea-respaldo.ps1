param(
    [ValidatePattern('^([01]?[0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$Hora = '03:17'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backupScript = Join-Path $PSScriptRoot 'respaldo-postgres.ps1'
if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) {
    throw "No se encontró el script de respaldo: $backupScript"
}

$parts = $Hora.Split(':')
$at = (Get-Date).Date.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
if ($at -le (Get-Date)) { $at = $at.AddDays(1) }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$backupScript`" -ProjectRoot `"$projectRoot`""
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'PricePeek - Respaldo PostgreSQL diario' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Genera un respaldo local diario de PostgreSQL y conserva los siete más recientes.' -Force | Out-Null

Write-Output "Tarea instalada. Se ejecutará diariamente a las $Hora (hora local) mientras tu sesión de Windows esté abierta."
Write-Output "Para correrla ahora: Start-ScheduledTask -TaskName 'PricePeek - Respaldo PostgreSQL diario'"
Write-Output "Para quitarla: Unregister-ScheduledTask -TaskName 'PricePeek - Respaldo PostgreSQL diario' -Confirm:`$false"
