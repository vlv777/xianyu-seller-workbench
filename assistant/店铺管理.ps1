param([string]$Action = "")
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$py = ''
foreach ($c in @("$root\..\runtime\python\python.exe", "$root\.venv\Scripts\python.exe", "$root\..\venv\Scripts\python.exe")) {
    if (Test-Path $c) { $py = (Resolve-Path $c).Path; break }
}
if (-not $py) { $py = 'python' }
$chrome = $env:CHROME_PATH
if (-not $chrome) {
    foreach ($cand in @('C:\Program Files\Google\Chrome\Application\chrome.exe', 'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe', 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', 'C:\Program Files\Microsoft\Edge\Application\msedge.exe')) {
        if (Test-Path $cand) { $chrome = $cand; break }
    }
}
Set-Location $root

function Get-Shops {
    @(Get-ChildItem "$root\shops" -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path "$($_.FullName)\config.json" } |
        Select-Object -ExpandProperty Name | Sort-Object)
}

function Get-ShopCfg($name) {
    Get-Content "$root\shops\$name\config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-Running($name) {
    $pat = "--shop\s+" + [regex]::Escape($name) + "(\s|$)"
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match $pat }).Count -gt 0
}

function Start-One($name) {
    if (Test-Running $name) { Write-Host "  [$name] 已在运行"; return }
    Start-Process -FilePath $py -ArgumentList "main.py --shop $name" -WorkingDirectory $root -WindowStyle Hidden
    Write-Host "  [$name] 已启动"
}

function Stop-One($name) {
    $pat = "--shop\s+" + [regex]::Escape($name) + "(\s|$)"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match $pat } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "  [$name] 已停止"
}

function Choose-Shop {
    $shops = Get-Shops
    if (-not $shops) { Write-Host "没有店铺，请先新建"; return $null }
    for ($i = 0; $i -lt $shops.Count; $i++) { Write-Host ("  {0}) {1}" -f ($i + 1), $shops[$i]) }
    $sel = Read-Host "选择编号"
    $idx = 0
    if (-not [int]::TryParse($sel, [ref]$idx)) { return $null }
    $idx = $idx - 1
    if ($idx -lt 0 -or $idx -ge $shops.Count) { return $null }
    return $shops[$idx]
}

function Fix-Shop {
    $name = Choose-Shop
    if (-not $name) { return }
    $cfg = Get-ShopCfg $name
    Write-Host "即将弹出 Chrome 并打开验证页——请在弹出的窗口里完成滑块验证"
    $dp = $cfg.debug_port
    Start-Process -FilePath $chrome -ArgumentList "--remote-debugging-port=$dp", "--user-data-dir=$root\shops\$name\chrome-profile", "--no-first-run", "--no-default-browser-check", "--new-window", "https://www.goofish.com/"
    Start-Sleep -Seconds 8
    & $py "$root\punish_flow.py" --shop $name
    Write-Host "重启该店..."
    Stop-One $name
    Start-Sleep -Seconds 3
    Start-One $name
}

if ($Action) {
    switch ($Action) {
        'start-all' {
            foreach ($s in Get-Shops) { Start-One $s; Start-Sleep -Seconds 8 }
            & $py "$root\shop_admin.py" list
            return
        }
        'stop-all' {
            Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match '--shop' } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Write-Host "已停止全部店铺"
            return
        }
        'status' { & $py "$root\shop_admin.py" list; return }
        default { }
    }
}

while ($true) {
    Write-Host ""
    Write-Host "===== 闲鱼助手 · 店铺管理 ====="
    Write-Host " 1) 查看全部店铺状态"
    Write-Host " 2) 启动全部店铺（逐个启动，间隔 8 秒）"
    Write-Host " 3) 停止全部店铺"
    Write-Host " 4) 新建店铺"
    Write-Host " 5) 打开某店面板"
    Write-Host " 6) 某店掉线修复（过风控滑块 -> 重启）"
    Write-Host " 0) 退出"
    $c = Read-Host "请选择"
    switch ($c) {
        '1' { & $py "$root\shop_admin.py" list }
        '2' { foreach ($s in Get-Shops) { Start-One $s; Start-Sleep -Seconds 8 } }
        '3' {
            Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match '--shop' } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Write-Host "已停止全部店铺"
        }
        '4' {
            if (Test-Path "$root\单店版.txt") { Write-Host "此为单店铺测试版，不支持新建店铺" }
            else { $n = Read-Host "输入新店名（字母/数字，如 shop02）"; if ($n) { & $py "$root\shop_admin.py" new $n } }
        }
        '5' { $name = Choose-Shop; if ($name) { $cfg = Get-ShopCfg $name; Start-Process "http://127.0.0.1:$($cfg.port)/" } }
        '6' { Fix-Shop }
        '0' { return }
        default { Write-Host "无效选项" }
    }
}
