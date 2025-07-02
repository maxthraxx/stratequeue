"""Lightweight stub for the *vectorbt* library used in tests.

This stub is ONLY intended for the test environment where the real *vectorbt*
package (and its compiled dependencies) may not be available or compatible with
the installed NumPy version.  It provides just enough surface so that the
`StrateQueue.engines.vectorbt_engine` module can import it without triggering
import errors.

Do **NOT** rely on this module for production usage – it implements *none* of
vectorbt's actual functionality.
"""

from types import SimpleNamespace

# Common namespaces accessed by third-party code ---------------------------
# We expose the attributes as empty SimpleNamespace instances so that attribute
# look-ups via dot notation do not fail.

generic = SimpleNamespace(nb=SimpleNamespace(), plotting=SimpleNamespace())

# Marker to signal that this is a dummy impl – helps with debugging.
__vectorbt_stub__ = True

# Optionally expose a minimal API for "vectorbt.__version__" checks.
__version__ = "0.0.0-stub"

# Immediately raise ImportError so that caller modules can fall back to
# dependency-absent code paths (tests will skip VectorBT engine).  The stub
# definitions above ensure AttributeError chains remain intact if some code
# happens to inspect the partially-imported module, but normal importers will
# treat the dependency as unavailable.
raise ImportError("vectorbt not available in test environment – using stub placeholder") 