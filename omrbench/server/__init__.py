"""Local web UI for browsing benchmark results — opt-in `.[serve]` extra.

The server is a thin shell: it imports the engine-free read layer
(`omrbench.records`), `omrbench.corpus`, and `omrbench.score`, and exposes them
over HTTP. It holds no benchmark logic and imports no OMR engine — the same
discipline the rest of the core follows.
"""
