# Macro Goblin one-line installer.
#   irm https://atxgreene.github.io/rift-coach/install.ps1 | iex
#
# Downloads the latest MacroGoblin-Setup.exe from GitHub Releases, checks its
# SHA-256 against the release's SHA256SUMS.txt, and installs it for the current
# user (no admin prompt). Nothing else is changed on your PC.

# Runs in its own scope so your shell's settings are left exactly as they were.
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # makes Invoke-WebRequest much faster on Windows PowerShell
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $repo = 'atxgreene/rift-coach'
    $base = "https://github.com/$repo/releases/latest/download"
    $setup = Join-Path $env:TEMP 'MacroGoblin-Setup.exe'
    $sums = Join-Path $env:TEMP 'MacroGoblin-SHA256SUMS.txt'

    Write-Host ''
    Write-Host '  Macro Goblin' -ForegroundColor Yellow
    Write-Host '  Live macro coach for League of Legends' -ForegroundColor DarkGray
    Write-Host ''

    if ([Environment]::OSVersion.Version.Major -lt 10) {
        throw 'Macro Goblin needs Windows 10 or 11.'
    }

    Write-Host '  Downloading the latest release...'
    Invoke-WebRequest -UseBasicParsing -Uri "$base/MacroGoblin-Setup.exe" -OutFile $setup
    Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS.txt" -OutFile $sums

    $expected = (Get-Content $sums | Where-Object { $_ -match 'MacroGoblin-Setup\.exe' } | ForEach-Object { ($_ -split '\s+')[0] }) | Select-Object -First 1
    $actual = (Get-FileHash -Algorithm SHA256 $setup).Hash
    if (-not $expected -or $expected.ToLower() -ne $actual.ToLower()) {
        Remove-Item $setup -ErrorAction SilentlyContinue
        throw 'Checksum did not match. Nothing was installed. Try again, or download from GitHub Releases.'
    }
    Write-Host '  Checksum verified.' -ForegroundColor DarkGray

    Write-Host '  Installing...'
    # Wait for Setup itself only. (-Wait would also wait for the app Setup launches at the end.)
    $proc = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru
    $proc.WaitForExit()
    Remove-Item $setup, $sums -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0) {
        throw "The installer exited with code $($proc.ExitCode)."
    }

    Write-Host ''
    Write-Host '  Installed. Macro Goblin is opening now.' -ForegroundColor Green
    Write-Host '  Find it later in the Start menu. Set League to Borderless for the overlay.' -ForegroundColor DarkGray
    Write-Host ''
}
