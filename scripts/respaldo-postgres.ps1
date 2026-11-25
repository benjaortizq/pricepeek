param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Keep = 7
)

$ErrorActionPreference = 'Stop'

if ($Keep -lt 1) {
    throw 'Keep debe ser al menos 1.'
}

$envFile = Join-Path $ProjectRoot '.env'
$backupDir = Join-Path $ProjectRoot 'backups/postgres'
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "No se encontró el archivo de configuración: $envFile"
}

$settings = @{}
foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $settings[$Matches[1]] = $value
    }
}

foreach ($key in @('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT')) {
    if (-not $settings.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($settings[$key])) {
        throw "Falta configurar $key en .env."
    }
}

$pgDump = Get-Command 'pg_dump' -ErrorAction SilentlyContinue
$pgDumpPath = if ($pgDump) { $pgDump.Source } else { $null }
if (-not $pgDumpPath) {
    $postgresRoots = @('C:\Program Files\PostgreSQL', 'C:\Program Files (x86)\PostgreSQL')
    $foundPgDumps = foreach ($root in $postgresRoots) {
        if (Test-Path -LiteralPath $root -PathType Container) {
            Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending | ForEach-Object {
                $candidate = Join-Path $_.FullName 'bin\pg_dump.exe'
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidate }
            }
        }
    }
    $pgDumpPath = $foundPgDumps | Select-Object -First 1
    if (-not $pgDumpPath) {
        throw 'No se encontró pg_dump. Instala las herramientas de línea de comandos de PostgreSQL y verifica que pg_dump esté en PATH.'
    }
}

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmssZ')
$finalFile = Join-Path $backupDir "pricepeek-$timestamp.dump"
$partialFile = "$finalFile.partial"

$previousPassword = $env:PGPASSWORD
$previousSslMode = $env:PGSSLMODE
try {
    $env:PGPASSWORD = $settings['DB_PASSWORD']
    $env:PGSSLMODE = if ($settings.ContainsKey('DB_SSLMODE') -and $settings['DB_SSLMODE']) { $settings['DB_SSLMODE'] } else { 'require' }

    $dumpArguments = @(
        "--host=$($settings['DB_HOST'])",
        "--port=$($settings['DB_PORT'])",
        "--username=$($settings['DB_USER'])",
        "--dbname=$($settings['DB_NAME'])",
        '--format=custom',
        '--no-password',
        "--file=$partialFile"
    )
    & $pgDumpPath @dumpArguments
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump terminó con código $LASTEXITCODE. No se modificaron los respaldos anteriores."
    }
    if (-not (Test-Path -LiteralPath $partialFile -PathType Leaf) -or (Get-Item -LiteralPath $partialFile).Length -eq 0) {
        throw 'pg_dump no produjo un archivo de respaldo válido.'
    }

    Move-Item -LiteralPath $partialFile -Destination $finalFile
    Write-Output "Respaldo creado: $finalFile"

    $oldBackups = @(Get-ChildItem -LiteralPath $backupDir -Filter 'pricepeek-*.dump' -File | Sort-Object LastWriteTimeUtc -Descending | Select-Object -Skip $Keep)
    foreach ($oldBackup in $oldBackups) {
        Remove-Item -LiteralPath $oldBackup.FullName -Force
        Write-Output "Respaldo antiguo eliminado: $($oldBackup.Name)"
    }
}
finally {
    Remove-Item -LiteralPath $partialFile -Force -ErrorAction SilentlyContinue
    if ($null -eq $previousPassword) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue } else { $env:PGPASSWORD = $previousPassword }
    if ($null -eq $previousSslMode) { Remove-Item Env:PGSSLMODE -ErrorAction SilentlyContinue } else { $env:PGSSLMODE = $previousSslMode }
}
