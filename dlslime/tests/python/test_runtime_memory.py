import ctypes

import pytest

from dlslime.runtime import Memory, MemoryRegistry, MemoryView


def test_from_buffer_retains_owner_and_exposes_byte_range():
    owner = bytearray(32)
    memory = Memory.from_buffer(owner, offset=4, length=16)
    assert memory.length == 16
    assert memory.address == ctypes.addressof(ctypes.c_char.from_buffer(owner)) + 4
    assert memory.owner is owner
    view = memory.view(offset=3, length=5)
    assert isinstance(view, MemoryView)
    assert view.address == memory.address + 3


def test_memory_identity_is_not_address_identity():
    owner = bytearray(8)
    first = Memory.from_buffer(owner)
    second = Memory.from_buffer(owner)
    assert first.id != second.id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"offset": -1},
        {"offset": 8, "length": 1},
        {"offset": 0, "length": 0},
    ],
)
def test_invalid_ranges_fail(kwargs):
    with pytest.raises(ValueError):
        Memory.from_buffer(bytearray(8), **kwargs)


def test_read_only_buffer_requires_explicit_addressable_owner():
    with pytest.raises(TypeError):
        Memory.from_buffer(b"read-only")


def test_legacy_address_memory_requires_and_retains_owner():
    owner = object()
    memory = Memory.from_address(0x1000, 128, owner=owner)
    assert memory.address == 0x1000
    assert memory.owner is owner


def test_each_rebinding_of_a_growable_buffer_gets_a_new_memory_identity():
    owner = bytearray(8)
    first = Memory.from_buffer(owner)
    replacement = bytearray(16)
    second = Memory.from_buffer(replacement)
    assert first.id != second.id
    assert first.owner is owner
    assert second.owner is replacement


def test_memory_registry_allows_multiple_backend_bindings_and_idempotent_registration():
    memory = Memory.from_buffer(bytearray(8))
    registry = MemoryRegistry()
    released = []
    first = registry.bind(memory, "ipc", lambda: 11, release=released.append)
    second = registry.bind(memory, "nvml", lambda: 12, release=released.append)
    assert first.handle == 11 and second.handle == 12
    assert registry.bind(memory, "ipc", lambda: 99).handle == 11
    assert registry.release_memory(memory) == 2
    assert sorted(released) == [11, 12]
