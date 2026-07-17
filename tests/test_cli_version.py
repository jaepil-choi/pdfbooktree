"""최상위 CLI version 계약을 검증한다."""

from typer.testing import CliRunner

from pdfbooktree.cli import app


runner = CliRunner()


def test_cli_version은_설치_metadata_version을_출력한다(monkeypatch) -> None:
    """`--version`이 package metadata를 읽고 성공 종료해야 한다."""

    monkeypatch.setattr(
        "pdfbooktree.cli.metadata.version",
        lambda package: "9.8.7" if package == "pdfbooktree" else "",
    )

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == "pdfbooktree 9.8.7\n"


def test_cli_help에_version_option이_노출된다() -> None:
    """사용자가 help에서 version option을 발견할 수 있어야 한다."""

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--version" in result.stdout
