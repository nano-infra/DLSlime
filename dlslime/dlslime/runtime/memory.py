"""Backend-independent descriptions of actual application buffers."""

from __future__ import annotations

import ctypes
import itertools
from dataclasses import dataclass
from typing import Any, Optional

try:  # Optional until the C++ extension is rebuilt with runtime bindings.
    from dlslime._slime_c import _Memory as _NativeMemory
except Exception:  # pragma: no cover
    _NativeMemory = None


_IDS = itertools.count(1)


def _buffer_address(owner: Any, view: memoryview) -> int:
    data_ptr = getattr(owner, "data_ptr", None)
    if callable(data_ptr):
        return int(data_ptr())
    array_interface = getattr(owner, "__array_interface__", None)
    if array_interface:
        return int(array_interface["data"][0])
    if view.readonly:
        raise TypeError("Memory.from_buffer requires an addressable writable buffer")
    return ctypes.addressof(ctypes.c_char.from_buffer(view))


def _memory_kind(owner: Any) -> str:
    device = getattr(owner, "device", None)
    if device is not None and str(device) != "cpu":
        return (
            "cuda_device"
            if str(getattr(device, "type", device)).startswith("cuda")
            else "device"
        )
    return "host"


@dataclass(frozen=True)
class MemoryView:
    """A checked byte range that retains its parent Memory."""

    memory: "Memory"
    offset: int
    length: int

    def __post_init__(self) -> None:
        native = getattr(self.memory, "_native", None)
        if native is not None:
            native.check_range(self.offset, self.length)

    @property
    def address(self) -> int:
        return self.memory.address + self.offset


class Memory:
    """One actual address range and its application-owned lifetime.

    Backend registrations and remote handles deliberately do not belong here.
    """

    __slots__ = ("_id", "_owner", "_address", "_length", "_kind", "_device", "_native")

    def __init__(
        self,
        owner: Any,
        address: int,
        length: int,
        *,
        memory_kind: Optional[str] = None,
        device: Any = None,
    ) -> None:
        if int(address) < 0 or int(length) <= 0:
            raise ValueError("address must be non-negative and length must be positive")
        self._id = next(_IDS)
        self._owner = owner
        self._address = int(address)
        self._length = int(length)
        self._kind = memory_kind or _memory_kind(owner)
        self._device = device if device is not None else getattr(owner, "device", None)
        self._native = None
        if _NativeMemory is not None:
            try:
                self._native = _NativeMemory(
                    self._address, self._length, owner, self._kind
                )
            except (TypeError, ValueError, RuntimeError):
                # A build without the runtime binding remains source-compatible.
                self._native = None

    @classmethod
    def from_buffer(
        cls,
        buffer: Any,
        *,
        offset: int = 0,
        length: Optional[int] = None,
        memory_kind: Optional[str] = None,
        device: Any = None,
    ) -> "Memory":
        view = memoryview(buffer)
        if view.ndim != 1:
            view = view.cast("B")
        size = view.nbytes
        offset = int(offset)
        if offset < 0 or offset > size:
            raise ValueError("offset is outside the buffer")
        length = size - offset if length is None else int(length)
        if length <= 0 or offset + length > size:
            raise ValueError("length is outside the buffer")
        return cls(
            buffer,
            _buffer_address(buffer, view) + offset,
            length,
            memory_kind=memory_kind,
            device=device,
        )

    @classmethod
    def from_address(
        cls,
        address: int,
        length: int,
        *,
        owner: Any,
        memory_kind: str = "host",
        device: Any = None,
    ) -> "Memory":
        """Create a legacy address-backed Memory with an explicit keepalive owner."""
        if owner is None:
            raise TypeError("from_address requires an explicit owner")
        return cls(
            owner, int(address), int(length), memory_kind=memory_kind, device=device
        )

    @property
    def id(self) -> int:
        return self._id

    @property
    def owner(self) -> Any:
        return self._owner

    @property
    def address(self) -> int:
        return self._address

    @property
    def length(self) -> int:
        return self._length

    @property
    def memory_kind(self) -> str:
        return self._kind

    @property
    def device(self) -> Any:
        return self._device

    def view(self, *, offset: int = 0, length: Optional[int] = None) -> MemoryView:
        offset = int(offset)
        length = self.length - offset if length is None else int(length)
        if offset < 0 or length <= 0 or offset + length > self.length:
            raise ValueError("view is outside the Memory range")
        return MemoryView(self, offset, length)
