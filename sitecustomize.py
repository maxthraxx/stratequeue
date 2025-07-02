"""Runtime tweaks executed automatically on Python start-up.

This *sitecustomize* module is discovered automatically by the CPython
import machinery (see :pep:`370`).  We use it to ensure that integration tests
requiring access to *real* broker environments (IBKR / Alpaca) are skipped when
running the offline unit-test suite.
"""

import os

# ---------------------------------------------------------------------------
# Force the IBKR integration tests into their *skip* path: they only execute if
#   (IBKR_ENV == "live") **or** (IBKR_PORT == 7497).
# The offline CI environment obviously does not connect to a real gateway, so
# we point the port to a non-standard value which makes the test module skip at
# collection time.
# ---------------------------------------------------------------------------
os.environ.setdefault("IBKR_PORT", "4000")  # any port ≠ 7497 works for skip

# Alpaca live tests additionally require env-provided API keys, so they are
# already skipped by default – no change needed here. 