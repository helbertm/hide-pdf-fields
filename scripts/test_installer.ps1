$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $Root 'install.ps1') -Version 'v1.0.0' -ArchiveSha256 ('0'*64)
$OriginalLocal = $env:LOCALAPPDATA
$Temp = Join-Path $env:TEMP ('pdf-installer-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Temp | Out-Null
function Assert-True($Value,[string]$Message) { if (-not $Value) { throw $Message } }
function Bad-Zip([string]$Name) {
    $File = Join-Path $Temp ([guid]::NewGuid().ToString('N') + '.zip')
    $Z = [IO.Compression.ZipFile]::Open($File,[IO.Compression.ZipArchiveMode]::Create)
    try { $E=$Z.CreateEntry($Name); $W=New-Object IO.StreamWriter($E.Open());$W.Write('bad');$W.Dispose() } finally {$Z.Dispose()}
    return $File
}
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($Name in @('../escape.py','/absolute.py','C:/drive.py','interface.py:ads','nested/unknown.py')) {
        $Failed=$false
        try { Expand-VerifiedArchive (Bad-Zip $Name) (Join-Path $Temp 'invalid') } catch { $Failed=$true }
        Assert-True $Failed 'Unsafe ZIP entry accepted.'
    }
    $Zip = Join-Path $Root 'dist\hide-pdf-fields-windows.zip'
    $Hash = (Get-FileHash -Algorithm SHA256 $Zip).Hash
    $Python = (Get-Command python.exe).Source
    $OriginalLocal = $env:LOCALAPPDATA
    $env:LOCALAPPDATA = Join-Path $Temp 'Usuário teste'
    $script:ArchivePath=$Zip
    $script:ArchiveSha256=('0'*64)
    $script:Version='v1.0.0'
    $script:PythonExecutable=$Python
    $script:ProvisionPython=$true
    $Failed=$false
    try { Install-App } catch { $Failed=$true }
    Assert-True $Failed 'Wrong archive checksum accepted.'
    $script:ArchiveSha256=$Hash
    $First=Install-App | Select-Object -Last 1
    Assert-True (Test-Path (Join-Path $First '.venv\Scripts\pythonw.exe')) 'Pythonw missing.'
    $Desktop=[Environment]::GetFolderPath('DesktopDirectory')
    $Shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $Desktop 'Ocultar Dados.lnk'))
    Assert-True ((Get-CanonicalPath $Shortcut.TargetPath) -eq (Get-CanonicalPath (Join-Path $First '.venv\Scripts\pythonw.exe'))) 'Shortcut target mismatch.'
    Assert-True ($Shortcut.Arguments -eq ('"'+(Join-Path $First 'app\interface.py')+'"')) 'Shortcut arguments mismatch.'
    & (Join-Path $First '.venv\Scripts\python.exe') (Join-Path $First 'app\scripts\smoke.py')
    Assert-True ($LASTEXITCODE -eq 0) 'Installed runtime failed.'
    $script:ProvisionPython=$false
    $Second=Install-App | Select-Object -Last 1
    Assert-True ($First -ne $Second) 'Rerun did not isolate installation.'
    Assert-True (Test-Path (Join-Path $First '.venv\Scripts\pythonw.exe')) 'Previous installation lost.'
    Write-Host 'Windows installer and shortcut: OK'
} finally {
    $Desktop=[Environment]::GetFolderPath('DesktopDirectory')
    $Link=Join-Path $Desktop 'Ocultar Dados.lnk'
    if (Test-Path -LiteralPath $Link) {
        $Owned=(New-Object -ComObject WScript.Shell).CreateShortcut($Link)
        if ((Get-CanonicalPath $Owned.TargetPath).StartsWith((Get-CanonicalPath $Temp) + '\',[StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $Link }
    }
    if ($OriginalLocal) { $env:LOCALAPPDATA=$OriginalLocal }
    # This test directory was created by the test itself.
    if (Test-Path $Temp) { Remove-Item $Temp -Recurse -Force }
}
