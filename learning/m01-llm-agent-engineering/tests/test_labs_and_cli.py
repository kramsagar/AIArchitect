import importlib

import pytest

from m01_agent.cli import main

LABS = [
    "l01_llm_basics",
    "l02_instruction_roles",
    "l03_context_engineering",
    "l04_structured_output",
    "l05_function_calling",
    "l06_agent_loop",
    "l07_resilience",
]


@pytest.mark.parametrize("lab", LABS)
def test_lab_runs(lab, capsys):
    importlib.import_module(f"m01_agent.labs.{lab}").main()
    assert capsys.readouterr().out


def test_cli_ask_and_bench(capsys):
    assert main(["ask", "Is search-api healthy?", "--trace"]) == 0
    assert "[OK]" in capsys.readouterr().out
    assert main(["bench", "--requests", "20", "--concurrency", "4"]) == 0
    assert '"throughput_rps"' in capsys.readouterr().out
    assert main(["schemas"]) == 0


def test_load_dotenv_parses_comments_quotes_and_never_overrides(tmp_path, monkeypatch):
    from m01_agent.config import load_dotenv

    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "AGENT_PROVIDER=anthropic              # mock | anthropic\n"
        "M01_TEST_KEY=sk-ant-abc#notcomment\n"
        'export M01_TEST_QUOTED="a # b"\n'
        "M01_TEST_SET=from-file\n"
        "M01_TEST_EMPTY=\n",
        encoding="utf-8",
    )
    for k in ("AGENT_PROVIDER", "M01_TEST_KEY", "M01_TEST_QUOTED", "M01_TEST_EMPTY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("M01_TEST_SET", "from-shell")
    loaded = load_dotenv(env)
    assert loaded == {
        "AGENT_PROVIDER": "anthropic",
        "M01_TEST_KEY": "sk-ant-abc#notcomment",
        "M01_TEST_QUOTED": "a # b",
    }
    import os

    assert os.environ["M01_TEST_SET"] == "from-shell"
    for k in loaded:
        monkeypatch.delenv(k)
    assert load_dotenv(tmp_path / "missing.env") == {}
