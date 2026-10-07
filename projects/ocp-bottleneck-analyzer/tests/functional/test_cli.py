import json

from typer.testing import CliRunner

from ocp_analyzer.cli import app

runner = CliRunner()


def test_cli_deployments_demo():
    result = runner.invoke(app, ["deployments", "--demo"])
    assert result.exit_code == 0, result.output
    assert "checkout-service" in result.output


def test_cli_analyze_demo(tmp_path):
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    result = runner.invoke(
        app, ["analyze", "--demo", "-d", "checkout-service", "--no-llm", "-o", str(md), "--json", str(js)]
    )
    assert result.exit_code == 0, result.output
    assert "Top bottlenecks" in result.output
    assert md.read_text().startswith("# Bottleneck report")
    assert json.loads(js.read_text())["snapshot"]["deployment_name"] == "checkout-service"
