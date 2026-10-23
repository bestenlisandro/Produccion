param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [string]$PsqlPath = 'psql'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$migrationDirectory = Join-Path $repositoryRoot 'db\migrations'

$migrationFiles = Get-ChildItem -LiteralPath $migrationDirectory -Filter '*.sql' -File | Sort-Object Name
if ($migrationFiles.Count -ne 12) {
    throw "Expected 12 migrations, found $($migrationFiles.Count)."
}

foreach ($migration in $migrationFiles) {
    Write-Host "Applying $($migration.Name)"
    & $PsqlPath $DatabaseUrl -X -v ON_ERROR_STOP=1 -f $migration.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Migration failed: $($migration.Name)"
    }
}

foreach ($verificationFile in @('verify_schema.sql', 'temporal_scenarios.sql')) {
    $verificationPath = Join-Path $PSScriptRoot $verificationFile
    Write-Host "Running $verificationFile"
    & $PsqlPath $DatabaseUrl -X -v ON_ERROR_STOP=1 -f $verificationPath
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed: $verificationFile"
    }
}

Write-Host 'Migrations and verification completed successfully.'
