$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$sdk = "$env:LOCALAPPDATA\Android\Sdk"
$bt = "$sdk\build-tools\34.0.0"
$aj = "$sdk\platforms\android-34\android.jar"
$jh = $env:JAVA_HOME
if (-not $jh -or -not (Test-Path "$jh\bin\javac.exe")) {
  foreach ($cand in (Get-ChildItem "C:\Program Files\Microsoft\jdk-17*","C:\Program Files\Java\jdk-17*","C:\Program Files\Eclipse Adoptium\jdk-17*" -Directory -ErrorAction SilentlyContinue)) { if (Test-Path "$($cand.FullName)\bin\javac.exe") { $jh = $cand.FullName; break } }
}
if (-not $jh) { throw "未找到 JDK 17：请设 JAVA_HOME 或安装 JDK 17" }
$env:JAVA_HOME = $jh
$stage = "$env:TEMP\opencode\jxc-build"
$out = "$stage\out"

# [1/9] icons (PS/.NET handles unicode paths)
if (-not (Test-Path "$root\res\mipmap-xxxhdpi\ic_launcher.png")) {
  Add-Type -AssemblyName System.Drawing
  $dens = @(@('mdpi', 48), @('hdpi', 72), @('xhdpi', 96), @('xxhdpi', 144), @('xxxhdpi', 192))
  foreach ($d in $dens) {
    $name = $d[0]; $size = [int]$d[1]
    $dir = "$root\res\mipmap-$name"
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::FromArgb(31, 30, 29))
    $font = New-Object System.Drawing.Font('Microsoft YaHei', [float]($size * 0.5), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = [System.Drawing.StringAlignment]::Center
    $fmt.LineAlignment = [System.Drawing.StringAlignment]::Center
    $rect = New-Object System.Drawing.RectangleF(0, 0, $size, $size)
    $g.DrawString([char]0x8FDB, $font, [System.Drawing.Brushes]::White, $rect, $fmt)
    $g.Dispose()
    $bmp.Save("$dir\ic_launcher.png", [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
  }
  Write-Host "[1/9] icons generated"
} else { Write-Host "[1/9] icons cached" }

# [2/9] keystore
$ksPass = $env:JXC_KEYSTORE_PASS
if (-not $ksPass) { $ksPass = 'jxc-android' }
if (-not (Test-Path "$root\keystore.jks")) {
  & "$jh\bin\keytool.exe" -genkeypair -keystore "$root\keystore.jks" -alias jxc -keyalg RSA -keysize 2048 -validity 10000 -storepass $ksPass -keypass $ksPass -dname "CN=jxc, O=jxc-workbench, C=CN"
  if ($LASTEXITCODE -ne 0) { throw "keytool failed" }
  Write-Host "[2/9] keystore generated"
} else { Write-Host "[2/9] keystore cached" }

# [3/9] stage to ASCII dir (native tools cannot take unicode paths)
Write-Host "[3/9] stage copy"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Path $out -Force | Out-Null
Copy-Item "$root\res" -Destination "$stage\res" -Recurse
Copy-Item "$root\src" -Destination "$stage\src" -Recurse
Copy-Item "$root\AndroidManifest.xml" "$stage\AndroidManifest.xml"
Copy-Item "$root\merge-dex.py" "$stage\merge-dex.py"
Copy-Item "$root\keystore.jks" "$stage\keystore.jks"

Write-Host "[4/9] aapt2 compile"
& "$bt\aapt2.exe" compile --dir "$stage\res" -o "$out\res.zip"
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }

Write-Host "[5/9] aapt2 link"
& "$bt\aapt2.exe" link -o "$out\base.apk" -I "$aj" --manifest "$stage\AndroidManifest.xml" -R "$out\res.zip" --auto-add-overlay
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

Write-Host "[6/9] javac"
if (Test-Path "$out\classes") { Remove-Item -Recurse -Force "$out\classes" }
& "$jh\bin\javac.exe" --release 11 -encoding UTF-8 -cp "$aj" -d "$out\classes" "$stage\src\com\example\jxc\MainActivity.java"
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

Write-Host "[7/9] d8"
if (Test-Path "$out\dex") { Remove-Item -Recurse -Force "$out\dex" }
New-Item -ItemType Directory -Path "$out\dex" -Force | Out-Null
$cls = Get-ChildItem -Recurse "$out\classes" -Filter *.class | ForEach-Object { $_.FullName }
& "$bt\d8.bat" --lib "$aj" --min-api 24 --output "$out\dex" @cls
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Write-Host "[8/9] merge dex"
python "$stage\merge-dex.py" "$out\base.apk" "$out\dex\classes.dex" "$out\basedex.apk"
if ($LASTEXITCODE -ne 0) { throw "merge failed" }

Write-Host "[9/9] zipalign + sign + verify"
& "$bt\zipalign.exe" -f 4 "$out\basedex.apk" "$out\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }
& "$bt\apksigner.bat" sign --ks "$stage\keystore.jks" --ks-pass "pass:$ksPass" --key-pass "pass:$ksPass" --out "$out\jxc.apk" "$out\aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "sign failed" }
& "$bt\apksigner.bat" verify --print-certs "$out\jxc.apk"
if ($LASTEXITCODE -ne 0) { throw "verify failed" }

if (-not (Test-Path "$root\out")) { New-Item -ItemType Directory -Path "$root\out" | Out-Null }
Copy-Item "$out\jxc.apk" "$root\out\jxc.apk" -Force
$apk = Get-Item "$root\out\jxc.apk"
Write-Host ("OK -> " + $apk.FullName + "  (" + [math]::Round($apk.Length / 1024) + " KB)")
