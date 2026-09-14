<#
.SYNOPSIS
    Funções compartilhadas do launcher do Forge Studio.

.DESCRIPTION
    Estado de PID, validação de processo e espera de porta. O stop só encerra
    árvores cuja linha de comando pertença ao Studio — um PID reciclado pelo
    sistema nunca é morto por engano.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$StudioRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$StudioStatePath = Join-Path $StudioRoot 'data/studio/processes.json'
$StudioLogsDir = Join-Path $StudioRoot 'data/studio/logs'

# Slot -> fragmento obrigatório da linha de comando do processo.
$StudioSlots = [ordered]@{
    api    = 'forge-api'
    worker = 'forge-worker'
    web    = 'next'
}

# Fragmentos aceitos na linha de comando VIVA. O slot web é iniciado por
# npm.cmd, e só o processo filho se chama `next`; o pai carrega 'npm'. Validar
# contra o fragmento registrado sozinho recusaria o PID legítimo do web.
$StudioLivePatterns = @{
    api    = @('forge-api')
    worker = @('forge-worker')
    web    = @('next', 'npm')
}

function Get-StudioSlotCommand {
    param([Parameter(Mandatory)][string]$Slot)
    if (-not $StudioSlots.Contains($Slot)) {
        throw "Slot desconhecido: '$Slot'"
    }
    return $StudioSlots[$Slot]
}

function Save-StudioState {
    <#
    .SYNOPSIS
        Grava o estado dos processos sob data/studio/processes.json.
    #>
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][hashtable]$Processes
    )

    $payload = [ordered]@{
        version   = 1
        startedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        processes = [ordered]@{}
    }

    foreach ($slot in $StudioSlots.Keys) {
        if (-not $Processes.ContainsKey($slot)) {
            throw "Estado incompleto: falta o slot '$slot'"
        }
        $entry = $Processes[$slot]
        $procId = [int]$entry.pid
        if ($procId -le 0) {
            throw "PID inválido para '$slot': $procId"
        }
        $log = if ($entry.ContainsKey('log') -and $entry.log) {
            [string]$entry.log
        }
        else {
            "data/studio/logs/$slot.log"
        }
        $payload.processes[$slot] = [ordered]@{
            pid     = $procId
            command = [string]$entry.command
            log     = $log
        }
    }

    $stateDir = Join-Path $Root 'data/studio'
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $path = Join-Path $stateDir 'processes.json'
    $json = $payload | ConvertTo-Json -Depth 6
    # Set-Content -Encoding UTF8 no PS 5.1 grava BOM, que quebra json.loads em
    # qualquer ferramenta fora do PowerShell. Escreva UTF-8 sem BOM.
    [System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding $false))
    return $path
}

function Read-StudioState {
    <#
    .SYNOPSIS
        Lê e valida o estado; estado malformado vira stale, nunca uso cego.
    #>
    param([Parameter(Mandatory)][string]$Root)

    $path = Join-Path $Root 'data/studio/processes.json'
    if (-not (Test-Path -LiteralPath $path)) {
        return $null
    }

    try {
        $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8
        $state = $raw | ConvertFrom-Json
    }
    catch {
        return (Move-StudioStateAside -Path $path)
    }

    if ($state.version -ne 1) {
        return (Move-StudioStateAside -Path $path)
    }
    if ($null -eq $state.processes) {
        return (Move-StudioStateAside -Path $path)
    }

    $names = @($state.processes.PSObject.Properties.Name)
    if ($names.Count -ne $StudioSlots.Count) {
        return (Move-StudioStateAside -Path $path)
    }
    foreach ($slot in $StudioSlots.Keys) {
        if ($names -notcontains $slot) {
            return (Move-StudioStateAside -Path $path)
        }
        $entry = $state.processes.$slot
        $procId = 0
        if (-not [int]::TryParse([string]$entry.pid, [ref]$procId)) {
            return (Move-StudioStateAside -Path $path)
        }
        if ($procId -le 0) {
            return (Move-StudioStateAside -Path $path)
        }
        $log = [string]$entry.log
        if (-not $log.StartsWith('data/studio/logs/')) {
            return (Move-StudioStateAside -Path $path)
        }
    }

    $state
}

function Move-StudioStateAside {
    <#
    .SYNOPSIS
        Renomeia estado inválido; nunca o usa para matar processo.
    #>
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $invalid = Join-Path (Split-Path -Parent $Path) "processes.invalid-$stamp.json"
    Move-Item -LiteralPath $Path -Destination $invalid -Force
    Write-Warning "Estado do Studio inválido; movido para $invalid"
    return $null
}

function Test-StudioPortOpen {
    <#
    .SYNOPSIS
        Testa uma porta TCP local sem abrir conexão de aplicação.
    #>
    param(
        [Parameter(Mandatory)][int]$Port,
        [string]$Host_ = '127.0.0.1',
        [int]$TimeoutMs = 500
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($Host_, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Wait-StudioPort {
    <#
    .SYNOPSIS
        Espera uma porta abrir em polling de 250 ms até o prazo.
    #>
    param(
        [Parameter(Mandatory)][int]$Port,
        [int]$TimeoutSeconds = 30
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-StudioPortOpen -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Get-StudioProcessCommandLine {
    # O parâmetro não pode se chamar $Pid: $pid é automático e read-only no
    # PowerShell, e a atribuição falha em silêncio dentro da função.
    param([Parameter(Mandatory)][int]$ProcessId)

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        return $null
    }
    return [string]$proc.CommandLine
}

function Stop-RegisteredStudioProcess {
    <#
    .SYNOPSIS
        Encerra a árvore de um processo registrado, só se ele for do Studio.

.DESCRIPTION
        Duas guardas antes de matar: o comando registrado precisa ser um dos
        comandos do Studio, e a linha de comando viva precisa contê-lo. PID
        reciclado por outro programa não é encerrado.
    #>
    param(
        [Parameter(Mandatory)][hashtable]$ProcessInfo,
        [switch]$Force
    )

    $procId = [int]$ProcessInfo.pid
    $command = [string]$ProcessInfo.command
    $slot = if ($ProcessInfo.ContainsKey('slot')) { [string]$ProcessInfo.slot } else { '' }

    $patterns = @()
    if (-not [string]::IsNullOrWhiteSpace($slot)) {
        $expected = Get-StudioSlotCommand -Slot $slot
        if ($command -ne $expected) {
            throw "PID $procId não pertence ao Forge Studio (slot '$slot' espera '$expected', registrado '$command')"
        }
        if ($StudioLivePatterns.ContainsKey($slot)) {
            $patterns = @($StudioLivePatterns[$slot])
        }
    }

    if ($patterns.Count -eq 0) {
        $allowed = @($StudioSlots.Values)
        if ($allowed -notcontains $command) {
            throw "PID $procId não pertence ao Forge Studio (comando registrado '$command')"
        }
        $patterns = @($command)
    }

    $live = Get-StudioProcessCommandLine -ProcessId $procId
    if ($null -eq $live) {
        return $false  # já não existe
    }
    foreach ($pattern in $patterns) {
        if ($live -match [regex]::Escape($pattern)) {
            & taskkill.exe /PID $procId /T /F | Out-Null
            return $true
        }
    }

    throw "PID $procId não pertence ao Forge Studio (linha de comando '$live')"
}
