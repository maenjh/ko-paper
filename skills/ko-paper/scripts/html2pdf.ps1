# Print an HTML file to PDF with Edge (or Chrome) already on the machine.
#   powershell -NoProfile -ExecutionPolicy Bypass -File html2pdf.ps1 in.html out.pdf
# Lite mode uses this instead of BabelDOC, so nothing compiled is installed.
# ASCII only: Windows PowerShell 5.1 misreads UTF-8 files without a BOM.
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 2) { [Console]::Error.WriteLine('usage: html2pdf.ps1 in.html out.pdf'); exit 2 }
$in = (Resolve-Path $args[0]).Path
$out = Join-Path (Resolve-Path (Split-Path -Parent ([IO.Path]::GetFullPath($args[1])))).Path (Split-Path -Leaf $args[1])

$candidates = @(
    $env:KOPAPER_BROWSER,
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $browser) { [Console]::Error.WriteLine("[x] Edge or Chrome not found. Open $in in a browser and print it to PDF."); exit 1 }

if (Test-Path $out) { Remove-Item $out }
$url = ([Uri]$in).AbsoluteUri  # file:///C:/... with spaces and Korean names escaped
# A throwaway profile: works while the user's own browser is open, and leaves their profile alone.
$tmpProfile = Join-Path ([IO.Path]::GetTempPath()) ("ko-paper-" + [Guid]::NewGuid())
try {
    # Start-Process -Wait: Edge is a GUI program, so a plain call would return before the PDF is written.
    Start-Process -FilePath $browser -Wait -WindowStyle Hidden -ArgumentList @(
        '--headless=new', '--disable-gpu', '--no-first-run', "--user-data-dir=`"$tmpProfile`"",
        '--no-pdf-header-footer', "--print-to-pdf=`"$out`"", "`"$url`"")
} finally {
    Remove-Item -Recurse -Force $tmpProfile -ErrorAction SilentlyContinue
}
if (-not (Test-Path $out) -or (Get-Item $out).Length -eq 0) { [Console]::Error.WriteLine("[x] the browser did not write $out"); exit 1 }
Write-Output $out
