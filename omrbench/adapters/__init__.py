"""OMR engine adapters. The benchmark core never imports an engine directly;
each engine is wrapped here as a subprocess that maps images -> MusicXML."""

from omrbench.adapters.base import Adapter
from omrbench.adapters.homr import HomrAdapter

#: adapter *type* (the code that drives an engine) -> class. Named engine
#: instances bind to one of these via the ``adapter`` field in omrbench.toml.
REGISTRY: dict[str, type[Adapter]] = {
    "homr": HomrAdapter,
}
