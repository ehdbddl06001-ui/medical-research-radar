# 윈도우 작업 스케줄러에 '연구 공고 알리미'를 등록합니다.
#   사용:  powershell -ExecutionPolicy Bypass -File install_task.ps1 [-Hours 2]
#   해제:  powershell -ExecutionPolicy Bypass -File install_task.ps1 -Remove
param([int]$Hours = 2, [switch]$Remove)
$ErrorActionPreference = 'Stop'
$name = 'MedResearchAlert'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "작업 '$name' 을(를) 삭제했습니다."
    return
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (Get-Command pythonw -ErrorAction SilentlyContinue).Source   # 창 안 뜨는 파이썬
if (-not $py) { $py = (Get-Command python).Source }

$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$here\monitor.py`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours $Hours)
# StartWhenAvailable: PC가 꺼져 있어 놓친 실행은 켜진 뒤 바로 실행
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $set `
    -Description '의사과학자·연구 기회 공고 확인 (monitor.py)' -Force | Out-Null

Write-Host "등록 완료: $Hours 시간마다 확인합니다."
Write-Host "  실행 파일: $py"
Write-Host "  스크립트 : $here\monitor.py"
Write-Host "해제하려면: powershell -ExecutionPolicy Bypass -File install_task.ps1 -Remove"
