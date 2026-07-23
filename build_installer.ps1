param(
    [string]$PythonExecutable = "python",
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$BuildRoot = [IO.Path]::GetFullPath(
    (Join-Path $TempRoot "FacultyCrawler-installer-build")
)
$ExpectedPrefix = $TempRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $BuildRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Task build directory must remain under the system temporary directory."
}
$BuildEnvironment = Join-Path $BuildRoot "venv"
$BrowserRoot = Join-Path $BuildRoot "ms-playwright"
$BuildPython = Join-Path $BuildEnvironment "Scripts\python.exe"
$ApplicationRoot = Join-Path $ProjectRoot "dist\FacultyCrawler"
$ApplicationExe = Join-Path $ApplicationRoot "FacultyCrawler.exe"
$InstallerRoot = Join-Path $ProjectRoot "dist\installer"
$InstallerExe = Join-Path $InstallerRoot "FacultyCrawler-Setup.exe"

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

Remove-TaskBuildDirectory -Path $BuildRoot
New-Item -ItemType Directory -Path $BuildRoot | Out-Null
New-Item -ItemType Directory -Force -Path $BrowserRoot | Out-Null

Push-Location $ProjectRoot
try {
    & $PythonExecutable -m venv $BuildEnvironment
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the clean build environment." }

    & $PythonExecutable -m pip --python $BuildPython install `
        --disable-pip-version-check -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Unable to install requirements-build.txt." }

    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserRoot
    $env:FACULTY_CRAWLER_BROWSER_SOURCE = $BrowserRoot
    & $BuildPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Unable to install task-specific Playwright Chromium." }

    & $BuildPython -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $ProjectRoot "dist") `
        --workpath (Join-Path $BuildRoot "pyinstaller") `
        faculty_crawler.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    if (-not (Test-Path -LiteralPath $ApplicationExe -PathType Leaf)) {
        throw "PyInstaller did not create FacultyCrawler.exe."
    }
    $BundledChrome = Get-ChildItem -LiteralPath $ApplicationRoot -Filter "chrome.exe" -File -Recurse
    if (-not $BundledChrome) {
        throw "The application bundle does not contain Chromium chrome.exe."
    }

    $ArchiveListing = & $BuildPython -m PyInstaller.utils.cliutils.archive_viewer -r -b $ApplicationExe
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect the PyInstaller archive." }
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
    & $InnoCompiler "/O$InstallerRoot" "/FFacultyCrawler-Setup" "installer\faculty-crawler.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }
    if (-not (Test-Path -LiteralPath $InstallerExe -PathType Leaf)) {
        throw "Inno Setup did not create FacultyCrawler-Setup.exe."
    }

    Write-Host "Built $ApplicationExe"
    Write-Host "Built $InstallerExe"
}
finally {
    Pop-Location
}
