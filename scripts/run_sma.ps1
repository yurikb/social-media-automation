param(
    [switch]$ApproveAll = $false
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectDir "data" "logs"
$LogFile = Join-Path $LogDir "sma_$(Get-Date -Format 'yyyyMMdd').log"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$env:PYTHONUNBUFFERED = "1"
$start = Get-Date

Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SMA pipeline started" | Out-File -FilePath $LogFile -Append

Set-Location $ProjectDir

# Scan for live streamers
python -m src.cli scan 2>&1 | Out-File -FilePath $LogFile -Append

# Run pipeline (queues for review if require_approval=true)
python -m src.cli run 2>&1 | Out-File -FilePath $LogFile -Append

# Auto-approve if flag is set
if ($ApproveAll) {
    Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Auto-approving all pending..." | Out-File -FilePath $LogFile -Append
    python -m src.cli approve --all 2>&1 | Out-File -FilePath $LogFile -Append
}

$elapsed = (Get-Date) - $start
Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SMA pipeline finished in $($elapsed.TotalMinutes.ToString('0.0')) min" | Out-File -FilePath $LogFile -Append
