# 闲鱼卖家工作台 · 统一启动器
# 用法：工作台.bat [start|stop|restart|status|open]，无参数进交互菜单
# 管理范围：进销存 PocketBase(8090) + AI开单(8091) + 闲鱼助手（各店，端口读 assistant/shops/*/config.json）

param([ValidateSet('menu','start','stop','restart','status','open')][string]$Action = 'menu')

$ErrorActionPreference = 'Continue'

# ── 目录（相对本脚本自动定位，仓库整体可搬） ──────────────
$ROOT       = Split-Path $PSScriptRoot -Parent
$ASSIST_DIR = Join-Path $ROOT 'assistant'
$JXC_DIR    = Join-Path $ROOT 'jxc'
# ──────────────────────────────────────────────────────────

$PB_PORT  = 8090
$AI_PORT  = 8091
$MANIFEST = Join-Path $JXC_DIR 'pb_public\workbench\services.json'
$PANEL_URL = "http://127.0.0.1:$PB_PORT/workbench/"

function Resolve-Exe([string[]]$cands, [string]$fallback) {
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path } }
    return $fallback
}

$NODE = Resolve-Exe @(
    (Join-Path $ROOT 'runtime\node\node.exe'),
    (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
    'C:\Program Files (x86)\nodejs\node.exe'
) 'node'

# python 解释器：便携版 runtime 优先，其次 assistant/.venv，再次仓库 .venv，最后系统 python
$PY = Resolve-Exe @(
    (Join-Path $ROOT 'runtime\python\python.exe'),
    (Join-Path $ASSIST_DIR '.venv\Scripts\python.exe'),
    (Join-Path $ROOT '.venv\Scripts\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
) 'python'

function Test-Port([int]$Port, [int]$TimeoutMs = 500) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch { return $false } finally { $client.Close() }
}

function Get-PidOnPort([int]$Port) {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess } else { return $null }
}

function Get-Shops {
    $list = @()
    $dir = Join-Path $ASSIST_DIR 'shops'
    if (Test-Path $dir) {
        foreach ($d in (Get-ChildItem $dir -Directory | Sort-Object Name)) {
            $cfgPath = Join-Path $d.FullName 'config.json'
            if (Test-Path $cfgPath) {
                try {
                    $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    $list += [pscustomobject]@{ Name = $d.Name; Port = [int]$cfg.port; Display = [string]$cfg.display_name }
                } catch { Write-Host "  [警告] $($d.Name) 配置读取失败，跳过" -ForegroundColor Yellow }
            }
        }
    }
    return @($list)
}

function Wait-Port([int]$Port, [int]$Seconds) {
    $tries = [int]($Seconds / 0.7)
    for ($i = 0; $i -lt $tries; $i++) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return (Test-Port $Port)
}

function Update-Manifest {
    $items = @()
    $items += @{ key = 'pb'; label = '进销存'; port = $PB_PORT; url = "http://127.0.0.1:$PB_PORT/"; health = "http://127.0.0.1:$PB_PORT/api/health"; ok = (Test-Port $PB_PORT); pid = (Get-PidOnPort $PB_PORT) }
    $items += @{ key = 'ai'; label = 'AI开单'; port = $AI_PORT; url = "http://127.0.0.1:$AI_PORT/health"; health = "http://127.0.0.1:$AI_PORT/health"; ok = (Test-Port $AI_PORT); pid = (Get-PidOnPort $AI_PORT) }
    foreach ($s in Get-Shops) {
        $items += @{ key = "xy-$($s.Name)"; label = ("闲鱼-" + $s.Name); port = $s.Port; url = "http://127.0.0.1:$($s.Port)/"; health = "http://127.0.0.1:$($s.Port)/status"; ok = (Test-Port $s.Port); pid = (Get-PidOnPort $s.Port) }
    }
    $obj = @{ generated_at = (Get-Date).ToString('s'); services = $items }
    $dir = Split-Path $MANIFEST -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($MANIFEST, ($obj | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
}

function Start-PB {
    if (Test-Port $PB_PORT) { Write-Host '  [进销存] 已在运行，跳过' -ForegroundColor DarkGreen; return }
    $exe = Join-Path $JXC_DIR 'pocketbase.exe'
    if (-not (Test-Path $exe)) {
        Write-Host '  [进销存] 缺少 pocketbase.exe —— 请先双击 setup\安装依赖.bat 下载' -ForegroundColor Red
        return
    }
    Write-Host '  [进销存] 启动中...' -ForegroundColor Yellow
    Start-Process -FilePath $exe -ArgumentList 'serve', '--http=0.0.0.0:8090' -WorkingDirectory $JXC_DIR -WindowStyle Hidden
}

function Start-AISvc {
    if (Test-Port $AI_PORT) { Write-Host '  [AI开单] 已在运行，跳过' -ForegroundColor DarkGreen; return }
    Write-Host '  [AI开单] 启动中...' -ForegroundColor Yellow
    Start-Process -FilePath $NODE -ArgumentList (Join-Path $JXC_DIR 'ai\jxc-ai.mjs') -WorkingDirectory (Join-Path $JXC_DIR 'ai') -WindowStyle Hidden
}

function Start-Shops {
    foreach ($s in Get-Shops) {
        if (Test-Port $s.Port) { Write-Host "  [闲鱼-$($s.Name)] 已在运行，跳过" -ForegroundColor DarkGreen; continue }
        Write-Host "  [闲鱼-$($s.Name)] 启动中...（约 8 秒）" -ForegroundColor Yellow
        Start-Process -FilePath $PY -ArgumentList 'main.py', '--shop', $s.Name -WorkingDirectory $ASSIST_DIR -WindowStyle Hidden
        Start-Sleep -Seconds 8
    }
}

function Show-Status {
    Write-Host ''
    Write-Host '=== 服务状态 ===' -ForegroundColor Cyan
    $rows = @()
    $rows += @{ Label = '进销存'; Port = $PB_PORT }
    $rows += @{ Label = 'AI开单'; Port = $AI_PORT }
    foreach ($s in Get-Shops) { $rows += @{ Label = "闲鱼-$($s.Name)"; Port = $s.Port } }
    foreach ($r in $rows) {
        $procId = Get-PidOnPort $r.Port
        $pad = $r.Label.PadRight(14)
        if ($procId) {
            Write-Host ("  [OK] $pad http://127.0.0.1:$($r.Port)  (PID $procId)") -ForegroundColor Green
        } else {
            Write-Host ("  [--] $pad http://127.0.0.1:$($r.Port)  未启动") -ForegroundColor Red
        }
    }
    Write-Host ''
    Write-Host "  工作台主页：$PANEL_URL" -ForegroundColor DarkGray
}

function Do-Start {
    Write-Host '=== 启动卖家工作台 ===' -ForegroundColor Cyan
    Start-PB
    Start-AISvc
    Start-Shops
    Write-Host ''
    Write-Host '等待服务就绪...'
    [void](Wait-Port $PB_PORT 20)
    [void](Wait-Port $AI_PORT 15)
    foreach ($s in Get-Shops) { [void](Wait-Port $s.Port 30) }
    Update-Manifest
    Show-Status
}

function Do-Stop {
    Write-Host '=== 停止卖家工作台 ===' -ForegroundColor Cyan
    $n = 0
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match '--shop' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }
    Write-Host "  [闲鱼] 已停止 $n 个进程"
    $n2 = 0
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'jxc-ai\.mjs' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n2++ }
    Write-Host "  [AI开单] 已停止 $n2 个进程"
    $n3 = 0
    Get-Process pocketbase -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue; $n3++ }
    Write-Host "  [进销存] 已停止 $n3 个进程"
    Update-Manifest
}

function Do-Restart {
    Do-Stop
    Start-Sleep -Seconds 3
    Do-Start
}

function Do-Open {
    Start-Process $PANEL_URL
}

function Show-Menu {
    while ($true) {
        Write-Host ''
        Write-Host '===== 卖家工作台 =====' -ForegroundColor Cyan
        Write-Host ' 1) 启动全部服务（进销存 + AI开单 + 闲鱼助手）'
        Write-Host ' 2) 停止全部服务'
        Write-Host ' 3) 查看服务状态'
        Write-Host ' 4) 重启全部服务'
        Write-Host ' 5) 打开工作台页面'
        Write-Host ' 0) 退出'
        $c = Read-Host '请选择'
        switch ($c) {
            '1' { Do-Start }
            '2' { Do-Stop }
            '3' { Update-Manifest; Show-Status }
            '4' { Do-Restart }
            '5' { Do-Open }
            '0' { return }
            default { Write-Host '无效选项' -ForegroundColor Red }
        }
    }
}

switch ($Action) {
    'start'   { Do-Start }
    'stop'    { Do-Stop }
    'restart' { Do-Restart }
    'status'  { Update-Manifest; Show-Status }
    'open'    { Do-Open }
    'menu'    { Show-Menu }
}
