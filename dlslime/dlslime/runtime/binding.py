"""Backend materialization ownership for first-class Memory objects."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Dict, Hashable, Optional, Tuple

from .memory import Memory


@dataclass
class MemoryBinding:
    memory: Memory
    backend: Hashable
    handle: Any
    metadata: Any = None
    _release: Optional[Callable[[Any], Any]] = None
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        if self._release is not None:
            self._release(self.handle)
        self._closed = True


class MemoryRegistry:
    """Own backend bindings; endpoints/pools never own logical Memory."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._bindings: Dict[Tuple[int, Hashable], MemoryBinding] = {}

    def bind(
        self,
        memory: Memory,
        backend: Hashable,
        register: Callable[[], Any],
        *,
        release=None,
        metadata=None,
    ) -> MemoryBinding:
        key = (memory.id, backend)
        with self._lock:
            existing = self._bindings.get(key)
            if existing is not None and not existing._closed:
                return existing
            binding = MemoryBinding(memory, backend, register(), metadata, release)
            self._bindings[key] = binding
            return binding

    def get(self, memory: Memory, backend: Hashable) -> Optional[MemoryBinding]:
        with self._lock:
            b = self._bindings.get((memory.id, backend))
            return b if b is not None and not b._closed else None

    def release(self, memory: Memory, backend: Hashable) -> bool:
        with self._lock:
            b = self._bindings.pop((memory.id, backend), None)
        if b is None:
            return False
        b.close()
        return True

    def release_memory(self, memory: Memory) -> int:
        with self._lock:
            items = [
                self._bindings.pop(k) for k in list(self._bindings) if k[0] == memory.id
            ]
        for b in items:
            b.close()
        return len(items)

    def snapshot(self) -> Tuple[MemoryBinding, ...]:
        with self._lock:
            return tuple(b for b in self._bindings.values() if not b._closed)
