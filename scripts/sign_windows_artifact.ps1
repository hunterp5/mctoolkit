# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

# Authenticode-sign Windows build outputs when a certificate is configured.
# With MOLMANAGER_WINDOWS_CERT_BASE64 unset, the file is left unsigned and
# this script exits 0. A present certificate that cannot be applied fails
# the build.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Path
)

$ErrorActionPreference = "Stop"
$certB64 = $env:MOLMANAGER_WINDOWS_CERT_BASE64
if ([string]::IsNullOrWhiteSpace($certB64)) {
    Write-Host "No MOLMANAGER_WINDOWS_CERT_BASE64 secret; leaving unsigned: $($Path -join ', ')"
    exit 0
}

$pfx = Join-Path ([System.IO.Path]::GetTempPath()) ("molmanager-codesign-" + [guid]::NewGuid().ToString("n") + ".pfx")
try {
    [System.IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($certB64.Trim()))
    $signtool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if (-not $signtool) {
        throw "signtool.exe was not found in the Windows SDK. The certificate is set, so the build will not stay unsigned."
    }
    $password = $env:MOLMANAGER_WINDOWS_CERT_PASSWORD
    if ($null -eq $password) {
        $password = ""
    }
    foreach ($item in $Path) {
        if (-not (Test-Path -LiteralPath $item)) {
            throw "Cannot sign missing file: $item"
        }
        & $signtool.FullName sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /f $pfx /p $password $item
        if ($LASTEXITCODE -ne 0) {
            throw "signtool failed for $item (exit $LASTEXITCODE)"
        }
        Write-Host "Signed $item"
    }
}
finally {
    if (Test-Path -LiteralPath $pfx) {
        Remove-Item -LiteralPath $pfx -Force
    }
}
