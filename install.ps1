#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+$')][string]$Version,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ArchiveSha256,
    [string]$ArchivePath,
    [string]$PythonExecutable,
    [switch]$ProvisionPython
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Repository = 'helbertm/hide-pdf-fields'
$PythonVersion = '3.14.10'
$PythonInstallerSha256 = '92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965'
$AllowedFiles = @('assets/icon.png','assets/icon.ico','interface.py','manual_pdf.py','manual_interface.py','manual_export.py','atualizacao.py','tarjar.py','lote.py','requirements-win.lock','README.md','USO.md','THIRD_PARTY.md','scripts/smoke.py')

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class WindowsPaths {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern uint GetLongPathName(string path, StringBuilder result, uint size);
}
'@
function Get-CanonicalPath([string]$Path) {
    $Buffer = New-Object System.Text.StringBuilder 32768
    $Length = [WindowsPaths]::GetLongPathName([IO.Path]::GetFullPath($Path), $Buffer, $Buffer.Capacity)
    if ($Length -eq 0 -or $Length -ge $Buffer.Capacity) { throw 'Nao foi possivel resolver o caminho da instalacao.' }
    return $Buffer.ToString()
}
function Assert-Python([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    try {
        & $Candidate -c 'import sys,struct,tkinter,venv; assert sys.version_info[:2] == (3,14) and sys.version_info >= (3,14,10) and struct.calcsize(chr(80)) == 8' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
function Find-Python {
    $Candidates = @((Join-Path $env:LOCALAPPDATA ('HidePdfFields\runtime\Python-' + $PythonVersion + '\python.exe')))
    if ($PythonExecutable) { $Candidates += $PythonExecutable }
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        try { $Candidates += (& py.exe -3.14 -c 'import sys;print(sys.executable)' 2>$null) } catch {}
    }
    $Candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe')
    $Found = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($Found) { $Candidates += $Found.Source }
    foreach ($Candidate in $Candidates) {
        if (Assert-Python $Candidate) { return $Candidate }
    }
    return $null
}
function Expand-VerifiedArchive([string]$ZipPath,[string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $Names = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $Total = 0L
        foreach ($Entry in $Archive.Entries) {
            $Name = $Entry.FullName
            $FileType = (($Entry.ExternalAttributes -shr 16) -band 61440)
            if ($Name -notin $AllowedFiles -or -not $Names.Add($Name) -or $FileType -eq 40960) {
                throw 'Arquivo ZIP contem caminhos, links ou entradas nao permitidos.'
            }
            $Total += $Entry.Length
            if ($Total -gt 10485760) { throw 'Arquivo ZIP excede o tamanho esperado.' }
        }
        if ($Names.Count -ne $AllowedFiles.Count) { throw 'Pacote incompleto.' }
        foreach ($Entry in $Archive.Entries) {
            $Target = [IO.Path]::GetFullPath((Join-Path $Destination $Entry.FullName))
            $Root = [IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
            if (-not $Target.StartsWith($Root,[StringComparison]::OrdinalIgnoreCase)) { throw 'Caminho fora da instalacao.' }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Target)) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry,$Target,$false)
        }
    } finally { $Archive.Dispose() }
}
function Install-App {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        throw 'Este instalador suporta Windows x64.'
    }
    Write-Host 'Verificando requisitos...'
    $AppRoot = Join-Path $env:LOCALAPPDATA 'HidePdfFields'
    $InstallPath = Join-Path $AppRoot ('versions\' + $Version + '-' + [guid]::NewGuid().ToString('N'))
    $TempPath = Join-Path ([IO.Path]::GetTempPath()) ('hide-pdf-fields-' + [guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($TempPath) | Out-Null
    try {
        $ZipPath = Join-Path $TempPath 'app.zip'
        if ($ArchivePath) { Copy-Item -LiteralPath $ArchivePath -Destination $ZipPath }
        else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $Url = "https://github.com/$Repository/releases/download/$Version/hide-pdf-fields-windows.zip"
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $ZipPath
        }
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath).Hash -ne $ArchiveSha256) { throw 'Checksum do pacote incorreto. Instalacao interrompida.' }
        $AppPath = Join-Path $InstallPath 'app'
        # Versioned permanent location: completed virtual environments are never moved.
        [IO.Directory]::CreateDirectory($AppPath) | Out-Null
        Expand-VerifiedArchive $ZipPath $AppPath
        Write-Host 'Preparando Python...'
        $Python = if ($ProvisionPython) { $null } else { Find-Python }
        if (-not $Python) {
            $Installer = Join-Path $TempPath 'python-setup.exe'
            $PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri $PythonUrl -OutFile $Installer
            if ((Get-FileHash -Algorithm SHA256 $Installer).Hash -ne $PythonInstallerSha256) { throw 'Checksum do Python incorreto.' }
            $Signature=Get-AuthenticodeSignature -LiteralPath $Installer
            if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') {
                throw 'Assinatura do instalador Python nao validada.'
            }
            $PythonPath=Join-Path $AppRoot ('runtime\Python-' + $PythonVersion)
            $Arguments=@('/quiet','InstallAllUsers=0',('TargetDir="'+$PythonPath+'"'),'Include_launcher=0','Include_test=0','PrependPath=0','Include_tcltk=1','Include_pip=1','AssociateFiles=0','Shortcuts=0')
            $Setup=Start-Process -FilePath $Installer -ArgumentList $Arguments -Wait -PassThru
            if ($Setup.ExitCode -notin @(0,3010)) { throw 'Nao foi possivel instalar Python. Codigo: '+$Setup.ExitCode }
            $Python=Join-Path $PythonPath 'python.exe'
            if (-not (Assert-Python $Python)) { throw 'Python 3.14 x64 com Tcl/Tk nao encontrado apos a instalacao.' }
        }
        Write-Host 'Instalando o aplicativo...'
        $Venv = Join-Path $InstallPath '.venv'
        & $Python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente isolado.' }
        $VenvPython = Join-Path $Venv 'Scripts\python.exe'
        & $VenvPython -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r (Join-Path $AppPath 'requirements-win.lock')
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias. O atalho anterior foi preservado.' }
        Write-Host 'Verificando a instalacao...'
        & $VenvPython (Join-Path $AppPath 'scripts\smoke.py')
        if ($LASTEXITCODE -ne 0) { throw 'A verificacao do aplicativo falhou. O atalho anterior foi preservado.' }
        Write-Host 'Criando o atalho...'
        $Desktop = [Environment]::GetFolderPath('DesktopDirectory')
        if (-not $Desktop) { throw 'Pasta da Area de Trabalho indisponivel.' }
        [IO.Directory]::CreateDirectory($Desktop) | Out-Null
        $ShortcutPath = Join-Path $Desktop 'Ocultar Dados.lnk'
        $Shell = New-Object -ComObject WScript.Shell
        if (Test-Path -LiteralPath $ShortcutPath) {
            $Existing = $Shell.CreateShortcut($ShortcutPath)
            if (-not (Get-CanonicalPath $Existing.TargetPath).StartsWith((Get-CanonicalPath $AppRoot) + '\',[StringComparison]::OrdinalIgnoreCase)) {
                throw 'Ja existe um atalho Ocultar Dados de outro aplicativo. Renomeie-o e tente novamente.'
            }
        }
        $NewShortcutPath = Join-Path $Desktop ('.ocultar-dados-' + [guid]::NewGuid().ToString('N') + '.lnk')
        $BackupShortcutPath = $NewShortcutPath + '.backup'
        $Shortcut = $Shell.CreateShortcut($NewShortcutPath)
        $Shortcut.TargetPath = Join-Path $Venv 'Scripts\pythonw.exe'
        $Shortcut.Arguments = '"' + (Join-Path $AppPath 'interface.py') + '"'
        $Shortcut.WorkingDirectory = $AppPath
        $Shortcut.Description = 'Ocultar Dados - Pedido Interno e NFe'
        $Shortcut.IconLocation = (Join-Path $AppPath 'assets\icon.ico') + ',0'
        $Shortcut.Save()
        try {
            if (Test-Path -LiteralPath $ShortcutPath) {
                [IO.File]::Replace($NewShortcutPath, $ShortcutPath, $BackupShortcutPath)
            } else {
                [IO.File]::Move($NewShortcutPath, $ShortcutPath)
            }
        } finally {
            if (Test-Path -LiteralPath $NewShortcutPath) { Remove-Item -LiteralPath $NewShortcutPath -Force }
        }
        if (-not (Test-Path -LiteralPath $ShortcutPath)) { throw 'Atalho nao foi criado.' }
        if (Test-Path -LiteralPath $BackupShortcutPath) { Remove-Item -LiteralPath $BackupShortcutPath -Force }
        Write-Host 'Instalacao concluida. Abra Ocultar Dados na Area de Trabalho.'
        return $InstallPath
    } finally {
        # Only the unique temporary directory created by this invocation is removed.
        if (Test-Path -LiteralPath $TempPath) { Remove-Item -LiteralPath $TempPath -Recurse -Force }
    }
}
if ($MyInvocation.InvocationName -ne '.') {
    try { Install-App | Out-Null }
    catch { Write-Error $_; exit 1 }
}
