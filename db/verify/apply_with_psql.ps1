param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [string]$PsqlPath = 'psql',

    [ValidateRange(0, 999)]
    [int]$FromMigration = 0,

    [switch]$SchemaOnly
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$migrationDirectory = Join-Path $repositoryRoot 'db\migrations'

$migrationFiles = Get-ChildItem -LiteralPath $migrationDirectory -Filter '*.sql' -File | Sort-Object Name
if ($migrationFiles.Count -eq 0) { throw 'No migrations found.' }
for ($index = 0; $index -lt $migrationFiles.Count; $index++) {
    if ($migrationFiles[$index].Name -notmatch ('^{0:D3}_[a-z0-9_]+\.sql$' -f $index)) {
        throw "Migration sequence must be contiguous from 000: $($migrationFiles[$index].Name)"
    }
}
$selectedMigrations = @($migrationFiles | Where-Object { [int]$_.Name.Substring(0, 3) -ge $FromMigration })
if ($selectedMigrations.Count -eq 0) { throw "No migrations at or after $FromMigration." }
Write-Host "Catalog: $($migrationFiles.Count) migrations; applying from $FromMigration."
# This repository has no database migration ledger. Incremental application is
# explicit: operators must verify the existing schema before selecting the start.
# Migrations fail on duplicate objects; do not silently replay historical DDL.

foreach ($migration in $selectedMigrations) {
    Write-Host "Applying $($migration.Name)"
    & $PsqlPath $DatabaseUrl -X -v ON_ERROR_STOP=1 -f $migration.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Migration failed: $($migration.Name)"
    }
}

$verificationFiles = @('verify_schema.sql')
if (-not $SchemaOnly) { $verificationFiles += 'temporal_scenarios.sql' }
foreach ($verificationFile in $verificationFiles) {
    $verificationPath = Join-Path $PSScriptRoot $verificationFile
    Write-Host "Running $verificationFile"
    & $PsqlPath $DatabaseUrl -X -v ON_ERROR_STOP=1 -f $verificationPath
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed: $verificationFile"
    }
}

Write-Host 'Migrations and verification completed successfully.'
