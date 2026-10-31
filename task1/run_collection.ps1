param(
    [switch]$Offline,
    [switch]$SkipOfficial,
    [switch]$SkipCtrip,
    [switch]$SkipXhs,
    [switch]$RetryFailed,
    [switch]$Force,
    [ValidateRange(1, 10000)]
    [int]$PerPlatform = 25,
    [string]$PythonExe = 'python',
    [string]$NodeExe = 'node'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
# 原生命令输出按 UTF-8 解码，避免中文被控制台代码页破坏。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Push-Location $PSScriptRoot
$transcriptStarted = $false
$exitCode = 0

function Show-Stage {
    param([string]$Name, [string]$Detail, [bool]$Done, [bool]$WillRun)
    $state = '未完成'
    if ($Done) { $state = '已完成' }
    $action = '执行'
    if (-not $WillRun) { $action = '跳过' }
    Write-Host ('  {0,-10} {1,-20} {2,-8} {3}' -f $Name, $Detail, $state, $action)
}

function Get-StageStatus {
    & $PythonExe scripts/stage_status.py $PerPlatform > $null
    if ($LASTEXITCODE -ne 0) { throw '阶段状态检查失败。' }
    return Get-Content 'data/crawl/stage_state.json' -Encoding UTF8 -Raw | ConvertFrom-Json
}

function Show-Progress {
    param($Status)
    Write-Host ('  [进度] 官方 {0} | 携程 {1} | 小红书 {2}' -f $Status.official.detail, $Status.ctrip.detail, $Status.xiaohongshu.detail)
}

try {
    New-Item -ItemType Directory -Force -Path 'logs', 'data/crawl', 'data/raw' > $null
    $runLog = Join-Path $PSScriptRoot ('logs/collection_{0}_{1}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'), ([guid]::NewGuid().ToString('N').Substring(0,8)))
    Start-Transcript -LiteralPath $runLog > $null
    $transcriptStarted = $true
    Write-Host "运行日志：$runLog"

    # 完成度由数据本身推导，删除或损坏数据后不会误判为已完成。
    # 状态从脚本写出的 JSON 文件读取，不经标准输出，避免编码转换破坏中文。
    $status = Get-StageStatus

    $needOfficial = (-not $SkipOfficial) -and (($status.official.done -eq $false) -or $Force)
    $needCtrip = (-not $SkipCtrip) -and (($status.ctrip.done -eq $false) -or $Force)
    $needXhs = (-not $SkipXhs) -and (-not $Offline) -and (($status.xiaohongshu.done -eq $false) -or $Force)

    Write-Host ''
    Write-Host '阶段状态：'
    Show-Stage '官方来源' $status.official.detail $status.official.done $needOfficial
    Show-Stage '携程' $status.ctrip.detail $status.ctrip.done $needCtrip
    Show-Stage '小红书' $status.xiaohongshu.detail $status.xiaohongshu.done $needXhs
    Write-Host ''

    # 各阶段串行执行。直接调用可让输出实时可见、$LASTEXITCODE 立即可读，
    # 且 Ctrl+C 能连子进程一起终止，不会留下孤儿进程继续写数据。
    if ($needOfficial) {
        $officialArgs = @('scripts/crawl_official.py')
        if ($Offline) { $officialArgs += '--offline' }
        Write-Host '--- 官方来源 开始 ---'
        & $PythonExe @officialArgs
        $code = $LASTEXITCODE
        Write-Host ("--- 官方来源 结束，退出码 {0} ---" -f $code)
        if ($code -ne 0) { throw ("官方来源采集失败，退出码 {0}。" -f $code) }
        Show-Progress (Get-StageStatus)
        Write-Host ''
    }

    if ($needCtrip) {
        $ctripArgs = @('scripts/crawl_ctrip_ranked.py', '--area', 'all', '--max-pages', '120', '--pool-size', [string][Math]::Max(35, $PerPlatform + 10))
        if ($Offline) { $ctripArgs += '--offline' }
        if ($RetryFailed) { $ctripArgs += '--retry-failed' }
        Write-Host '--- 携程 开始 ---'
        & $PythonExe @ctripArgs
        $code = $LASTEXITCODE
        Write-Host ("--- 携程 结束，退出码 {0} ---" -f $code)
        if ($code -ne 0) { throw ("携程采集失败，退出码 {0}。" -f $code) }
        Show-Progress (Get-StageStatus)
        Write-Host ''
    }

    if ($needXhs) {
        $xhsArgs = @('scripts/crawl_xiaohongshu.mjs', '--area', 'all', '--target', [string]($PerPlatform + 10))
        if ($RetryFailed) { $xhsArgs += '--retry-failed' }
        Write-Host '--- 小红书 开始 ---'
        & $NodeExe @xhsArgs
        $code = $LASTEXITCODE
        Write-Host ("--- 小红书 结束，退出码 {0} ---" -f $code)
        if ($code -ne 0) { throw ("小红书采集失败，退出码 {0}。" -f $code) }
        Show-Progress (Get-StageStatus)
        Write-Host ''
    }

    Write-Host '--- 汇总 开始 ---'
    & $PythonExe scripts/select_collection.py --per-platform $PerPlatform
    $code = $LASTEXITCODE
    Write-Host ("--- 汇总 结束，退出码 {0} ---" -f $code)
    if ($code -ne 0) { throw '采集尚有缺额或快照问题，请查看 data/collected/collection_summary.json。' }

    $final = Get-StageStatus
    Write-Host ''
    Write-Host '最终状态：'
    Write-Host ('  官方来源  {0}' -f $final.official.detail)
    Write-Host ('  携程      {0}' -f $final.ctrip.detail)
    Write-Host ('  小红书    {0}' -f $final.xiaohongshu.detail)
    Write-Host ''
    Write-Host '采集完成，结果见 data/collected/。'
} catch {
    Write-Host ''
    Write-Host ('执行失败：' + $_.Exception.Message) -ForegroundColor Red
    $exitCode = 1
} finally {
    if ($transcriptStarted) { Stop-Transcript > $null }
    Pop-Location
}
exit $exitCode
