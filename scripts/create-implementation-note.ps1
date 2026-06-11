<#
.SYNOPSIS
마지막 구현 커밋에 대한 implementation note 초안을 생성한다.

.DESCRIPTION
이 스크립트는 Git의 마지막 커밋 ID를 읽고
docs/vibe/implementations/NNN_{commit_id}.md 형식의 문서를 생성한다.

기본 대상은 HEAD이며, 필요하면 -Commit 옵션으로 다른 커밋을 지정할 수 있다.
기존 파일은 -Force를 주지 않는 한 덮어쓰지 않는다.

.EXAMPLE
.\scripts\create-implementation-note.ps1

.EXAMPLE
.\scripts\create-implementation-note.ps1 -Commit HEAD~1

.EXAMPLE
.\scripts\create-implementation-note.ps1 -WhatIf
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [string] $Commit = "HEAD",

    [Parameter()]
    [string] $ImplementationsDir = "docs/vibe/implementations",

    [Parameter()]
    [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $GitArgs
    )

    $output = & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') 명령이 실패했다."
    }

    return $output
}

function Get-NextImplementationNumber {
    param(
        [Parameter(Mandatory = $true)]
        [string] $DirectoryPath
    )

    if (-not (Test-Path -LiteralPath $DirectoryPath)) {
        return 1
    }

    $numbers = Get-ChildItem -LiteralPath $DirectoryPath -Filter "*.md" -File |
        ForEach-Object {
            if ($_.Name -match '^(\d{3})_') {
                [int] $Matches[1]
            }
        }

    if (-not $numbers) {
        return 1
    }

    $maximum = ($numbers | Measure-Object -Maximum).Maximum
    return ([int] $maximum + 1)
}

$repoRoot = (Invoke-Git -GitArgs @("rev-parse", "--show-toplevel") | Select-Object -First 1).Trim()
$shortCommitId = (Invoke-Git -GitArgs @("rev-parse", "--short=12", $Commit) | Select-Object -First 1).Trim()
$fullCommitId = (Invoke-Git -GitArgs @("rev-parse", $Commit) | Select-Object -First 1).Trim()
$commitSubject = (Invoke-Git -GitArgs @("log", "-1", "--format=%s", $Commit) | Select-Object -First 1).Trim()
$commitDate = (Invoke-Git -GitArgs @("log", "-1", "--format=%aI", $Commit) | Select-Object -First 1).Trim()

$implementationDirPath = Join-Path -Path $repoRoot -ChildPath $ImplementationsDir
$existingNoteForCommit = $null
if (Test-Path -LiteralPath $implementationDirPath) {
    $existingNoteForCommit = Get-ChildItem -LiteralPath $implementationDirPath -Filter "*_$shortCommitId.md" -File |
        Select-Object -First 1
}

if ($existingNoteForCommit) {
    $notePath = $existingNoteForCommit.FullName
    if (-not $Force) {
        throw "이미 이 커밋의 implementation note가 존재한다: $notePath. 덮어쓰려면 -Force를 사용한다."
    }
}
else {
    $nextNumber = [int] (Get-NextImplementationNumber -DirectoryPath $implementationDirPath)
    $fileName = "{0:D3}_{1}.md" -f $nextNumber, $shortCommitId
    $notePath = Join-Path -Path $implementationDirPath -ChildPath $fileName
}

if ((Test-Path -LiteralPath $notePath) -and (-not $Force)) {
    throw "이미 파일이 존재한다: $notePath. 덮어쓰려면 -Force를 사용한다."
}

$createdAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")

$content = @"
# 구현 노트: $commitSubject

## 메타데이터

- 구현 커밋: ``$shortCommitId``
- 전체 커밋 ID: ``$fullCommitId``
- 커밋 일시: ``$commitDate``
- 노트 생성 일시: ``$createdAt``

## 변경 배경

- TODO: 이 구현이 필요했던 이유를 적는다.
- TODO: 실험이나 요구사항에서 확인한 근거를 적는다.

## 결정 내용

- TODO: 이번 커밋에서 내린 주요 설계 결정을 적는다.
- TODO: public interface, 내부 구조, 데이터 모델, 알고리즘 선택이 있다면 함께 적는다.

## 작동 방식

- TODO: 변경된 코드가 어떤 흐름으로 동작하는지 적는다.
- TODO: 중요한 입력, 출력, 예외 처리, 1-based page convention 같은 규칙이 있으면 적는다.

## 검증

- TODO: 실행한 검증 명령을 적는다.
- TODO: 테스트하지 못한 부분이 있으면 이유를 적는다.

## 대안과 제외한 선택지

- TODO: 고려했지만 선택하지 않은 접근과 그 이유를 적는다.

## 남은 리스크

- TODO: 후속 작업, 알려진 제약, 낮은 confidence 지점을 적는다.
"@

if ($PSCmdlet.ShouldProcess($notePath, "implementation note 생성")) {
    New-Item -ItemType Directory -Path $implementationDirPath -Force | Out-Null
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($notePath, $content, $utf8NoBom)
}

Write-Output $notePath
