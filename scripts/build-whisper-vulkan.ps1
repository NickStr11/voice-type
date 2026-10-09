<#
.SYNOPSIS
    Rebuild whisper.cpp with the Vulkan backend (MinGW) and install the binaries
    into runtime/whisper-cpp/.

.DESCRIPTION
    Reproducible recipe for the GPU/Vulkan STT path on the AMD RX 7800 XT box.
    An AMD driver update can break the prebuilt Vulkan binaries (see
    docs/learned-the-hard-way.md §3) — rerun this to rebuild against the current
    driver. The runtime *fix env* (VK_LOADER_LAYERS_DISABLE / GGML_VK_DISABLE_COOPMAT)
    lives in voice_type/stt_whisper.py (_VULKAN_ENV); this script only produces
    the binaries.

    Toolchain (w64devkit + ninja) is downloaded into runtime/build/ (gitignored)
    on first run and reused afterwards. Requires a Vulkan SDK (glslc) — set
    $env:VULKAN_SDK or install to C:\VulkanSDK\.

.EXAMPLE
    pwsh -File scripts/build-whisper-vulkan.ps1
    # then: scripts\restart.bat   (restart the worker to pick up new binaries)
#>
[CmdletBinding()]
param(
    [string]$WhisperTag    = "v1.9.1",
    [string]$W64DevkitVer  = "2.8.0",
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"

# --- paths ------------------------------------------------------------------
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$root       = Split-Path -Parent $scriptDir
$build      = Join-Path $root "runtime\build"
$whisperDir = Join-Path $root "runtime\whisper-cpp"
$src        = Join-Path $build "whisper.cpp"
$bld        = Join-Path $src   "bld"
$w64        = Join-Path $build "w64devkit"
$ninja      = Join-Path $build "ninja.exe"

New-Item -ItemType Directory -Force -Path $build | Out-Null

function Info($msg) { Write-Host "[build-whisper] $msg" -ForegroundColor Cyan }

# --- Vulkan SDK (provides glslc for shader compilation) ---------------------
if (-not $env:VULKAN_SDK) {
    $sdk = Get-ChildItem "C:\VulkanSDK" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($sdk) { $env:VULKAN_SDK = $sdk.FullName }
}
if (-not $env:VULKAN_SDK -or -not (Test-Path (Join-Path $env:VULKAN_SDK "Bin\glslc.exe"))) {
    throw "Vulkan SDK with glslc not found. Install from https://vulkan.lunarg.com/ and/or set `$env:VULKAN_SDK."
}
Info "Vulkan SDK: $env:VULKAN_SDK"

# --- w64devkit (portable MinGW gcc + g++) -----------------------------------
$gcc = Join-Path $w64 "bin\gcc.exe"
$gxx = Join-Path $w64 "bin\g++.exe"
if (-not (Test-Path $gcc)) {
    $sfx = Join-Path $build "w64devkit.7z.exe"
    $url = "https://github.com/skeeto/w64devkit/releases/download/v$W64DevkitVer/w64devkit-x64-$W64DevkitVer.7z.exe"
    Info "Downloading w64devkit $W64DevkitVer ..."
    Invoke-WebRequest -Uri $url -OutFile $sfx
    Info "Extracting w64devkit ..."
    # self-extracting 7z archive: -y assume-yes, -o<dir> output (no space)
    Start-Process -FilePath $sfx -ArgumentList "-y", "-o`"$build`"" -Wait -NoNewWindow
    if (-not (Test-Path $gcc)) { throw "w64devkit extraction failed — $gcc missing." }
}
Info "gcc: $gcc"

# --- ninja ------------------------------------------------------------------
if (-not (Test-Path $ninja)) {
    $zip = Join-Path $build "ninja-win.zip"
    Info "Downloading ninja ..."
    Invoke-WebRequest -Uri "https://github.com/ninja-build/ninja/releases/latest/download/ninja-win.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $build -Force
    if (-not (Test-Path $ninja)) { throw "ninja download failed." }
}
Info "ninja: $ninja"

# --- whisper.cpp source -----------------------------------------------------
if (-not (Test-Path $src)) {
    Info "Cloning whisper.cpp $WhisperTag ..."
    git clone --depth 1 --branch $WhisperTag https://github.com/ggml-org/whisper.cpp.git $src
} else {
    $currentTag = git -C $src describe --tags --exact-match 2>$null
    if ($currentTag -ne $WhisperTag) {
        Info "Updating whisper.cpp checkout from $currentTag to $WhisperTag ..."
        git -C $src fetch --depth 1 origin "tag" $WhisperTag
        git -C $src checkout --detach $WhisperTag
        if ($LASTEXITCODE -ne 0) { throw "Failed to checkout whisper.cpp $WhisperTag." }
    } else {
        Info "Reusing whisper.cpp $currentTag checkout at $src."
    }
}

# --- configure + build ------------------------------------------------------
# Ninja avoids the 'sh.exe in PATH' conflict that breaks the MinGW Makefiles
# generator. Static libstdc++ in w64devkit makes the output self-contained.
$env:PATH = "$($w64)\bin;$build;$($env:PATH)"
Info "Configuring (cmake -G Ninja, GGML_VULKAN=ON) ..."
cmake -B $bld -S $src -G Ninja `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_C_COMPILER="$gcc" `
    -DCMAKE_CXX_COMPILER="$gxx" `
    -DCMAKE_MAKE_PROGRAM="$ninja" `
    -DGGML_VULKAN=ON `
    -DWHISPER_SDL2=OFF `
    -DBUILD_SHARED_LIBS=ON
if ($LASTEXITCODE -ne 0) { throw "cmake configure failed." }

Info "Building whisper-cli + whisper-server ..."
& $ninja -C $bld whisper-cli whisper-server
if ($LASTEXITCODE -ne 0) { throw "ninja build failed." }

# --- install (with backup) --------------------------------------------------
$artifacts = @(
    "whisper-cli.exe", "whisper-server.exe",
    "ggml.dll", "ggml-base.dll", "ggml-cpu.dll", "ggml-vulkan.dll",
    "libwhisper.dll"
)
$binDir = Join-Path $bld "bin"

if (-not $SkipBackup) {
    $stamp  = Get-Date -Format "yyyy-MM-dd"
    $backup = Join-Path $whisperDir "backup-pre-$stamp"
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach ($a in $artifacts) {
        $cur = Join-Path $whisperDir $a
        if (Test-Path $cur) { Copy-Item $cur -Destination $backup -Force }
    }
    Info "Backed up current binaries -> $backup"
}

foreach ($a in $artifacts) {
    Copy-Item (Join-Path $binDir $a) -Destination $whisperDir -Force
}
Info "Installed new binaries -> $whisperDir"

Info "Done. Restart the worker to load them:  scripts\restart.bat"
Info "If GPU still crashes after a driver update, re-check _VULKAN_ENV toggles in voice_type/stt_whisper.py (see learned-the-hard-way §3)."
