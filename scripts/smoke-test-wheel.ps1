param(
    [Parameter(Mandatory = $true)]
    [string]$SamplePdf,

    [string]$OutputRoot = "experiments/outputs/wheel-smoke"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step 실패: exit_code=$LASTEXITCODE"
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ResolvedSamplePdf = (Resolve-Path $SamplePdf).Path
$ResolvedOutputRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $RepoRoot $OutputRoot)
)
$Timestamp = Get-Date -Format "yyyyMMddTHHmmssfff"
$RunDir = Join-Path $ResolvedOutputRoot $Timestamp
$DistDir = Join-Path $RunDir "dist"
$VenvDir = Join-Path $RunDir "venv"
$ProjectDir = Join-Path $RunDir "project"
$ProcessOutputDir = Join-Path $RunDir "process-output"

New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
New-Item -ItemType Directory -Force -Path $ProjectDir | Out-Null

Push-Location $RepoRoot
try {
    uv build --no-index --out-dir $DistDir
    Assert-LastExitCode "wheel build"

    $Wheel = Get-ChildItem $DistDir -Filter "*.whl" |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
    if ($null -eq $Wheel) {
        throw "생성된 wheel을 찾지 못했다: $DistDir"
    }

    uv venv --python 3.12 $VenvDir
    Assert-LastExitCode "clean virtual environment 생성"

    $PythonExe = Join-Path $VenvDir "Scripts/python.exe"
    $CliExe = Join-Path $VenvDir "Scripts/pdfbooktree.exe"
    uv pip install --python $PythonExe $Wheel.FullName
    Assert-LastExitCode "wheel 설치"

    $MetadataPayload = & $PythonExe -c @"
import json
from importlib.metadata import metadata

value = metadata("pdfbooktree")
print(json.dumps({
    "license_expression": value["License-Expression"],
    "license_files": value.get_all("License-File") or [],
    "project_urls": value.get_all("Project-URL") or [],
    "keywords": value["Keywords"],
    "classifiers": value.get_all("Classifier") or [],
}))
"@ | ConvertFrom-Json
    Assert-LastExitCode "설치 wheel metadata"
    if ($MetadataPayload.license_expression -ne "MIT") {
        throw "wheel License-Expression이 MIT가 아니다."
    }
    if ($MetadataPayload.license_files -notcontains "LICENSE") {
        throw "wheel metadata가 LICENSE 파일을 연결하지 않는다."
    }

    $VersionOutput = & $CliExe --version
    Assert-LastExitCode "CLI --version"

    & $CliExe --help | Out-Null
    Assert-LastExitCode "CLI --help"

    $ConfigPayload = & $CliExe config schema --format json |
        ConvertFrom-Json
    Assert-LastExitCode "config schema"
    if (-not $ConfigPayload.ok) {
        throw "config schema JSON 결과가 실패다."
    }

    $InspectPayload = & $CliExe inspect page-count $ResolvedSamplePdf --format json |
        ConvertFrom-Json
    Assert-LastExitCode "실제 PDF inspect"
    if (-not $InspectPayload.ok -or $InspectPayload.result.page_count -lt 1) {
        throw "실제 PDF inspect 결과가 유효하지 않다."
    }

    $ProcessPayload = & $CliExe process $ResolvedSamplePdf `
        -o $ProcessOutputDir `
        --format json |
        ConvertFrom-Json
    Assert-LastExitCode "실제 PDF process"
    if (
        -not $ProcessPayload.ok -or
        $ProcessPayload.result.result.status -ne "processed"
    ) {
        throw "설치 wheel의 실제 PDF process 결과가 processed가 아니다."
    }

    $SkillPayload = & $CliExe skill install `
        --project-dir $ProjectDir `
        --format json |
        ConvertFrom-Json
    Assert-LastExitCode "package skill 설치"
    if (-not $SkillPayload.ok) {
        throw "package skill 설치 결과가 실패다."
    }

    $InstalledSkillRoot = Join-Path $ProjectDir ".agents/skills/use-pdfbooktree"
    $InstalledSkillFiles = Get-ChildItem $InstalledSkillRoot -Recurse -File
    if ($InstalledSkillFiles.Count -ne 5) {
        throw "설치된 package skill 파일 수가 5가 아니다: $($InstalledSkillFiles.Count)"
    }

    $Result = [ordered]@{
        status = "passed"
        wheel = $Wheel.FullName
        version = [string]$VersionOutput
        license_expression = [string]$MetadataPayload.license_expression
        license_files = @($MetadataPayload.license_files)
        project_url_count = @($MetadataPayload.project_urls).Count
        classifier_count = @($MetadataPayload.classifiers).Count
        sample_pdf = $ResolvedSamplePdf
        sample_page_count = [int]$InspectPayload.result.page_count
        process_run_dir = [string]$ProcessPayload.result.run_dir
        process_status = [string]$ProcessPayload.result.result.status
        bookmark_count = [int]$ProcessPayload.result.result.bookmark_count
        markdown_manifest = [string](
            $ProcessPayload.result.result.artifact_paths.markdown_manifest
        )
        installed_skill_file_count = [int]$InstalledSkillFiles.Count
        run_dir = $RunDir
        ran_at = (Get-Date).ToString("o")
    }
    $ResultPath = Join-Path $RunDir "result.json"
    $Result | ConvertTo-Json -Depth 8 |
        Set-Content -Path $ResultPath -Encoding utf8
    $Result | ConvertTo-Json -Depth 8
}
finally {
    Pop-Location
}
