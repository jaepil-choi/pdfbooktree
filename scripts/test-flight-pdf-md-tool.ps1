$popplerBin = 'D:\chljeffreyz\utils\poppler-26.02.0\Library\bin'
$pdftoppm = Join-Path $popplerBin 'pdftoppm.exe'

if (-not (Test-Path -LiteralPath $pdftoppm -PathType Leaf)) {
    throw "Poppler 실행 파일을 찾을 수 없습니다: $pdftoppm"
}

# uv로 실행되는 하위 프로세스에서도 Poppler를 찾을 수 있도록 현재 작업의 PATH에 추가한다.
$env:Path = "$popplerBin;$env:Path"

# 모델 호스팅 자동 탐색을 생략하고 Paddle 공식 BOS 저장소를 직접 사용한다.
$env:PADDLE_PDX_MODEL_SOURCE = 'bos'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = '1'

# Paddle의 C++ 추론기가 한글 사용자 경로를 잘못 해석하므로 ASCII 전용 경로를 사용한다.
$paddlexCache = 'D:\chljeffreyz\utils\paddlex-cache'
$paddleTemp = 'D:\chljeffreyz\utils\pdf-md-temp'
$env:PADDLE_PDX_CACHE_HOME = $paddlexCache
$env:TEMP = $paddleTemp
$env:TMP = $paddleTemp
New-Item -ItemType Directory -Force -Path $paddlexCache, $paddleTemp | Out-Null

# 기존에 정상적으로 다운로드된 모델을 재사용해 다시 내려받지 않는다.
$legacyModel = Join-Path $HOME '.paddlex\official_models\PP-OCRv5_server_det'
$cachedModel = Join-Path $paddlexCache 'official_models\PP-OCRv5_server_det'
if ((Test-Path -LiteralPath $legacyModel -PathType Container) -and
    -not (Test-Path -LiteralPath $cachedModel -PathType Container)) {
    $cachedModelParent = Split-Path -Parent $cachedModel
    New-Item -ItemType Directory -Force -Path $cachedModelParent | Out-Null
    Copy-Item -LiteralPath $legacyModel -Destination $cachedModel -Recurse
}
$inputPdf = 'data\scanned-pdf-not-indexed\금리의_경제학_-_홍완표.pdf'
$outputDir = 'experiments\outputs\금리의_경제학_pdf_md_harness'
$outputMd = Join-Path $outputDir '금리의_경제학.md'
$logFile = Join-Path $outputDir 'run.log'
$statusFile = Join-Path $outputDir 'job-status.json'

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$paddleVenv = 'references\pdf-md-harness-clean\.venv-paddle'
$paddlePython = Join-Path $paddleVenv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $paddlePython -PathType Leaf)) {
    Write-Host "PaddleOCR용 가상환경을 만듭니다: $paddleVenv"
    & uv run python -m venv $paddleVenv
    if ($LASTEXITCODE -ne 0) {
        throw "PaddleOCR용 가상환경 생성에 실패했습니다. 종료 코드: $LASTEXITCODE"
    }
}
$truststorePackage = Join-Path $paddleVenv 'Lib\site-packages\truststore'
if (-not (Test-Path -LiteralPath $truststorePackage -PathType Container)) {
    Write-Host 'Windows 인증서 저장소 연동 패키지를 설치합니다: truststore'
    & uv pip install --python $paddlePython truststore
    if ($LASTEXITCODE -ne 0) {
        throw "truststore 설치에 실패했습니다. 종료 코드: $LASTEXITCODE"
    }
}

$startedAt = Get-Date
& uv run python 'references\pdf-md-harness-clean\ocr_pdf_to_markdown.py' `
    $inputPdf `
    $outputMd `
    --engine paddle `
    --dpi 300 `
    --title '금리의 경제학' `
    --paddle-venv $paddleVenv `
    2>&1 | Tee-Object -FilePath $logFile

$exitCode = $LASTEXITCODE
$finishedAt = Get-Date

[ordered]@{
    input_pdf   = (Resolve-Path $inputPdf).Path
    output_md   = [System.IO.Path]::GetFullPath($outputMd)
    log_file    = [System.IO.Path]::GetFullPath($logFile)
    started_at  = $startedAt.ToString('o')
    finished_at = $finishedAt.ToString('o')
    elapsed     = ($finishedAt - $startedAt).ToString()
    exit_code   = $exitCode
    succeeded   = ($exitCode -eq 0)
} | ConvertTo-Json | Set-Content -Encoding utf8 $statusFile

if ($exitCode -ne 0) {
    throw "OCR 작업이 실패했습니다. 종료 코드: $exitCode, 로그: $logFile"
}

Write-Host "완료: $outputMd"
Write-Host "상태: $statusFile"
