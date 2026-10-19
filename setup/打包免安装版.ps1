# 闲鱼卖家工作台 · 免安装版打包脚本
# 产物：<OutDir>\xianyu-seller-workbench-portable-<Tag>.zip（内含便携 Python + Node + PocketBase + 全部代码）
# 用法：powershell -ExecutionPolicy Bypass -File setup\打包免安装版.ps1 [-Tag v1.0]
# 说明：打包机需要本机有 Python 3.13（只为收集依赖用；最终用户不需要装任何东西）
param(
    [string]$OutDir = "$PSScriptRoot\..",
    [string]$PyVer = '3.13.14',
    [string]$Tag = 'v1.0'
)
$ErrorActionPreference = 'Stop'
$ROOT = (Resolve-Path (Split-Path $PSScriptRoot -Parent)).Path
$NAME = 'xianyu-seller-workbench'
$BUILD = Join-Path $env:TEMP ("wb-portable-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$PKG = Join-Path $BUILD $NAME
New-Item -ItemType Directory -Path $PKG -Force | Out-Null
Write-Host "===== 打包免安装版 $Tag =====" -ForegroundColor Cyan
Write-Host "[构建目录] $BUILD"

# ---------- 1. 便携 Python（embeddable + 依赖） ----------
Write-Host '[1/6] 下载便携 Python ...'
$pyDir = Join-Path $PKG 'runtime\python'
New-Item -ItemType Directory -Path $pyDir -Force | Out-Null
$pyZip = Join-Path $BUILD 'python-embed.zip'
$pyUrls = @(
    "https://mirrors.huaweicloud.com/python/$PyVer/python-$PyVer-embed-amd64.zip",
    "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
)
$ok = $false
foreach ($u in $pyUrls) {
    try {
        Invoke-WebRequest -Uri $u -OutFile $pyZip -UseBasicParsing -TimeoutSec 180
        if ((Get-Item $pyZip).Length -gt 5MB) { $ok = $true; break }
    } catch { Write-Host "  下载失败：$u" -ForegroundColor DarkGray }
}
if (-not $ok) { throw '便携 Python 下载失败，检查网络' }
Expand-Archive -Path $pyZip -DestinationPath $pyDir -Force
$pth = Get-ChildItem (Join-Path $pyDir 'python*._pth') | Select-Object -First 1
$zipLine = ((Get-Content $pth.FullName) | Where-Object { $_ -match '\.zip\s*$' } | Select-Object -First 1)
if (-not $zipLine) { $zipLine = 'python313.zip' }
@($zipLine.Trim(), '.', 'Lib\site-packages', 'import site') | Set-Content $pth.FullName -Encoding ASCII
New-Item -ItemType Directory -Path (Join-Path $pyDir 'Lib\site-packages') -Force | Out-Null
# sitecustomize：embeddable 的 ._pth 不会把脚本目录加入 sys.path，这里补上（等价 venv 行为）
$sc = @'
# 便携版 Python 补丁：把当前工作目录加入 sys.path。
# embeddable 发行版的 ._pth 隔离机制不会像普通 Python 那样自动加入脚本目录，
# 导致 main.py 无法 import brain / kb 等同目录模块。此文件由 site 自动加载。
import os
import sys

try:
    _here = os.getcwd()
    if _here and _here not in sys.path:
        sys.path.insert(0, _here)
except Exception:
    pass
'@
[System.IO.File]::WriteAllText((Join-Path $pyDir 'Lib\site-packages\sitecustomize.py'), $sc, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "  便携 Python $PyVer 就位（$zipLine + sitecustomize）"

Write-Host '[2/6] 收集 Python 依赖（pip --target）...'
$sysPy = $null
foreach ($c in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'), 'python')) {
    try { & $c --version 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $sysPy = $c; break } } catch { }
}
if (-not $sysPy) { throw '打包机需要 Python 3.13（仅打包用）' }
$site = Join-Path $pyDir 'Lib\site-packages'
$mirrors = @('https://mirrors.aliyun.com/pypi/simple/', 'https://pypi.tuna.tsinghua.edu.cn/simple', 'https://pypi.org/simple')
$okDeps = $false
foreach ($m in $mirrors) {
    Write-Host "  尝试镜像：$m"
    & $sysPy -m pip install -r (Join-Path $ROOT 'assistant\requirements.txt') --target $site --no-cache-dir -i $m --quiet
    if ($LASTEXITCODE -eq 0) { $okDeps = $true; break }
}
if (-not $okDeps) { throw '依赖收集失败' }
& (Join-Path $pyDir 'python.exe') -c "import requests, websockets, qrcode, PIL, jieba, rank_bm25, numpy; print('  deps import ok')"
if ($LASTEXITCODE -ne 0) { throw '便携 Python 依赖自检失败' }

# ---------- 2. 便携 Node ----------
Write-Host '[3/6] 复制 node.exe ...'
$nodeSrc = @((Join-Path $env:ProgramFiles 'nodejs\node.exe'), 'C:\Program Files (x86)\nodejs\node.exe') |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $nodeSrc) { throw '未找到 node.exe（打包机需装 Node.js）' }
New-Item -ItemType Directory -Path (Join-Path $PKG 'runtime\node') -Force | Out-Null
Copy-Item $nodeSrc (Join-Path $PKG 'runtime\node\node.exe') -Force
& (Join-Path $PKG 'runtime\node\node.exe') -v | ForEach-Object { Write-Host "  node $_" }

# ---------- 3. 复制代码（排除隐私/数据） ----------
Write-Host '[4/6] 复制代码（排除 .git / 登录态 / 数据 / venv）...'
$rc = robocopy $ROOT $PKG /E /NFL /NDL /NJH /NJS `
    /XD "$ROOT\.git" "$ROOT\node_modules" "$ROOT\.venv" "$ROOT\assistant\.venv" `
        "$ROOT\jxc\pb_data" "$ROOT\assistant\shops" "$ROOT\jxc\android\out" "$ROOT\jxc\android\build" `
    /XF "软件配置.json" "session.json" "知识库.md" "补充知识.md" "kb-chunks.json" `
        "*.db" "*.db-wal" "*.db-shm" "*.log" "ai-config.json" "services.json" "*.jks" "*.apk"
if ($rc -ge 8) { throw "robocopy 失败（code $rc）" }
New-Item -ItemType Directory -Path (Join-Path $PKG 'assistant\shops') -Force | Out-Null
Set-Content (Join-Path $PKG 'assistant\shops\.gitkeep') '' -Encoding ASCII

# ---------- 4. PocketBase ----------
Write-Host '[5/6] 复制 pocketbase.exe ...'
$pbDst = Join-Path $PKG 'jxc\pocketbase.exe'
if (-not (Test-Path $pbDst)) {
    $pbSrc = Join-Path $ROOT 'jxc\pocketbase.exe'
    if (-not (Test-Path $pbSrc)) {
        $PB_VER = '0.40.5'
        $urls = @(
            "https://github.com/pocketbase/pocketbase/releases/download/v$PB_VER/pocketbase_${PB_VER}_windows_amd64.zip",
            "https://gh-proxy.com/https://github.com/pocketbase/pocketbase/releases/download/v$PB_VER/pocketbase_${PB_VER}_windows_amd64.zip"
        )
        $zip = Join-Path $BUILD 'pb.zip'
        $got = $false
        foreach ($u in $urls) {
            try { Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing -TimeoutSec 180; if ((Get-Item $zip).Length -gt 5MB) { $got = $true; break } } catch { }
        }
        if (-not $got) { throw 'PocketBase 下载失败' }
        $tmp = Join-Path $BUILD 'pbx'
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $pbSrc = Join-Path $tmp 'pocketbase.exe'
    }
    Copy-Item $pbSrc $pbDst -Force
}
Write-Host '  pocketbase.exe 就位'

# ---------- 5. 使用说明 ----------
$readme = @"
闲鱼卖家工作台 · 免安装版 $Tag
================================================
1. 解压到任意目录（路径可以中文，别放 OneDrive 同步盘里）
2. 双击 setup\首次配置.bat，按提示填几步（约半分钟）
3. 双击 workbench\工作台.bat → 选 1 启动全部服务
4. 浏览器打开 http://127.0.0.1:8090/workbench/
5. 「闲鱼客服」页签里点扫码登录（建议用小号）

说明
- 本包已内置 Python / Node / PocketBase，无需安装任何环境
- 系统要求：Windows 10/11 64 位
- 所有数据都在本目录里，整个文件夹拷走即备份
- 首次配置里 DeepSeek Key 可以留空，之后在助手面板设置里填
- 遇到问题先看 README.md 的「常见问题」
- 有不懂的别慌：把「卡在哪一步 + 报错原文」直接发给 AI 问（DeepSeek / 豆包 / 元宝 / ChatGPT 都行），
  让它按这份说明带你排查，基本都能自己搞定

—— 项目主页 https://github.com/vlv777/xianyu-seller-workbench
"@
[System.IO.File]::WriteAllText((Join-Path $PKG '使用说明.txt'), $readme, (New-Object System.Text.UTF8Encoding($false)))

# ---------- 6. 压缩 ----------
Write-Host '[6/6] 压缩 ...'
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$zipOut = Join-Path (Resolve-Path $OutDir).Path "$NAME-portable.zip"
if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
& tar.exe -a -cf "$zipOut" -C "$BUILD" "$NAME"
if ($LASTEXITCODE -ne 0) { throw '压缩失败' }
$size = [math]::Round((Get-Item $zipOut).Length / 1MB, 1)
Write-Host ''
Write-Host "打包完成 ✔  $zipOut  ($size MB)" -ForegroundColor Green
Write-Host "构建目录保留在：$BUILD（可删除）"
