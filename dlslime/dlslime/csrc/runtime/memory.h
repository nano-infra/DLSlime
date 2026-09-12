#pragma once
#include <atomic>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>

namespace dlslime::runtime {
class Memory: public std::enable_shared_from_this<Memory> {
public:
    Memory(uintptr_t address, size_t length, std::shared_ptr<void> owner, std::string kind = "host"):
        id_(next_id_.fetch_add(1)), address_(address), length_(length), owner_(std::move(owner)), kind_(std::move(kind))
    {
        if (!owner_ || !address || !length || length > std::numeric_limits<uintptr_t>::max() - address)
            throw std::invalid_argument("Invalid Memory owner or address range");
    }
    uint64_t id() const noexcept
    {
        return id_;
    }
    uintptr_t address() const noexcept
    {
        return address_;
    }
    size_t length() const noexcept
    {
        return length_;
    }
    const std::string& kind() const noexcept
    {
        return kind_;
    }
    void check_range(size_t offset, size_t length) const
    {
        if (!length || offset > length_ || length > length_ - offset)
            throw std::invalid_argument("view is outside the Memory range");
    }

private:
    inline static std::atomic<uint64_t> next_id_{1};
    uint64_t                            id_;
    uintptr_t                           address_;
    size_t                              length_;
    std::shared_ptr<void>               owner_;
    std::string                         kind_;
};

class MemoryView {
public:
    MemoryView(std::shared_ptr<Memory> memory, size_t offset, size_t length):
        memory_(std::move(memory)), offset_(offset), length_(length)
    {
        if (!memory_)
            throw std::invalid_argument("MemoryView requires a Memory");
        memory_->check_range(offset, length);
    }
    const std::shared_ptr<Memory>& memory() const noexcept
    {
        return memory_;
    }
    uintptr_t address() const noexcept
    {
        return memory_->address() + offset_;
    }
    size_t offset() const noexcept
    {
        return offset_;
    }
    size_t length() const noexcept
    {
        return length_;
    }

private:
    std::shared_ptr<Memory> memory_;
    size_t                  offset_;
    size_t                  length_;
};
}  // namespace dlslime::runtime
