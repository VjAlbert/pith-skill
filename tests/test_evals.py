"""Pytest entry point for PITH eval suite."""
from pathlib import Path
import importlib.util


def test_evals_pass():
    spec = importlib.util.spec_from_file_location(
        "run_evals", Path(__file__).parent / "run_evals.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    result = mod.main()
    assert result == 0, f"Eval suite returned {result} (evals failed — see output above)"
