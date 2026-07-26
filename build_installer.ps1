param(
    [string]$PythonExecutable = "python",
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VersionPath = Join-Path $ProjectRoot "VERSION"
if (-not (Test-Path -LiteralPath $VersionPath -PathType Leaf)) {
    throw "VERSION file is missing."
}
$Version = (Get-Content -LiteralPath $VersionPath -Raw).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "VERSION must contain exactly three numeric components, for example 1.0.0."
}

$WindowsFileVersion = "$Version.0"
$VersionTuple = (($Version.Split(".") + "0") -join ", ")
$Utf8 = [Text.Encoding]::UTF8
$ProductName = $Utf8.GetString(
    [Convert]::FromBase64String("6auY5qCh5pWZ5biI5L+h5oGv6YeH6ZuG5bel5YW3")
)
$FileDescription = $Utf8.GetString(
    [Convert]::FromBase64String(
        "6auY5qCh5pWZ5biI55uu5b2V5om56YeP6YeH6ZuG5LiOIEV4Y2VsIOWvvOWHuuW3peWFtw=="
    )
)

$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$BuildRoot = [IO.Path]::GetFullPath(
    (Join-Path $TempRoot "FacultyCrawler-installer-build")
)
$ExpectedPrefix = $TempRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
    [IO.Path]::DirectorySeparatorChar
if (-not $BuildRoot.StartsWith(
    $ExpectedPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Task build directory must remain under the system temporary directory."
}

$BuildEnvironment = Join-Path $BuildRoot "venv"
$BrowserRoot = Join-Path $BuildRoot "ms-playwright"
$BuildPython = Join-Path $BuildEnvironment "Scripts\python.exe"
$ApplicationDistRoot = Join-Path $BuildRoot "dist"
$PyInstallerWorkRoot = Join-Path $BuildRoot "pyinstaller"
$ApplicationRoot = Join-Path $ApplicationDistRoot "FacultyCrawler"
$ApplicationExe = Join-Path $ApplicationRoot "FacultyCrawler.exe"
$InstallerRoot = Join-Path $ProjectRoot "dist\installer"
$InstallerExe = Join-Path $InstallerRoot "FacultyCrawler-Setup-$Version.exe"
$VersionResource = Join-Path $BuildRoot "file_version_info.txt"

function Remove-TaskBuildDirectory {
    param([string]$Path)

    for ($Attempt = 1; $Attempt -le 5; $Attempt++) {
        if (-not (Test-Path -LiteralPath $Path)) { return }
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        }
        catch {
            if ($Attempt -eq 5) {
                throw "Unable to clean task build directory after 5 attempts: $Path"
            }
            Start-Sleep -Milliseconds 250
        }
    }
}

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
Remove-TaskBuildDirectory -Path $BuildEnvironment
Remove-TaskBuildDirectory -Path $ApplicationDistRoot
Remove-TaskBuildDirectory -Path $PyInstallerWorkRoot
New-Item -ItemType Directory -Force -Path $BrowserRoot | Out-Null

$VersionResourceContent = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($VersionTuple),
    prodvers=($VersionTuple),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'FacultyCrawler'),
          StringStruct('FileDescription', '$FileDescription'),
          StringStruct('FileVersion', '$WindowsFileVersion'),
          StringStruct('InternalName', 'FacultyCrawler'),
          StringStruct('OriginalFilename', 'FacultyCrawler.exe'),
          StringStruct('ProductName', '$ProductName'),
          StringStruct('ProductVersion', '$Version'),
        ],
      ),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"@
Set-Content -LiteralPath $VersionResource -Value $VersionResourceContent -Encoding UTF8

Push-Location $ProjectRoot
try {
    & $PythonExecutable -m venv $BuildEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the clean build environment."
    }

    & $PythonExecutable -m pip --python $BuildPython install `
        --disable-pip-version-check -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to install requirements-build.txt."
    }

    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserRoot
    $env:FACULTY_CRAWLER_BROWSER_SOURCE = $BrowserRoot
    $env:FACULTY_CRAWLER_VERSION_FILE = $VersionResource
    & $BuildPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to install task-specific Playwright Chromium."
    }

    & $BuildPython -m PyInstaller --noconfirm --clean `
        --distpath $ApplicationDistRoot `
        --workpath $PyInstallerWorkRoot `
        faculty_crawler.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    if (-not (Test-Path -LiteralPath $ApplicationExe -PathType Leaf)) {
        throw "PyInstaller did not create FacultyCrawler.exe."
    }
    $BundledChrome = Get-ChildItem `
        -LiteralPath $ApplicationRoot `
        -Filter "chrome.exe" `
        -File `
        -Recurse
    if (-not $BundledChrome) {
        throw "The application bundle does not contain Chromium chrome.exe."
    }

    $ArchiveListing = & $BuildPython `
        -m PyInstaller.utils.cliutils.archive_viewer `
        -r `
        -b `
        $ApplicationExe
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the PyInstaller archive."
    }
    $ArchiveText = $ArchiveListing -join "`n"
    foreach ($RequiredModule in @("crawler.faculty_crawler", "ui.controller")) {
        if ($ArchiveText -notmatch [regex]::Escape($RequiredModule)) {
            throw "The application bundle is missing required module $RequiredModule."
        }
    }

    if (-not $InnoCompiler) {
        $Candidates = @(
            $env:INNO_SETUP_COMPILER,
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        ) | Where-Object { $_ }
        $InnoCompiler = $Candidates | Where-Object {
            Test-Path -LiteralPath $_ -PathType Leaf
        } | Select-Object -First 1
    }
    if (-not $InnoCompiler) {
        throw "Inno Setup 6 compiler (ISCC.exe) was not found. Install it or pass -InnoCompiler."
    }

    New-Item -ItemType Directory -Force -Path $InstallerRoot | Out-Null
    & $InnoCompiler `
        "/O$InstallerRoot" `
        "/DAppVersion=$Version" `
        "/DApplicationRoot=$ApplicationRoot" `
        "installer\faculty-crawler.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed."
    }
    if (-not (Test-Path -LiteralPath $InstallerExe -PathType Leaf)) {
        throw "Inno Setup did not create $InstallerExe."
    }

    $GitCommit = (& git rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $GitCommit) {
        $GitCommit = "unknown"
    }
    $InstallerHash = (
        Get-FileHash -LiteralPath $InstallerExe -Algorithm SHA256
    ).Hash
    Write-Host "Version: $Version"
    Write-Host "Git commit: $GitCommit"
    Write-Host "Built: $ApplicationExe"
    Write-Host "Built: $InstallerExe"
    Write-Host "Installer SHA-256: $InstallerHash"
}
finally {
    Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:FACULTY_CRAWLER_BROWSER_SOURCE -ErrorAction SilentlyContinue
    Remove-Item Env:FACULTY_CRAWLER_VERSION_FILE -ErrorAction SilentlyContinue
    Pop-Location
}
