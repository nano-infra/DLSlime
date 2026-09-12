#include <pybind11/pybind11.h>

#include "memory.h"
namespace py = pybind11;
void bind_memory(py::module_& m)
{
    using dlslime::runtime::Memory;
    using dlslime::runtime::MemoryView;
    py::class_<Memory, std::shared_ptr<Memory>>(m, "_Memory")
        .def(py::init([](uintptr_t address, size_t length, py::object owner, const std::string& kind) {
            if (owner.is_none())
                throw std::invalid_argument("Memory requires an owner");
            auto keepalive = std::shared_ptr<void>(new py::object(std::move(owner)), [](void* p) {
                py::gil_scoped_acquire gil;
                delete static_cast<py::object*>(p);
            });
            return std::make_shared<Memory>(address, length, std::move(keepalive), kind);
        }))
        .def_property_readonly("id", &Memory::id)
        .def_property_readonly("address", &Memory::address)
        .def_property_readonly("length", &Memory::length)
        .def_property_readonly("memory_kind", &Memory::kind)
        .def("check_range", &Memory::check_range);
    py::class_<MemoryView>(m, "_MemoryView")
        .def(py::init<std::shared_ptr<Memory>, size_t, size_t>())
        .def_property_readonly("memory", &MemoryView::memory)
        .def_property_readonly("address", &MemoryView::address)
        .def_property_readonly("offset", &MemoryView::offset)
        .def_property_readonly("length", &MemoryView::length);
}
