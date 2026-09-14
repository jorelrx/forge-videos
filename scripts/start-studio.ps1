<#
.SYNOPSIS
    Inicia API, worker e web do Forge Studio localmente.

.DESCRIPTION
    Valida a máquina, aplica a migração SQLite, inicia os três processos com
    logs sob data/studio/logs e registra os PIDs em data/studio/processes.json.
    Não inicia Docker, banco externo nem navegador fora do previsto aqui.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [ValidateSet('dev', 'production')]
    [string]$WebMode = 'dev',
    [ValidateRange(1, 300)]
    [int]$GraceSeconds = 30,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'studio-common.ps1')

$ApiPort = 8765
$WebPort = 3100
$WebUrls = "http://127.0.0.1:$WebPort"

function Get-LiveStudioState {
    $state = Read-StudioState -Root $StudioRoot
    if ($null -eq $state) {
        return $null
    }
    foreach ($slot in $StudioSlots.Keys) {
        # $pid é automático e read-only no PowerShell: usar o nome falha.
        $procId = [int]$state.processes.$slot.pid
        if ($null -eq (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
            return $null
        }
    }
    return $state
}

New-Item -ItemType Directory -Force -Path $StudioLogsDir | Out-Null

# 1. Já em execução: não duplicar processos.
$running = Get-LiveStudioState
if ($null -ne $running -and -not $Force) {
    Write-Host 'Forge Studio já está em execução.'
    Write-Host "  web:    $WebUrls"
    Write-Host "  api:    http://127.0.0.1:$ApiPort"
    Write-Host "  logs:   $StudioLogsDir"
    exit 0
}

# 2. Doctor: valida a máquina e aplica a migração. Falha aqui encerra antes de
#    qualquer processo subir — meio Studio no ar é pior que nenhum.
Push-Location $StudioRoot
try {
    & uv run forge-studio-doctor --migrate
    if ($LASTEXITCODE -ne 0) {
        Write-Host "forge-studio-doctor falhou (exit $LASTEXITCODE); Studio não iniciado." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

# 3. Estado stale/forçado: só PIDs validados são encerrados.
if ($null -ne $running -or $Force -or (Test-Path -LiteralPath $StudioStatePath)) {
    & (Join-Path $PSScriptRoot 'stop-studio.ps1') -Force
}

$apiLog = Join-Path $StudioLogsDir 'api.log'
$apiErrLog = Join-Path $StudioLogsDir 'api.err.log'
$workerLog = Join-Path $StudioLogsDir 'worker.log'
$workerErrLog = Join-Path $StudioLogsDir 'worker.err.log'
$webLog = Join-Path $StudioLogsDir 'web.log'
$webErrLog = Join-Path $StudioLogsDir 'web.err.log'
foreach ($log in @(
        $apiLog, $apiErrLog, $workerLog, $workerErrLog, $webLog, $webErrLog
    )) {
    if (Test-Path -LiteralPath $log) {
        Remove-Item -LiteralPath $log -Force
    }
}

$webScript = if ($WebMode -eq 'production') { 'start' } else { 'dev' }

# 4. Início oculto, sempre com o diretório raiz como cwd. O Windows PowerShell
#    5.1 recusa Start-Process com stdout e stderr no mesmo arquivo, então cada
#    slot tem um par de logs.
$api = Start-Process -FilePath 'uv' -ArgumentList @('run', 'forge-api') `
    -WorkingDirectory $StudioRoot -WindowStyle Hidden `
    -RedirectStandardOutput $apiLog -RedirectStandardError $apiErrLog -PassThru
$worker = Start-Process -FilePath 'uv' -ArgumentList @('run', 'forge-worker') `
    -WorkingDirectory $StudioRoot -WindowStyle Hidden `
    -RedirectStandardOutput $workerLog -RedirectStandardError $workerErrLog -PassThru
$web = Start-Process -FilePath 'npm.cmd' `
    -ArgumentList @('--prefix', 'web', 'run', $webScript, '--', '-H', '127.0.0.1', '-p', "$WebPort") `
    -WorkingDirectory $StudioRoot -WindowStyle Hidden `
    -RedirectStandardOutput $webLog -RedirectStandardError $webErrLog -PassThru

# 5. O estado é gravado imediatamente após o start. Sem isso, uma falha entre
#    subir os processos e validá-los deixaria órfãos que o stop não encontra —
#    foi exatamente o que aconteceu antes desta ordem. O estado é removido no
#    caminho de falha, então um start malsucedido nunca o deixa para trás.
Save-StudioState -Root $StudioRoot -Processes @{
    api    = @{ pid = $api.Id; command = 'forge-api'; log = 'data/studio/logs/api.log' }
    worker = @{ pid = $worker.Id; command = 'forge-worker'; log = 'data/studio/logs/worker.log' }
    web    = @{ pid = $web.Id; command = 'next'; log = 'data/studio/logs/web.log' }
} | Out-Null

function Stop-FailedStart {
    param([string]$Reason)
    & (Join-Path $PSScriptRoot 'stop-studio.ps1') -Force | Out-Null
    Write-Host $Reason -ForegroundColor Red
    foreach ($entry in @(
            @('api', $apiLog), @('api stderr', $apiErrLog),
            @('worker', $workerLog), @('worker stderr', $workerErrLog),
            @('web', $webLog), @('web stderr', $webErrLog)
        )) {
        Write-Host "--- últimos 40: $($entry[1]) ---"
        if (Test-Path -LiteralPath $entry[1]) {
            Get-Content -LiteralPath $entry[1] -Tail 40
        }
    }
    exit 1
}

# 6. Espera as portas; qualquer falha desfaz o que subiu e mostra os logs.
$apiPortOpen = Wait-StudioPort -Port $ApiPort -TimeoutSeconds 30
$webPortOpen = Wait-StudioPort -Port $WebPort -TimeoutSeconds 30
# O @() precisa envolver o pipeline inteiro: sem isso, nada morrendo dá $null e
# `.Count` falha sob StrictMode.
$died = @(@($api, $worker, $web) | Where-Object { $_.HasExited })

if (-not $apiPortOpen -or -not $webPortOpen -or $died.Count -gt 0) {
    Stop-FailedStart -Reason "Forge Studio não subiu (api=$apiPortOpen web=$webPortOpen mortos=$($died.Count))."
}

Write-Host 'Forge Studio iniciado.'
Write-Host "  web:    $WebUrls"
Write-Host "  api:    http://127.0.0.1:$ApiPort"
Write-Host "  logs:   $StudioLogsDir"

if (-not $NoBrowser) {
    Start-Process $WebUrls
}

exit 0
