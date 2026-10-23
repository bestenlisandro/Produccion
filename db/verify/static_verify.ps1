$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$migrationDirectory = Join-Path $repositoryRoot 'db\migrations'
$dictionaryPath = Join-Path $repositoryRoot 'docs\08-diccionario-datos-v1.md'

$migrationFiles = Get-ChildItem -LiteralPath $migrationDirectory -Filter '*.sql' -File | Sort-Object Name
if ($migrationFiles.Count -ne 12) { throw "Expected 12 migration files, found $($migrationFiles.Count)." }

$sql = ($migrationFiles | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }) -join "`n"
$tableMatches = [regex]::Matches($sql, '(?m)^CREATE TABLE ([a-z_]+\.[a-z_]+)')
$sqlTables = @($tableMatches | ForEach-Object { $_.Groups[1].Value })
if ($sqlTables.Count -ne 87) { throw "Expected 87 CREATE TABLE statements, found $($sqlTables.Count)." }
if (($sqlTables | Sort-Object -Unique).Count -ne 87) { throw 'Duplicate table declarations found.' }

$dictionaryTables = @(Get-Content -LiteralPath $dictionaryPath | ForEach-Object {
    if ($_ -match '^### D[0-9]{3} `([^`]+)`') { $matches[1] }
})
$difference = Compare-Object ($sqlTables | Sort-Object) ($dictionaryTables | Sort-Object)
if ($difference) { throw "Migration/dictionary table mismatch:`n$($difference | Out-String)" }

$schemaCount = [regex]::Matches($sql, '(?m)^CREATE SCHEMA IF NOT EXISTS (core|capacity|production|planning|execution|portal|integration|audit);').Count
if ($schemaCount -ne 8) { throw "Expected 8 schemas, found $schemaCount." }

foreach ($migration in $migrationFiles) {
    $content = Get-Content -LiteralPath $migration.FullName -Raw
    if ($content -notmatch '(?m)^BEGIN;' -or $content -notmatch '(?m)^COMMIT;') {
        throw "Migration lacks transaction boundary: $($migration.Name)"
    }
}

$fkMatches = [regex]::Matches($sql, 'FOREIGN KEY\s*\((?<child>[^\)]+)\)\s*REFERENCES\s+(?<target>[a-z_]+\.[a-z_]+)\s*\((?<parent>[^\)]+)\)', 'IgnoreCase')
$unsafeForeignKeys = @($fkMatches | Where-Object {
    $_.Groups['target'].Value -ne 'core.organizations' -and
    ($_.Groups['child'].Value -notmatch 'organization_id' -or $_.Groups['parent'].Value -notmatch 'organization_id')
})
if ($unsafeForeignKeys.Count -ne 0) { throw "$($unsafeForeignKeys.Count) tenant-unsafe FK declarations found." }

if ($sql -match '(?i)ON DELETE CASCADE') { throw 'Destructive ON DELETE CASCADE found.' }

$tenantTablesWithoutOrganization = @()
foreach ($table in $sqlTables) {
    if ($table -eq 'core.organizations') { continue }
    $pattern = 'CREATE TABLE ' + [regex]::Escape($table) + '\s*\((?<body>[\s\S]*?)\n\);'
    $match = [regex]::Match($sql, $pattern)
    if (-not $match.Success -or $match.Groups['body'].Value -notmatch '\borganization_id\b') {
        $tenantTablesWithoutOrganization += $table
    }
}
if ($tenantTablesWithoutOrganization.Count -ne 0) { throw "Tables without organization_id: $($tenantTablesWithoutOrganization -join ', ')" }

$secondaryIndexFamilies = [regex]::Matches($sql, '(?m)^CREATE INDEX ix[0-9]{2}_').Count
if ($secondaryIndexFamilies -ne 28) { throw "Expected 28 approved secondary index families, found $secondaryIndexFamilies." }

$exclusions = [regex]::Matches($sql, 'EXCLUDE USING gist', 'IgnoreCase').Count
if ($exclusions -ne 7) { throw "Expected 7 exclusion constraints, found $exclusions." }

$declaredNamedConstraints = [regex]::Matches($sql, '\bCONSTRAINT\s+[a-zA-Z0-9_]+', 'IgnoreCase').Count
$declaredIndexes = [regex]::Matches($sql, '\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+[a-zA-Z0-9_]+', 'IgnoreCase').Count
$declaredForeignKeys = $fkMatches.Count

[pscustomobject]@{
    migrations = $migrationFiles.Count
    schemas = $schemaCount
    tables = $sqlTables.Count
    named_constraints = $declaredNamedConstraints
    foreign_keys = $declaredForeignKeys
    declared_indexes = $declaredIndexes
    approved_secondary_index_families = $secondaryIndexFamilies
    exclusion_constraints = $exclusions
    tenant_unsafe_foreign_keys = $unsafeForeignKeys.Count
    destructive_cascades = 0
} | Format-List

Write-Host 'Static migration verification passed.'
