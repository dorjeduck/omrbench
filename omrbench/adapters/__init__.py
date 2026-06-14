"""OMR engine adapters. The benchmark core never imports an engine directly;
each engine is wrapped here as a subprocess that maps images -> MusicXML."""

from omrbench.adapters.base import Adapter
from omrbench.adapters.homr import HomrAdapter

REGISTRY: dict[str, type[Adapter]] = {
    "homr": HomrAdapter,
}


def get_adapter(name: str) -> Adapter:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown adapter {name!r}; known adapters: {known}")
    return REGISTRY[name]()
