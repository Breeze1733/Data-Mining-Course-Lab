param(
    [string]$PythonExe = '',
    [string]$Task1Dir = '',
    [string]$InputDir = '',
    [string]$Config = '',
    [switch]$SkipPrepare,
    [switch]$NoWordcloud,
    [switch]$SkipIter1,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'
$Task2Root = $PSScriptRoot
$RepoRoot = Split-Path -Parent $Task2Root

if (-not $PythonExe) {
    $candidate = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) {
        $PythonExe = $candidate
    } else {
         $task1Python = Join-Path $RepoRoot 'task1\.venv\Scripts\python.exe'
        $PythonExe = if (Test-Path -LiteralPath $task1Python) { $task1Python } else { 'python' }
    }
}
if (-not $Config) {
    $candidate = Join-Path $Task2Root 'config.json'
    if (Test-Path -LiteralPath $candidate) { $Config = $candidate }
}
if ($Config -and -not [System.IO.Path]::IsPathRooted($Config)) {
    $Config = Join-Path $Task2Root $Config
}
if ($Config) { $Config = (Resolve-Path -LiteralPath $Config).Path }

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

Push-Location $Task2Root
try {
    $configArgs = @()
    if ($Config) { $configArgs = @('--config', $Config) }

    $paths = & $PythonExe 'src\config.py' '--print-paths' @configArgs | Out-String | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "config.py --print-paths 失败" }
    $sources = & $PythonExe 'src\config.py' '--print-sources' @configArgs | Out-String | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "config.py --print-sources 失败" }

    $resourcesDir = $paths.resources_dir
    $outputsDir = $paths.outputs_dir
    $iter1Dir = $paths.iter1_dir
    $chartsDir = $paths.charts_dir
    $qcDir = $paths.qc_dir
    $manifestPath = $paths.manifest
    $iter1Baseline = $paths.iter1_baseline_dir
    $logsDir = $paths.logs_dir
    $chosenInput = if ($InputDir) { $InputDir } else { $paths.input_dir }

    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
    $log = Join-Path $logsDir ('task2_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
    Start-Transcript -Path $log -Force | Out-Null
} catch {
    Pop-Location
    throw
}

function Invoke-Py {
    param([string[]]$PyArgs)
    & $PythonExe @PyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python 命令失败 (exit=$LASTEXITCODE): $PythonExe $($PyArgs -join ' ')"
    }
}

try {
    Write-Host "task2 root : $Task2Root"
    Write-Host "python     : $PythonExe"
    Write-Host "inputs     : $chosenInput"
    Write-Host "config     : $Config"

    if ($RunTests) {
        Invoke-Py @('-m', 'unittest', 'discover', '-s', 'src', '-p', 'test_*.py', '-v')
    }

    try {
        Invoke-Py @('-c', 'import jieba, matplotlib')
    } catch {
        Write-Host "缺少依赖。请先运行:"
        Write-Host "  uv pip install --python `"$PythonExe`" -r requirements.txt"
        throw
    }
    if (-not $NoWordcloud) {
        try {
            Invoke-Py @('-c', 'import wordcloud')
        } catch {
            Write-Warning "wordcloud 不可用，自动降级为柱状图。"
            $NoWordcloud = $true
        }
    }

    $missingRequired = @()
    $missingOptional = @()
    foreach ($property in $sources.PSObject.Properties) {
        $spec = $property.Value
        $path = Join-Path $chosenInput ([string]$spec.file)
        if (-not (Test-Path -LiteralPath $path)) {
            if ($spec.required -eq $true) { $missingRequired += $path } else { $missingOptional += $path }
        }
    }
    if (($missingRequired.Count + $missingOptional.Count) -gt 0 -and -not $SkipPrepare) {
        Write-Host "inputs 缺失，尝试从 task1 生成快照..."
        $prepareArgs = @{ Config = $Config; InputDir = $chosenInput; PythonExe = $PythonExe }
        if ($Task1Dir) { $prepareArgs['Task1Dir'] = $Task1Dir }
        & (Join-Path $Task2Root 'prepare_inputs.ps1') @prepareArgs
        if ($LASTEXITCODE -ne 0) { throw "prepare_inputs.ps1 失败" }
    }
    $missingRequired = @()
    foreach ($property in $sources.PSObject.Properties) {
        $spec = $property.Value
        $path = Join-Path $chosenInput ([string]$spec.file)
        if (-not (Test-Path -LiteralPath $path) -and $spec.required -eq $true) {
            $missingRequired += $path
        }
    }
    if ($missingRequired.Count -gt 0) {
        throw "缺少必选输入文件: $($missingRequired -join ', ')。请运行 prepare_inputs.ps1 或提供 -InputDir。"
    }

    if (-not $SkipIter1) {
        Write-Host "`n=== iter1 baseline ==="
        Invoke-Py (@('src\build_baseline.py', '--input-dir', $chosenInput, '--output-dir', $iter1Baseline) + $configArgs)
        Invoke-Py (@('src\extract_entities.py', '--input-dir', $chosenInput, '--resources', $iter1Baseline, '--iteration', 'iter1', '--output-dir', $iter1Dir) + $configArgs)
        Invoke-Py (@('src\stats_entities.py', '--entities', (Join-Path $iter1Dir 'entities.json'), '--output-dir', (Join-Path $iter1Dir 'stats')) + $configArgs)
        Invoke-Py (@('src\visualize_entities.py', '--entities', (Join-Path $iter1Dir 'entities.json'), '--charts-dir', (Join-Path $iter1Dir 'charts'), '--no-wordcloud') + $configArgs)
    }

    Write-Host "`n=== iter2 final ==="
    Invoke-Py (@('src\extract_entities.py', '--input-dir', $chosenInput, '--resources', $resourcesDir, '--iteration', 'iter2', '--output-dir', $outputsDir) + $configArgs)
    Invoke-Py (@('src\stats_entities.py', '--entities', (Join-Path $outputsDir 'entities.json'), '--output-dir', $outputsDir) + $configArgs)
    $chartArgs = @('src\visualize_entities.py', '--entities', (Join-Path $outputsDir 'entities.json'), '--charts-dir', $chartsDir) + $configArgs
    if ($NoWordcloud) { $chartArgs += '--no-wordcloud' }
    Invoke-Py -PyArgs $chartArgs

    $iter1Entities = Join-Path $iter1Dir 'entities.json'
    if (Test-Path -LiteralPath $iter1Entities) {
        Invoke-Py (@('src\compare_iterations.py', '--iter1', $iter1Entities, '--iter2', (Join-Path $outputsDir 'entities.json'), '--output-dir', $outputsDir, '--charts-dir', $chartsDir) + $configArgs)
    }

    Invoke-Py (@('src\qc_entities.py', '--input-dir', $chosenInput, '--entities', (Join-Path $outputsDir 'entities.json'), '--output-dir', $qcDir, '--resources', $resourcesDir) + $configArgs)
    Invoke-Py @('src\build_definition.py', '--input', (Join-Path $resourcesDir 'entity_definition.csv'), '--output-dir', $outputsDir)
    Invoke-Py (@('src\build_manifest.py', '--outputs', $outputsDir, '--inputs', $chosenInput, '--output', $manifestPath) + $configArgs)

    Write-Host "`n完成：$outputsDir\entities.json、$chartsDir、$qcDir"
} finally {
    Stop-Transcript | Out-Null
    Pop-Location
}
