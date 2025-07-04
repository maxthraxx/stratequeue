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

# ---------------------------------------------------------------------------
# When running *integration* CLI tests we spawn a separate Python process.
# That fresh interpreter does **not** inherit the monkey-patched broker stubs
# installed by the parent test session, which causes output mismatches between
# the in-process `InfoFormatter` calls and the CLI subprocess.
#
# Setting the environment variable  SQ_TEST_STUB_BROKERS=1  tells this
# sitecustomize module to import the lightweight stub implementations located
# under  tests/unit_tests/brokers/*_stubs.py.  Importing these modules has the
# side-effect of registering the fake classes in ``sys.modules`` so subsequent
# ``import StrateQueue.brokers.Alpaca.alpaca_broker`` / IBKR lookups resolve to
# the stubs rather than the real heavy SDKs.
# ---------------------------------------------------------------------------

if os.getenv("SQ_TEST_STUB_BROKERS") == "1":
    try:
        # The stubs live inside the test suite – ensure its parent directory is
        # on sys.path so the import below succeeds even when invoked from an
        # installed wheel / different CWD.
        import sys, pathlib, importlib

        project_root = pathlib.Path(__file__).resolve().parent
        # Move two levels up to the repository root and append "tests".
        tests_dir = (project_root / "tests").resolve()
        if tests_dir.exists() and str(tests_dir) not in sys.path:
            sys.path.insert(0, str(tests_dir))

        # Import the stub modules – they self-register into sys.modules.
        importlib.import_module("unit_tests.brokers.alpaca.alpaca_stubs")
        importlib.import_module("unit_tests.brokers.ibkr.ibkr_stubs")
    except Exception as _e:  # pragma: no cover – stub load failure should not crash
        # Silently continue; the real modules may still be available so the CLI
        # can work, and tests will surface any inconsistencies.
        pass 