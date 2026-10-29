param(
    [string]$PythonExe = '',
    [string]$Task1Dir = '',
    [string]$InputDir = '',
    [string]$Config = ''
)

$ErrorActionPreference = 'Stop'
$Task2Root = $PSScriptRoot
$RepoRoot = Split-Path -Parent $Task2Root

if (-not $Config) {
    $candidate = Join-Path $Task2Root 'config.json'
    if (Test-Path -LiteralPath $candidate) { $Config = $candidate }
}
if ($Config) {
    if (-not [System.IO.Path]::IsPathRooted($Config)) {
        $Config = Join-Path $Task2Root $Config
    }
    $Config = (Resolve-Path -LiteralPath $Config).Path
}

function Resolve-PathValue {
    param([string]$Value, [string]$BaseDir)
    if ([System.IO.Path]::IsPathRooted($Value)) { return $Value }
    return (Join-Path $BaseDir $Value)
}

$configObject = $null
$configDir = $Task2Root
if ($Config -and (Test-Path -LiteralPath $Config)) {
    $configObject = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
    $configDir = Split-Path -Parent $Config
}

if (-not $Task1Dir) {
    if ($configObject -and $configObject.input.fallback_dirs -and $configObject.input.fallback_dirs.Count -gt 0) {
        $Task1Dir = Resolve-PathValue $configObject.input.fallback_dirs[0] $configDir
    } else {
        $Task1Dir = Join-Path $RepoRoot 'task1\data\processed'
    }
}
if (-not $InputDir) {
    if ($configObject -and $configObject.input.dir) {
        $InputDir = Resolve-PathValue $configObject.input.dir $configDir
    } else {
        $InputDir = Join-Path $Task2Root 'inputs'
    }
}
$Task1Dir = [System.IO.Path]::GetFullPath((Resolve-PathValue $Task1Dir $Task2Root))
$InputDir = [System.IO.Path]::GetFullPath((Resolve-PathValue $InputDir $Task2Root))

Write-Host "task1 processed: $Task1Dir"
Write-Host "task2 inputs   : $InputDir"
Write-Host "config         : $Config"

if (-not (Test-Path -LiteralPath $Task1Dir)) {
    throw "找不到 task1 预处理目录: $Task1Dir"
}

# The local branch commits a unified dataset; adapt it without changing task1 outputs.
$canonicalDataset = Join-Path $Task1Dir 'dataset_clean.jsonl'
if ((Test-Path -LiteralPath $canonicalDataset) -and -not (Test-Path -LiteralPath (Join-Path $Task1Dir 'tourist_routes_clean.jsonl'))) {
    if (-not $PythonExe) {
        $candidate = Join-Path $RepoRoot 'task1\.venv\Scripts\python.exe'
        $PythonExe = if (Test-Path -LiteralPath $candidate) { $candidate } else { 'python' }
    }
    $adaptedDir = Join-Path $Task2Root 'data\canonical_inputs'
    & $PythonExe -X utf8 (Join-Path $Task2Root 'src\prepare_canonical_inputs.py') --dataset $canonicalDataset --official-routes (Join-Path (Split-Path -Parent $Task1Dir) 'raw\official_routes.jsonl') --output-dir $adaptedDir
    if ($LASTEXITCODE -ne 0) { throw 'canonical input adaptation failed' }
    $Task1Dir = $adaptedDir
}

# 默认来源规格（无 config.json 或配置未声明 sources 时使用）
$sources = @{}
$sourceProps = $null
if ($configObject -and $configObject.input -and $configObject.input.sources) {
    $sourceProps = $configObject.input.sources.PSObject.Properties
}
if ($sourceProps) {
    foreach ($property in $sourceProps) {
        $sources[$property.Name] = $property.Value
    }
} else {
    $sources['tourist'] = [pscustomobject]@{ file = 'tourist_routes_clean.jsonl'; id_field = 'record_id'; accept_field = $null; required = $false }
    $sources['official_route'] = [pscustomobject]@{ file = 'official_routes_clean.jsonl'; id_field = 'route_id'; accept_field = $null; required = $false }
    $sources['official_document'] = [pscustomobject]@{ file = 'official_documents_clean.jsonl'; id_field = 'evidence_id'; accept_field = 'accepted'; required = $false }
}

New-Item -ItemType Directory -Force -Path $InputDir | Out-Null
$files = @()

foreach ($kind in ($sources.Keys | Sort-Object)) {
    $spec = $sources[$kind]
    $name = [string]$spec.file
    $source = Join-Path $Task1Dir $name
    if (-not (Test-Path -LiteralPath $source)) {
        if ($spec.required -eq $true) {
            throw "缺少必选输入: $source"
        }
        Write-Warning "缺少可选输入: $source"
        continue
    }
    $destination = Join-Path $InputDir $name
    Copy-Item -LiteralPath $source -Destination $destination -Force
    $hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLower()
    $item = Get-Item -LiteralPath $destination
    $records = 0
    $accepted = $null
    if ($name -like '*.jsonl') {
        $lines = @(Get-Content -LiteralPath $destination -Encoding UTF8 | Where-Object { $_.Trim().Length -gt 0 })
        $records = $lines.Count
        $acceptField = ''
        if ($spec.accept_field) { $acceptField = [string]$spec.accept_field }
        if ($acceptField -and $lines.Count -gt 0) {
            $first = $lines[0] | ConvertFrom-Json
            if ($first.PSObject.Properties.Name -contains $acceptField) {
                $accepted = 0
                foreach ($line in $lines) {
                    $row = $line | ConvertFrom-Json
                    if ($row.PSObject.Properties[$acceptField].Value -eq $true) { $accepted++ }
                }
            }
        }
    }
    $entry = [ordered]@{
        source_kind      = $kind
        id_field         = [string]$spec.id_field
        name             = $name
        bytes            = $item.Length
        sha256           = $hash
        records          = $records
        accepted_records = $accepted
    }
    $files += $entry
    Write-Host ("  {0,-36} {1,10} bytes  {2} records" -f $name, $item.Length, $records)
}

$qualityName = 'quality_report.json'
$pipelineVersion = 'unknown'
if ($configObject -and $configObject.input.quality_report) {
    $qualityName = [string]$configObject.input.quality_report
}
$qualitySource = Join-Path $Task1Dir $qualityName
if (Test-Path -LiteralPath $qualitySource) {
    Copy-Item -LiteralPath $qualitySource -Destination (Join-Path $InputDir $qualityName) -Force
    try {
        $quality = Get-Content -LiteralPath $qualitySource -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($quality.pipeline_version) { $pipelineVersion = [string]$quality.pipeline_version }
    } catch {
        Write-Warning "quality_report.json 解析失败，pipeline_version 记为 unknown"
    }
}

if ($files.Count -eq 0) {
    throw "没有复制任何输入文件，请检查 task1 预处理输出。"
}

$manifestName = 'manifest.json'
if ($configObject -and $configObject.input.manifest) {
    $manifestName = [string]$configObject.input.manifest
}
$manifest = [ordered]@{
    schema_version         = 'task2-input-manifest-1.0'
    created_at             = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    source_dir             = $Task1Dir
    task1_pipeline_version = $pipelineVersion
    note                   = 'task1/data/processed 的冻结快照；由 prepare_inputs.ps1 生成'
    files                  = $files
}
$json = $manifest | ConvertTo-Json -Depth 8
$manifestPath = Join-Path $InputDir $manifestName
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "manifest written: $manifestPath"
