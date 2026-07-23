# Academic Faculty Data Collection

Python project for collecting faculty member data from a university faculty directory page and exporting it to Excel.

## Features

- Accepts a faculty directory URL from the command line.
- Uses Playwright Chromium so JavaScript-rendered pages can be crawled.
- Extracts faculty name, academic title, and profile URL.
- Removes duplicates.
- Exports results to `.xlsx` with columns `Name`, `Title`, and `Profile_URL`.
- Includes logging and clear error handling.

## Project Structure

```text
.
├── crawler/
│   ├── __init__.py
│   ├── faculty_crawler.py
│   └── parsers.py
├── output/
├── tests/
├── main.py
├── README.md
└── requirements.txt
```

## Setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Example Usage

```bash
python main.py https://www.eecs.mit.edu/people/faculty-advisors/ --output output/mit_faculty.xlsx
```

Optional flags:

```bash
python main.py <faculty_directory_url> --output output/faculty_data.xlsx --timeout 30000 --verbose
```

## Windows Desktop Batch Mode

For source-based development, run `setup.bat` once, then double-click `start.bat`.
For colleagues, distribute `dist/installer/FacultyCrawler-Setup.exe`; normal use does not require
Python, a command line, AI knowledge, or Feishu administrator access.

Build the clean Windows source archive with:

```bash
python build_release.py
```

The archive is written to `dist/faculty-crawler-windows.zip` and excludes virtual environments,
tests, caches, previous output files, and Git metadata.

### Build the Windows installer

Build prerequisites:

- 64-bit Python 3.11 or newer available as `python`;
- internet access while build dependencies and Playwright Chromium are downloaded;
- Inno Setup 6, with `ISCC.exe` in its standard per-machine/per-user location or supplied with
  `-InnoCompiler`.

The build dependencies are bounded in `requirements-build.txt`. The script recreates the
task-specific `%TEMP%\FacultyCrawler-installer-build` environment and Playwright browser directory
on each run. Its ASCII-only temporary path also supports source worktrees whose path contains
Chinese characters. The script does not use or change a global Playwright cache.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

To select tools explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1 `
  -PythonExecutable "C:\Path\To\python.exe" `
  -InnoCompiler "C:\Path\To\ISCC.exe"
```

Successful output is `dist/FacultyCrawler/FacultyCrawler.exe` and
`dist/installer/FacultyCrawler-Setup.exe`. The script fails if the executable, bundled Chromium,
required runtime modules, or installer is absent. Build inputs are explicit; local output, logs,
reports, runs, sessions, tasks, settings, cookies, and other user data are not packaged.

### Verification data upgrades

Verification queue schema upgrades are not automatic. If the desktop reports
that saved verification data requires cleanup or an application upgrade, close
the application, remove the local `verification-queue.json` file under the
FacultyCrawler application-data `runs` directory, and restart. Queue contents
are never included in the diagnostic message or release archive.

## Run Tests

```bash
python -m unittest discover -s tests -v
```

## Notes

This first version crawls one faculty directory page at a time. Extraction is heuristic and best-effort across university websites, with the MIT EECS faculty directory used as the reference example. It does not include recursive crawling, proxy rotation, a database, or a web UI.
