from __future__ import annotations

from pathlib import Path

import pytest

from pm_dashboard.parser import parse_mpp_file


@pytest.mark.skipif(
    not Path("tools/mpp-parser/target/mpp-parser-1.0.0.jar").exists()
    or not Path("2026 Pyrolysis Petal - 24 Mar 2026.mpp").exists(),
    reason="Parser jar or sample MPP file not available",
)
def test_real_mpp_file_parses():
    parsed = parse_mpp_file(Path("2026 Pyrolysis Petal - 24 Mar 2026.mpp"))
    assert parsed.title
    assert parsed.tasks
    assert any(task.finish_date for task in parsed.tasks)
