<#
.SYNOPSIS
    Testes unitários das funções de processo do launcher do Studio.

.DESCRIPTION
    Exercita `studio-common.ps1` com processos, portas e WMI falsos. Não abre
    navegador nem inicia serviço algum. Sem Pester instalado, sai 0 com
    instrução explícita: a cobertura equivalente vive em
    tests/scripts/test_state_parser.py, que drive as mesmas funções via
    powershell.exe.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# O Windows traz Pester 3.4, que não tem `Should -Throw` com wildcard nem
# `-BeNullOrEmpty` no formato exigido aqui. Só Pester 5+ serve.
$pester = Get-Module -ListAvailable -Name Pester |
    Where-Object { $_.Version -ge [Version]'5.0' } |
    Select-Object -First 1

if ($null -eq $pester) {
    Write-Host 'Pester não instalado; execute o teste unitário Python de parser de estado'
    exit 0
}

Import-Module Pester -MinimumVersion 5.0

Describe 'studio-common' {
    BeforeAll {
        # Join-Path no PS 5.1 aceita apenas dois argumentos: componha em etapas.
        $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
        . (Join-Path $RepoRoot 'scripts/studio-common.ps1')
    }

    It 'grava e lê somente PIDs inteiros de API worker e web' {
        Save-StudioState -Root $TestDrive -Processes @{
            api    = @{ pid = 1001; command = 'forge-api' }
            worker = @{ pid = 1002; command = 'forge-worker' }
            web    = @{ pid = 1003; command = 'next' }
        }
        (Read-StudioState -Root $TestDrive).api.pid | Should -Be 1001
        (Read-StudioState -Root $TestDrive).worker.pid | Should -Be 1002
        (Read-StudioState -Root $TestDrive).web.pid | Should -Be 1003
    }

    It 'recusa encerrar PID cuja linha de comando não pertence ao Studio' {
        { Stop-RegisteredStudioProcess -ProcessInfo @{ pid = 77; command = 'powershell' } } |
            Should -Throw '*não pertence ao Forge Studio*'
    }

    It 'trata estado com versão desconhecida como stale e o renomeia' {
        $stateDir = Join-Path $TestDrive 'data/studio'
        New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
        Set-Content -LiteralPath (Join-Path $stateDir 'processes.json') `
            -Value '{"version":99,"processes":{}}' -Encoding UTF8

        Read-StudioState -Root $TestDrive | Should -BeNullOrEmpty
        Get-ChildItem -Path $stateDir -Filter 'processes.invalid-*.json' |
            Should -Not -BeNullOrEmpty
    }

    It 'preserva PID quando a linha de comando viva diverge do registrado' {
        Mock Get-StudioProcessCommandLine { 'powershell.exe -NoProfile' }
        { Stop-RegisteredStudioProcess -ProcessInfo @{ pid = 55; command = 'forge-api' } } |
            Should -Throw '*não pertence ao Forge Studio*'
    }
}
