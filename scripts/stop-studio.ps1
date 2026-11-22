<#
.SYNOPSIS
    Encerra o Forge Studio de forma cooperativa e idempotente.

.DESCRIPTION
    Tenta antes uma pausa cooperativa pelo control plane local para que o worker pare no limite
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
    param([int]$TimeoutSeconds)
    Push-Location $StudioRoot
    try {
        & uv run python -m forge.studio.pausar --prazo $TimeoutSeconds
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "A pausa cooperativa não terminou dentro do prazo."
        }
    }
    finally { Pop-Location }
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
