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
