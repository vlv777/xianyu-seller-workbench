# 闲鱼卖家工作台 · AI 一键部署提示词（复制给任意 AI 工具使用）

> **怎么用**：把本文件**整段复制**，粘贴给你在用的任意 AI 助手，
> 然后告诉它你的需求（例如：「帮我在我电脑上把闲鱼卖家工作台装好」）。
>
> - 如果你的 AI **能执行命令**（OpenCode / Codex / Claude Code / Cursor / 通义灵码 / 豆包电脑版等）：
>   它会直接按下面的步骤帮你下载、解压、配置、启动并验证。
> - 如果你的 AI **只能聊天**：它会把这些命令逐条给你，你复制到
>   PowerShell 里执行，把结果发回去让它判断下一步。
>
> 全程不需要安装 Python / Node / 数据库，免安装包里全带好了。

---

## 给 AI 的指令（从这里开始）

你要帮助用户在一台 **Windows 10/11（64 位）** 电脑上部署「闲鱼卖家工作台」。
这是一个本地运行的闲鱼卖家一体化工台：AI 客服自动回复 + 进销存记账，
全部数据存在本地，不依赖云服务。

请严格按以下步骤执行，**每一步都执行"验证"**；能做一步验证一步，不要跳步。
如果你无法执行命令，则逐条把命令给用户执行，并等用户贴回结果再继续。

### 0. 收集三个信息（先问用户，不要猜）

1. **店铺标识**：英文字母/数字，用作目录名，默认 `shop01`
2. **进销存登录邮箱 + 密码**：用户自己定，用于登录记账系统（例如 `me@example.com` / 自定义密码）
3. **DeepSeek API Key**：可留空（留空则 AI 客服不生成回复草稿，之后再填）

### 1. 下载免安装包

```powershell
$zip = "$env:USERPROFILE\Downloads\xianyu-seller-workbench-portable.zip"
# 主源（GitHub 官方），失败自动换国内镜像
$urls = @(
  'https://github.com/vlv777/xianyu-seller-workbench/releases/latest/download/xianyu-seller-workbench-portable.zip',
  'https://gh-proxy.com/https://github.com/vlv777/xianyu-seller-workbench/releases/latest/download/xianyu-seller-workbench-portable.zip'
)
foreach ($u in $urls) {
  try { Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing -TimeoutSec 300; break } catch { Write-Host "镜像失败：$u" }
}
if (-not (Test-Path $zip) -or (Get-Item $zip).Length -lt 10MB) { Write-Host '下载失败，请检查网络后重试'; exit 1 }
Write-Host "下载完成：" $zip ((Get-Item $zip).Length / 1MB)
```

**验证**：文件存在且大于 10MB。

### 2. 解压

```powershell
$dir = "$env:USERPROFILE\Downloads\xianyu-seller-workbench"
Expand-Archive -Path $zip -DestinationPath $dir -Force
Test-Path "$dir\xianyu-seller-workbench\workbench\工作台.bat"
```

**验证**：输出 `True`。
注意：建议放在普通目录（如 `D:\Tools\`），**不要**放 OneDrive/网盘同步目录。

### 3. 首次配置（自动化，无需交互）

把用户提供的信息代入下面命令执行（**把示例值换成用户的值**）：

```powershell
$root = "$dir\xianyu-seller-workbench"
$answers = @(
  'shop01',            # 店铺标识
  '我的小店',           # 店铺显示名
  '8767',              # 面板端口（被占用可换 8768/8769）
  '',                  # DeepSeek Key（可留空）
  '',                  # PushPlus Token（可留空）
  'me@example.com',    # 进销存登录邮箱
  '替换成用户的密码',     # 进销存登录密码
  ''                   # 末尾回车
)
$answers | & "$root\runtime\python\python.exe" "$root\setup\首次配置.py"
```

**验证**：输出包含「【3/3】完成 ✅」，并且以下文件存在：

```powershell
foreach ($f in 'assistant\shops\shop01\config.json','assistant\软件配置.json','assistant\知识库.md','jxc\ai\ai-config.json') {
  Write-Host $f (Test-Path "$root\$f")
}
```

说明：该向导是幂等的，失败可重跑；它会自动创建进销存管理员账号与登录用户。

### 4. 启动全部服务

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\workbench\workbench.ps1" start
```

**验证**（应看到 4 个 `[OK]`，顺序输出）：

```powershell
Start-Sleep 20
Invoke-WebRequest http://127.0.0.1:8090/api/health -UseBasicParsing | Select-Object -ExpandProperty StatusCode   # 期望 200
Invoke-WebRequest http://127.0.0.1:8091/health    -UseBasicParsing | Select-Object -ExpandProperty StatusCode   # 期望 200
Invoke-WebRequest http://127.0.0.1:8767/status    -UseBasicParsing | Select-Object -ExpandProperty Content      # 看到 JSON
Invoke-WebRequest http://127.0.0.1:8090/workbench/ -UseBasicParsing | Select-Object -ExpandProperty StatusCode # 期望 200
```

### 5. 交付给用户

打开 `http://127.0.0.1:8090/workbench/`（可 `Start-Process` 打开）。
告诉用户两件事：

1. **闲鱼客服**：点「闲鱼客服」页签 → 扫码登录（**建议用闲鱼小号**）；
2. **AI 开单**：在「进销存」页签里用一句话开单，例如「出货 红米AX6 1台 145」。

### 6. 常见错误处理

- **端口被占用（8090/8091/8767）**：看谁占用 `Get-NetTCPConnection -State Listen -LocalPort 8090 | Select OwningProcess`，
  用户自己不用就结束它，或换端口（助手面板端口在 `assistant\shops\<店名>\config.json`）。
- **下载被拦截**：换第 1 步的 gh-proxy 镜像；或让用户浏览器手动打开 Releases 页面下载。
- **.bat 被 SmartScreen/杀毒拦**：右键「属性」→ 勾「解除锁定」；杀毒软件加白名单。
- **PowerShell 禁止脚本**：命令统一加 `-ExecutionPolicy Bypass`（上面的命令已带）。
- **首次配置中途失败**：直接重跑（幂等），已建的账号不会重复。
- **启动后某个服务没起来**：看对应进程是否被杀软拦截；重跑第 4 步。

### 7. 升级方法（保留数据）

下载新版 zip 解压到新目录，然后把旧目录里的**用户数据**拷过去覆盖：

- `assistant\shops\`（店铺配置与登录态）
- `assistant\软件配置.json`、`assistant\知识库.md`、`assistant\补充知识.md`
- `jxc\pb_data\`（全部记账数据）、`jxc\ai\ai-config.json`

**程序文件不要拷**（runtime、代码都用新版的）。

### 8. 完成标准（全部满足才算部署成功）

- [ ] 首次配置输出「完成 ✅」且 4 个配置文件齐全
- [ ] 4 项验证全部 `[OK]`（进销存 / AI开单 / 闲鱼助手 / 工作台页）
- [ ] 工作台主页能在浏览器打开
- [ ] 已告知用户：扫码登录用小号、开单示例、数据备份=拷贝整个目录

---

## 附：你也可以直接告诉用户的"人话版"

> 装好后浏览器打开 `http://127.0.0.1:8090/workbench/` 就是总面板；
> 「闲鱼客服」里扫码登录（用小号最安全）；「进销存」里一句话就能开单。
> 数据都在你电脑里，整个文件夹拷走就是备份。
> 全程有任何看不懂的，直接把报错发给 AI 问，都能解决。

—— 项目主页：https://github.com/vlv777/xianyu-seller-workbench
