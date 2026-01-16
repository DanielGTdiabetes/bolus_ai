<#
.SYNOPSIS
    Migrates database from Neon to NAS (local or remote) using Docker.
.DESCRIPTION
    This script performs a pg_dump from a Neon database and restores it to a target NAS database.
    It uses Docker containers to run pg_dump and psql, avoiding the need for local tool installation.
.PARAMETER NeonUrl
    The connection string for the source Neon database.
.PARAMETER TargetUrl
    The connection string for the target NAS database.
#>

param (
    [string]$NeonUrl = $env:NEON_DB_URL,
    [string]$TargetUrl = $env:TARGET_DB_URL
)

# Configuration
$ContainerImage = "postgres:15-alpine"
$Date = Get-Date -Format "yyyyMMdd"
$DumpFile = "neon_backup_$Date.sql"
$DumpPath = Join-Path $PWD $DumpFile

Write-Host "=== Starting Migration: Neon -> NAS (Dockerized/PowerShell) ===" -ForegroundColor Cyan

# 1. Validation
if ([string]::IsNullOrWhiteSpace($NeonUrl) -or $NeonUrl -like "*replace_me*") {
    Write-Error "Please set NEON_DB_URL environment variable or pass -NeonUrl parameter."
    exit 1
}
if ([string]::IsNullOrWhiteSpace($TargetUrl)) {
    Write-Error "Please set TARGET_DB_URL environment variable or pass -TargetUrl parameter."
    exit 1
}

# 2. Dump from Neon
Write-Host "1. Dumping data from Neon (using temporary postgres container)..." -ForegroundColor Yellow

# Note: We mount current directory to /tmp_dump inside container
try {
    docker run --rm `
        -v "${PWD}:/tmp_dump" `
        $ContainerImage `
        pg_dump "$NeonUrl" --no-owner --no-acl --clean --if-exists -f "/tmp_dump/$DumpFile"
}
catch {
    Write-Error "Docker failed to start. Is Docker Desktop running?"
    exit 1
}

if (-not (Test-Path $DumpPath)) {
    Write-Error "Dump failed: File was not created at $DumpPath"
    exit 1
}

$FileSize = (Get-Item $DumpPath).Length
if ($FileSize -lt 100) {
    Write-Error "Dump failed: File is too small ($FileSize bytes). Check permissions or URL."
    exit 1
}

Write-Host "✅ Dump successful: $DumpFile ($FileSize bytes)" -ForegroundColor Green

# 3. Restore to NAS
Write-Host "2. Restoring to NAS ($TargetUrl)..." -ForegroundColor Yellow

try {
    # We use Get-Content to pipe the file into the docker container's stdin
    # '-i' allows interactive, but we pipe input.
    # Note: On PowerShell, piping binary/text can be tricky, but SQL text usually works ok.
    # We use 'cmd /c' trick or direct redirection if possible, but 'Get-Content | docker' works for text.
    
    # Better approach for docker run with file input in PowerShell:
    # Use standard redirection < is harder, so we mount the file again and use psql -f
    
    docker run --rm `
        -e "PGPASSWORD=unused" `
        -v "${PWD}:/tmp_dump" `
        $ContainerImage `
        psql "$TargetUrl" -f "/tmp_dump/$DumpFile"
        
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Migration Complete! Data is now in your local NAS." -ForegroundColor Green
    } else {
        Write-Error "❌ Restore failed (Exit Code: $LASTEXITCODE)."
        exit 1
    }
}
catch {
    Write-Error "Restore process failed: $_"
    exit 1
}

# 4. Cleanup
Write-Host "3. Cleaning up..." -ForegroundColor Yellow
Remove-Item $DumpPath -Force
Write-Host "✅ Done." -ForegroundColor Cyan
