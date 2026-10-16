# 闲鱼卖家工作台 · 依赖安装（Windows 10/11）
# 做的事：建 Python 虚拟环境 + 装依赖 + 下载 PocketBase 二进制 + 检查 Node
$ErrorActionPreference = 'Stop'
$ROOT   = Split-Path $PSScriptRoot -Parent
$ASSIST = Join-Path $ROOT 'assistant'
$JXC    = Join-Path $ROOT 'jxc'
$VENV   = Join-Path $ASSIST '.venv'
$PB_VER = '0.40.5'

Write-Host '===== 闲鱼卖家工作台 · 安装依赖 =====' -ForegroundColor Cyan

# ---- 1) Python ----
$py = $null
foreach ($c in @('python', 'py')) {
    try { $v = & $c --version 2>$null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch { }
}
if (-not $py) { throw '未找到 Python：请安装 Python 3.10+（https://www.python.org/downloads/），安装时勾选 Add to PATH' }
Write-Host "[1/4] Python: $(& $py --version)"

# ---- 2) 虚拟环境 + 依赖 ----
if (-not (Test-Path (Join-Path $VENV 'Scripts\python.exe'))) {
    Write-Host '[2/4] 创建虚拟环境 assistant\.venv ...'
    & $py -m venv $VENV
}
$vpy = Join-Path $VENV 'Scripts\python.exe'
Write-Host '[2/4] 安装 Python 依赖（国内镜像）...'
& $vpy -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
& $vpy -m pip install -r (Join-Path $ASSIST 'requirements.txt') -i https://pypi.tuna.tsinghua.edu.cn/simple
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败：检查网络后重试' }
Write-Host '[2/4] 依赖 OK'

# ---- 3) Node ----
$node = $null
foreach ($c in @((Join-Path $env:ProgramFiles 'nodejs\node.exe'), 'C:\Program Files (x86)\nodejs\node.exe')) {
    if (Test-Path $c) { $node = $c; break }
}
if (-not $node) {
    try { $null = & node --version; $node = 'node' } catch { }
}
if ($node) { Write-Host "[3/4] Node: $(& $node --version)" }
else { Write-Host '[3/4] 警告：未找到 Node.js ——「AI 开单」功能需要它，请安装 https://nodejs.org/' -ForegroundColor Yellow }

# ---- 4) PocketBase ----
$pbExe = Join-Path $JXC 'pocketbase.exe'
if (Test-Path $pbExe) {
    Write-Host '[4/4] PocketBase 已存在，跳过'
} else {
    Write-Host "[4/4] 下载 PocketBase v$PB_VER（windows-amd64）..."
    $zip = Join-Path $env:TEMP "pb_$PB_VER.zip"
    $urls = @(
        "https://github.com/pocketbase/pocketbase/releases/download/v$PB_VER/pocketbase_${PB_VER}_windows_amd64.zip",
        "https://gh-proxy.com/https://github.com/pocketbase/pocketbase/releases/download/v$PB_VER/pocketbase_${PB_VER}_windows_amd64.zip",
        "https://mirror.ghproxy.com/https://github.com/pocketbase/pocketbase/releases/download/v$PB_VER/pocketbase_${PB_VER}_windows_amd64.zip"
    )
    $ok = $false
    foreach ($u in $urls) {
        try {
            Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing -TimeoutSec 120
            if ((Get-Item $zip).Length -gt 5MB) { $ok = $true; break }
        } catch { Write-Host "  镜像不通：$u" -ForegroundColor DarkGray }
    }
    if (-not $ok) { throw 'PocketBase 下载失败：请手动下载解压到 jxc\ 目录（见 README）' }
    $tmp = Join-Path $env:TEMP "pb_$PB_VER"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    Copy-Item (Join-Path $tmp 'pocketbase.exe') $pbExe -Force
    Write-Host '[4/4] PocketBase 就位'
}

Write-Host ''
Write-Host '安装完成 ✅  下一步：双击 setup\首次配置.bat 完成初始化' -ForegroundColor Green
