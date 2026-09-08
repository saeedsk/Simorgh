"""Pin the terminal width for Interface tests.

Rendering follows the real terminal (`render.terminal_width`), which is
right for the product and wrong for a test suite: six of these tests
assumed the default width and failed in a 60-column window, and one
failed in a 200-column one. A suite whose result depends on the size of the window
it was launched from is not a suite.

So the default here is a fixed 80. A test that is *about* width
overrides it explicitly -- `test_line_widths.py` patches
`shutil.get_terminal_size` per case, and that patch wins over this one
because it is applied later and closer.
"""

from __future__ import annotations

import os
import shutil

import pytest

# 100, not 80: that is `render.terminal_width`'s own default, and so
# the width these tests were really running at all along -- under
# pytest `shutil.get_terminal_size` finds no terminal and returns
# the fallback the caller passes, which is `(default, 24)`.
FIXED_COLUMNS = 100


@pytest.fixture(autouse=True)
def _fixed_terminal_width(monkeypatch):
    monkeypatch.setenv("COLUMNS", str(FIXED_COLUMNS))
    monkeypatch.setattr(
        shutil, "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((FIXED_COLUMNS, 24)),
    )
    yield
