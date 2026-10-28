param(
    [switch]$Offline,
    [switch]$SkipXhs,
    [switch]$SkipCtrip,
    [switch]$RetryFailed,
    [ValidateRange(1, 10000)]
    [int]$PerPlatform = 25,
    [string]$PythonExe = 'python',
    [string]$NodeExe = 'node'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $PSScriptRoot
$transcriptStarted = $false
try {
    New-Item -ItemType Directory -Force -Path 'logs', 'research', 'data/raw' > $null
    $runLog = Join-Path $PSScriptRoot ('logs/collection_{0}_{1}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'), ([guid]::NewGuid().ToString('N').Substring(0,8)))
    Start-Transcript -LiteralPath $runLog > $null
    $transcriptStarted = $true
    Write-Host "运行日志：$runLog"
    $officialArgs = @('src/crawl_official.py')
    if ($Offline) { $officialArgs += '--offline' }
    & $PythonExe @officialArgs
    if ($LASTEXITCODE -ne 0) { throw '官方来源采集执行失败。' }
    if (-not $SkipCtrip) {
        $ctripArgs = @('src/crawl_ctrip_ranked.py', '--area', 'all', '--max-pages', '120', '--pool-size', [string][Math]::Max(35, $PerPlatform + 10))
        if ($Offline) { $ctripArgs += '--offline' }
        if ($RetryFailed) { $ctripArgs += '--retry-failed' }
        & $PythonExe @ctripArgs
        if ($LASTEXITCODE -ne 0) { throw '携程采集执行失败。' }
    }
    if (-not $Offline -and -not $SkipXhs) {
        $xhsArgs = @('src/crawl_xiaohongshu.mjs', '--area', 'all', '--target', [string]($PerPlatform + 10))
        if ($RetryFailed) { $xhsArgs += '--retry-failed' }
        & $NodeExe @xhsArgs
        if ($LASTEXITCODE -ne 0) { throw '小红书采集尚未成功，可登录后再次运行；已保存结果不会丢失。' }
    }
    & $PythonExe src/select_collection.py --per-platform $PerPlatform
    if ($LASTEXITCODE -ne 0) { throw '采集尚有缺额或快照问题，请查看 data/collected/collection_summary.json。' }
} finally {
    if ($transcriptStarted) { Stop-Transcript > $null }
    Pop-Location
}
