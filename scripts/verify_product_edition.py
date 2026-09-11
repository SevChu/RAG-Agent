"""Run existing application regressions against an extracted product source archive.

Use the repository development environment. No package installation or external model calls.
"""

from __future__ import annotations

import argparse
import importlib.abc
import os
import sys
from pathlib import Path


class NoResearch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.evaluation" or fullname.startswith("app.evaluation."):
            raise AssertionError(f"product attempted research import: {fullname}")
        if fullname == "pyarrow" or fullname.startswith("pyarrow."):
            raise ModuleNotFoundError("PyArrow is unavailable in this product verification")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_root", type=Path)
    parser.add_argument("--basetemp", type=Path, required=True)
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parents[1]
    product = args.product_root.resolve()
    if (product / "backend/app/evaluation").exists():
        parser.error("expected product archive without an evaluation directory")
    sys.meta_path.insert(0, NoResearch())
    sys.path.insert(0, str(product / "backend"))
    sys.path.append(str(source_root / "backend"))
    os.environ["AGENTIC_EDITION"] = "product"
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    from app.core.config import Settings

    Settings.model_config["env_file"] = None
    import app.main

    assert Path(app.main.__file__).resolve().is_relative_to(product)
    os.chdir(product / "backend")
    import pytest

    names = (
        "test_health",
        "test_courses_api",
        "test_documents_api",
        "test_conversations_api",
        "test_qa_api",
        "test_agent_deletion",
        "test_agent_integration",
        "test_agent_runtime",
    )
    result = pytest.main(
        [
            "-q",
            "-p",
            "no:cacheprovider",
            "--import-mode=importlib",
            "--basetemp=" + str(args.basetemp.resolve()),
            "-k",
            "not offline_references_never_load_evaluators_at_runtime",
            *(str(source_root / "backend/tests" / (name + ".py")) for name in names),
        ]
    )
    assert not any(
        name == "app.evaluation" or name.startswith("app.evaluation.") for name in sys.modules
    )
    assert "pyarrow" not in sys.modules
    print(
        "Verified: application came from product archive; no evaluation module or PyArrow loaded."
    )
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
