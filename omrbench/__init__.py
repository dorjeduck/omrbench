"""omrbench — a tool-independent ground-truth benchmark for OMR.

The core (corpus discovery + scoring) imports no OMR engine. Engines plug in
through thin subprocess adapters under :mod:`omrbench.adapters`.
"""

__version__ = "0.0.1"
