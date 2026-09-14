<#
.SYNOPSIS
    Encerra o Forge Studio de forma cooperativa e idempotente.

.DESCRIPTION
    Tenta antes uma pausa cooperativa via API para que o worker pare no limite
    seguro da etapa. Depois encerra as árvores registradas — sempre validando
    a linha de comando, mesmo com -Force.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 300)]
    [int]$GraceSeconds = 30,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'studio-common.ps1')

$ApiPort = 8765
$ApiBase = "http://127.0.0.1:$ApiPort"
$PausableStatuses = @('preparing', 'running', 'pausing')
$SettledStatuses = @('paused', 'failed', 'interrupted', 'completed')

if (-not (Test-Path -LiteralPath $StudioStatePath)) {
    Write-Host 'Forge Studio não está em execução'
    exit 0
}

$state = Read-StudioState -Root $StudioRoot
if ($null -eq $state) {
    Write-Host 'Forge Studio não está em execução'
    exit 0
}

function Invoke-StudioPause {
    <# Pausa cooperativa; ausência da API não é erro. #>
    param([int]$TimeoutSeconds)

    if (-not (Test-StudioPortOpen -Port $ApiPort)) {
        return
    }

    try {
        $page = Invoke-RestMethod -Uri "$ApiBase/api/runs?limit=100" -TimeoutSec 5
    }
    catch {
        Write-Warning "API não respondeu ao listar runs: $($_.Exception.Message)"
        return
    }

    $runs = @($page.items)
    foreach ($item in $runs) {
        $status = [string]$item.run.status
        if ($PausableStatuses -notcontains $status) {
            continue
        }
        try {
            Invoke-RestMethod -Method Post -Uri "$ApiBase/api/runs/$($item.run.id)/pause" `
                -Headers @{ 'Idempotency-Key' = "stop-$($item.run.id)" } -TimeoutSec 5 | Out-Null
        }
        catch {
            Write-Warning "Falha ao solicitar pausa de $($item.run.id): $($_.Exception.Message)"
        }
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $page = Invoke-RestMethod -Uri "$ApiBase/api/runs?limit=100" -TimeoutSec 5
        }
        catch {
            return
        }
        $pending = @($page.items | Where-Object { $PausableStatuses -contains [string]$_.run.status })
        if ($pending.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    Write-Warning "Pausa cooperativa não concluiu em ${TimeoutSeconds}s; encerrando."
}

if (-not $Force) {
    Invoke-StudioPause -TimeoutSeconds $GraceSeconds
}

$remaining = @()
foreach ($slot in $StudioSlots.Keys) {
    $entry = @{
        slot    = $slot
        pid     = [int]$state.processes.$slot.pid
        command = [string]$state.processes.$slot.command
    }
    if ($null -eq (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue)) {
        continue
    }
    if (Stop-RegisteredStudioProcess -ProcessInfo $entry -Force:$Force) {
        $remaining += $entry.pid
    }
}

# O arquivo de estado só some depois de todo PID ter terminado ou não existir.
$alive = @($remaining | Where-Object { $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
if ($alive.Count -gt 0) {
    Write-Warning "PIDs ainda vivos: $($alive -join ', '); estado preservado para nova tentativa."
    exit 1
}

Remove-Item -LiteralPath $StudioStatePath -Force
Write-Host 'Forge Studio encerrado.'
exit 0
