# DLSlime 3.0 Runtime API Contract

This document defines the contract that guides the 3.0 refactor. Applications submit logical operations over logical memory and receive one logical Future; they do not select backend handles.

## Boundary

<iframe src="../../assets/runtime-boundary.html" title="DLSlime 3.0 layered communication runtime" style="width:100%;height:820px;border:0;border-radius:14px;background:#f8fafc"></iframe>

PeerAgent owns identity, discovery, desired connections, registration, heartbeat, and stale cleanup. Agent binds application intent to peers, topology, memory, streams, and engines. TransferEngine executes operations within topology and does not own identity.

## Memory contract

`Memory` is the runtime object for one actual address range. It describes an
existing buffer and keeps that buffer alive; it does not represent an RDMA MR,
CUDA IPC handle, socket registration, or any other backend object.

```python
@dataclass(frozen=True)
class Memory:
    id: MemoryId                 # stable while this object is alive
    buffer: BufferReference      # owns or retains the application buffer
    address: int                 # base address of the described range
    length: int
    memory_kind: MemoryKind      # host, cuda_device, cuda_fabric, ...
    device: DeviceId | None

    @classmethod
    def from_buffer(cls, buffer, *, offset=0, length=None) -> "Memory": ...
    def view(self, *, offset=0, length=None) -> "MemoryView": ...
    def bind(self, engine: "Engine") -> "MemoryBinding": ...
```

### Identity and range

`Memory.id` identifies the object and its generation, not an address that can
be reused after release. A `MemoryView` is a checked subrange:

```python
view = memory.view(offset=4096, length=8192)
```

Views do not own storage and cannot outlive their parent Memory. A Memory is
immutable after creation; resizing, replacing the underlying buffer, or moving
the allocation creates a new Memory identity.

### Binding and materialization

`Memory` has no public Context dependency in this phase. An Agent or Engine
creates a `MemoryBinding` through the runtime registry. A Memory is not limited
to one binding: the same actual address range may be materialized by multiple
engines (IPC, NVML/fabric, TCP, or RDMA) at the same time.

```python
binding = registry.bind(memory, engine, register, release=unregister)
rdma_binding = registry.bind(memory, ("rdma", rdma_engine), register_rdma, release=unregister_rdma)
nvlink_binding = registry.bind(memory, ("nvlink", nvlink_engine), register_nvlink, release=unregister_nvlink)
```

A binding records backend permission, validity, and a generation. Each
engine-specific binding records its own materialization state. RDMA may create
an MR, NVLink a mapping or export descriptor, and TCP a bookkeeping record; all
may coexist for the same Memory. These handles are owned by their engines and
are never part of the public Memory API.

### Ownership and lifetime

Memory retains its application buffer. Engines and bindings retain only a
reference to Memory. An in-flight Operation holds strong references to its
Memory, Binding, and materialized resources until its Future is terminal.
Unbinding prevents new submissions and releases backend resources only after
referencing Futures are terminal.

### Current implementation mapping

The current code has the right ingredients but several owners:

| Current object                     | Proposed role                                                        |
| ---------------------------------- | -------------------------------------------------------------------- |
| `LogicalMemoryRegion` in PeerAgent | `Memory` metadata and lifetime                                       |
| `MaterializedMemoryRegion`         | engine-private `MaterializedMemory`                                  |
| RDMA/NVLink/TCP memory pools       | Engine materialization and binding storage                           |
| remote MR pools and name maps      | `RemoteMemoryRef` plus engine-private materialization                |
| `PeerMemoryRegion`                 | a Memory factory for Agent-owned allocations                         |
| `register_memory_region()`         | compatibility wrapper around `Memory.from_buffer()` and publish/bind |

The first migration can introduce Memory without changing transport execution:
PeerAgent creates Memory objects, then passes their address and range to the
existing pools. Subsequent Engine work moves those pool calls behind
the binding/materialization boundary.

The Phase 2 compatibility implementation now follows this rule: every
PeerAgent logical region owns a `Memory` description, while its legacy `ptr`,
`offset`, and `length` fields remain only for existing backend calls. This
allows the control plane and current transports to keep working while the pool
calls move behind the later materialization boundary.

### C++ core and Python facade

The semantic owner of Memory is a language-neutral C++ core. Python objects are facades over reference-counted C++ objects; they must not reimplement address, range, buffer-retention, binding, or release rules.

The proposed C++ layer is independent of RDMA, CUDA, and Python:

```cpp
namespace dlslime::runtime {
class Memory {
public:
    static std::shared_ptr<Memory> from_buffer(Buffer buffer, size_t offset = 0, size_t length = npos);
    MemoryId id() const noexcept;
    uintptr_t address() const noexcept;
    size_t length() const noexcept;
    MemoryView view(size_t offset, size_t length) const;
    MemoryBinding bind(const std::shared_ptr<Engine>& engine);
};
class MemoryBinding {
public:
    MemoryId memory_id() const noexcept;
    BackendId backend_id() const noexcept;
    BindingState state() const noexcept;
};

class EngineBinding {
public:
    MemoryId memory_id() const noexcept;
    EngineId engine_id() const noexcept;
    BindingState state() const noexcept;
};
}  // namespace dlslime::runtime
```

`Buffer` retains the framework-specific owner, such as a Python object or Torch tensor, through an explicit lifetime adapter. A raw `uintptr_t` constructor may exist for legacy callers, but it must require an explicit owner or lifetime token.

The binding and execution relationship is:

```text
C++ Memory -> MemoryBinding -> backend MR / mapping / registration
Python Memory -> pybind holder of C++ Memory
Python Future -> pybind holder of C++ Future
```

Existing `RDMAMemoryPool`, `NVLinkMemoryPool`, `TcpMemoryPool`, and Ascend pools remain backend implementations. They receive a C++ binding and return engine-private materialized objects; they must not become the public Memory type.

Python `Memory.from_buffer()` should call the C++ factory through pybind. The old `PeerAgent.register_memory_region()` remains a compatibility wrapper that creates or looks up a C++ Memory, publishes its identity, and asks the MemoryRegistry for backend bindings. Python, C++, RPC, and future bindings then share one source of truth for Memory lifetime and handle invalidation.

## Core contracts

| Object         | Contract                                                                                     |
| -------------- | -------------------------------------------------------------------------------------------- |
| Agent          | `memory()`, `connect()`, `submit()`, `close()`                                               |
| Topology       | Versioned resources, links, memory visibility, capabilities                                  |
| Memory         | Actual address range, buffer lifetime, identity, views, and multiple engine/backend bindings |
| Operation      | Immutable backend-independent action or plan                                                 |
| Future         | Exactly one terminal state: pending, running, succeeded, failed, cancelled                   |
| Stream         | Ordering and device execution context                                                        |
| TransferEngine | Capabilities, materialization, submission, progress, completion adaptation                   |

Illustrative API:

```python
memory = Memory.from_buffer(kv_tensor)
op = Operation.write(source=local, target=remote, ranges=ranges,
                    dependencies=deps)
future = agent.submit(op, stream=stream)
future.wait()
```

A successful Future means destination visibility under declared Memory and Stream semantics; `wait()` never implies device-wide synchronize. Memory cannot be released while a referencing Future is incomplete. Cancellation is best effort and never changes a committed operation's result.

## TransferEngine SPI

```python
class TransferEngine:
    def capabilities(self, topology): ...
    def materialize(self, memory): ...
    def submit(self, operation, context): ...  # returns ChildFuture
    def progress(self): ...
    def close(self): ...
```

An Agent may expand one Operation into child operations, but exposes one parent Future with child diagnostics. Backend adapters report selected path and capabilities. Adding a backend requires capability declaration, memory materialization, submission, completion adaptation, and conformance tests.

## PeerAgent mapping

| Current surface                   | New contract                           |
| --------------------------------- | -------------------------------------- |
| `connect_to()` / `PeerConnection` | `Agent.connect()`                      |
| `register_memory_region()`        | `Agent.memory()` lifecycle             |
| `read/write/send/recv`            | `Operation` + `Agent.submit()`         |
| endpoint Future classes           | unified Future adapter                 |
| resource caches                   | versioned Topology                     |
| RDMA/NVLink/TCP endpoints         | private TransferEngine implementations |

Existing methods remain compatibility wrappers that construct logical objects and delegate to the runtime path. DLEngine is the first consumer, followed by SlimeRPC and DLSlimeCache.

## Conformance

Every backend and integration must preserve logical Memory across endpoint replacement and fallback, ordering and remote visibility, device synchronization, deterministic shutdown, and one parent Future for all child work. Consumers must not branch on backend implementation types for supported operations.
