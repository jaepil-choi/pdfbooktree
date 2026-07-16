$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$output = Join-Path $root "showcase/outputs/026_process_ocr_books_cli"
$books = @(
    @{ Name = "econometrics_note1"; Pdf = "showcase/outputs/016_econometrics_note1_ocr_overlay/kim_econometrics_note1_ocr.pdf" }
    @{ Name = "interest_economics"; Pdf = "showcase/outputs/017_interest_economics_ocr_overlay/interest_economics_ocr.pdf" }
    @{ Name = "statistics_principles"; Pdf = "showcase/outputs/018_statistics_principles_ocr_overlay/statistics_principles_ocr.pdf"; Replace = $true }
)

New-Item -ItemType Directory -Force -Path $output | Out-Null
foreach ($book in $books) {
    $arguments = @("process", (Join-Path $root $book.Pdf), "-o", (Join-Path $output $book.Name), "--format", "json")
    if ($book.Replace) { $arguments += @("--set", "outline_quality.replace_when_low_quality=true") }

    pdfbooktree @arguments | Tee-Object -FilePath (Join-Path $output "$($book.Name).json")
    if ($LASTEXITCODE -ne 0) { throw "$($book.Name) 처리에 실패했다." }
}
