param(
  [string]$ServiceName = "Req2CodeApproval",
  [string]$Host = "127.0.0.1",
  [int]$Port = 8088,
  [string]$PythonExe = "python"
)

$root = Split-Path -Parent $PSScriptRoot
$cmd = "$PythonExe -m req2code.main serve-approval --host $Host --port $Port"

Write-Host "Installing service $ServiceName ..."
sc.exe create $ServiceName binPath= "cmd /c cd /d $root && $cmd" start= auto
sc.exe description $ServiceName "Req2Code approval callback service"
sc.exe start $ServiceName
Write-Host "Service $ServiceName started."
