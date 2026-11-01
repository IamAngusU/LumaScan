[CmdletBinding()]
param([ValidateSet('start','stop','status')][string]$Action='status',[string]$LanIP='')
$ErrorActionPreference='Stop'
$scanRoot=Split-Path -Parent $PSScriptRoot
$scanPython=Join-Path $scanRoot '.venv\Scripts\python.exe'
$scanRuntime=Join-Path $scanRoot 'runtime'
$scanPid=Join-Path $scanRuntime 'service.pid'
New-Item -ItemType Directory -Path $scanRuntime -Force | Out-Null
if($Action -eq 'stop'){
 if(Test-Path -LiteralPath $scanPid){
  $scanProcessId=[int](Get-Content -LiteralPath $scanPid -Raw)
  $scanProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$scanProcessId"
  if($scanProcess){
   if($scanProcess.CommandLine -notmatch 'lumascan\.cli' -or $scanProcess.CommandLine -notlike "*$scanRoot*"){throw 'Recorded process does not belong to this LumaScan instance'}
   $scanChildren=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$scanProcessId")
   foreach($scanChild in $scanChildren){if($scanChild.CommandLine -notmatch 'lumascan\.cli'){throw 'Unexpected child process; stop refused'}}
   foreach($scanChild in $scanChildren){Stop-Process -Id $scanChild.ProcessId -ErrorAction SilentlyContinue}
   Stop-Process -Id $scanProcessId -ErrorAction SilentlyContinue
  }
  Remove-Item -LiteralPath $scanPid
 }
 Write-Output 'LumaScan stopped; archive retained.';exit
}
$scanHealth=$null
try{$scanHealth=Invoke-RestMethod 'http://127.0.0.1:8772/healthz' -TimeoutSec 2}catch{}
if($Action -eq 'status'){if($scanHealth){$scanHealth|ConvertTo-Json -Compress}else{Write-Output 'LumaScan stopped'};exit}
if($scanHealth){Write-Output 'Already running: http://127.0.0.1:8772';exit}
$scanArgs=@('-m','lumascan.cli','--root',('"'+$scanRoot+'"'))
if($LanIP){$scanArgs+=@('--lan-ip',$LanIP)}
$scanStarted=Start-Process -FilePath $scanPython -ArgumentList $scanArgs -WorkingDirectory $scanRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $scanRuntime 'service.out.log') -RedirectStandardError (Join-Path $scanRuntime 'service.err.log')
$scanStarted.Id|Set-Content -LiteralPath $scanPid -Encoding ASCII
for($scanAttempt=0;$scanAttempt -lt 30;$scanAttempt++){
 Start-Sleep -Milliseconds 250
 try{$scanHealth=Invoke-RestMethod 'http://127.0.0.1:8772/healthz' -TimeoutSec 1}catch{continue}
 Write-Output 'LumaScan: http://127.0.0.1:8772';exit
}
throw 'LumaScan startup failed; inspect runtime/service.err.log'
