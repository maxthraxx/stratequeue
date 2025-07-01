"""Stub placeholder for the heavy *backtrader* package.

The real Backtrader library is not required for StrateQueue's unit-test suite
and drastically slows down import time.  This stub simply triggers an
ImportError so that optional Backtrader-based components gracefully degrade or
mark themselves as unavailable.
"""

raise ImportError("backtrader not available in lightweight test environment") 