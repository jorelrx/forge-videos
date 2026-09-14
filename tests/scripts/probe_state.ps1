<#
.SYNOPSIS
    Sonda o estado do Studio para os testes Python.

.DESCRIPTION
    Existe porque o Windows PowerShell 5.1 desta máquina não tem Pester: a
    cobertura das mesmas funções roda daqui, via powershell.exe. Cada modo
    imprime uma linha estável que o teste Python interpreta.

    Modos:
      read   -> imprime o JSON do estado, ou NULL
      save   -> grava o estado a partir de -Pid/-Command e imprime SAVED
      stop   -> chama Stop-RegisteredStudioProcess e imprime STOPPED/THREW
      stale  -> chama Read-StudioState sobre estado inválido e imprime o veredito
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][ValidateSet('read', 'save', 'stop', 'stale')][string]$Mode,
    [int]$Pid_ = 0,
    [string]$Command = 'forge-api'
)

$ErrorActionPreference = 'Stop'

# O Windows PowerShell 5.1 escreve na codepage do console por padrão; o teste
# Python lê UTF-8 e palavras como "não" chegam quebradas sem isto.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# O aviso de estado stale é para quem opera o launcher, não para esta sonda:
# ele poluiria a linha que o teste Python interpreta.
$WarningPreference = 'SilentlyContinue'

# Join-Path no PS 5.1 aceita apenas dois argumentos: componha em etapas.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $RepoRoot 'scripts/studio-common.ps1')

switch ($Mode) {
    'read' {
        $state = Read-StudioState -Root $Root
        if ($null -eq $state) {
            Write-Output 'NULL'
        }
        else {
            Write-Output ($state | ConvertTo-Json -Compress -Depth 6)
        }
    }
    'save' {
        Save-StudioState -Root $Root -Processes @{
            api    = @{ pid = $Pid_; command = $Command }
            worker = @{ pid = ($Pid_ + 1); command = 'forge-worker' }
            web    = @{ pid = ($Pid_ + 2); command = 'next' }
        } | Out-Null
        Write-Output 'SAVED'
    }
    'stop' {
        try {
            Stop-RegisteredStudioProcess -ProcessInfo @{ pid = $Pid_; command = $Command } | Out-Null
            Write-Output 'STOPPED'
        }
        catch {
            Write-Output "THREW: $($_.Exception.Message)"
        }
    }
    'stale' {
        $state = Read-StudioState -Root $Root
        if ($null -eq $state) {
            Write-Output 'NULL'
        }
        else {
            Write-Output 'STATE'
        }
    }
}
