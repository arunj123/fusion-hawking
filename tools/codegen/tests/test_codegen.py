import unittest
import tempfile
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.getcwd())

from tools.codegen.generators.rust import RustGenerator
from tools.codegen.generators.python import PythonGenerator
from tools.codegen.generators.cpp import CppGenerator
from tools.codegen.models import Service, Struct, Type, Field, Method


def _make_simple_service():
    """Build a minimal Service model for testing generators directly."""
    int_type = Type("int", None)
    str_type = Type("str", None)
    my_struct = Struct("MyStruct", [Field("a", int_type), Field("b", str_type)])
    method = Method("my_method", 1, [Field("val", int_type)], int_type)
    svc = Service(name="MyService", id=0x1234, methods=[method], events=[], fields=[], major_version=1, minor_version=0)
    return [my_struct], [svc]


def _make_recursive_types():
    """Build nested list type models."""
    int_type = Type("int", None)
    point_type = Type("Point", None)
    list_point = Type("list", point_type)
    list_list_point = Type("list", list_point)

    point = Struct("Point", [Field("x", int_type), Field("y", int_type)])
    path = Struct("Path", [Field("points", list_point)])
    path_collection = Struct("PathCollection", [Field("paths", list_list_point)])
    return [point, path, path_collection], []


def _make_all_primitives():
    """Build a struct with all primitive types."""
    fields = [
        Field("a", Type("int", None)),
        Field("b", Type("float", None)),
        Field("c", Type("bool", None)),
        Field("d", Type("str", None)),
    ]
    return [Struct("AllPrimitives", fields)], []


def _make_rpc_service():
    """Build a service with sync RPC and fire-and-forget methods."""
    int_type = Type("int", None)
    str_type = Type("str", None)
    none_type = Type("None", None)
    add_method = Method("add", 1, [Field("a", int_type), Field("b", int_type)], int_type)
    faf_method = Method("fire_and_forget", 2, [Field("msg", str_type)], none_type)
    svc = Service(name="MathService", id=0x5678, methods=[add_method, faf_method], events=[], fields=[], major_version=1, minor_version=0)
    return [], [svc]


class TestGenerators(unittest.TestCase):
    """Tests for code generators using model objects directly (no parser dependency)."""

    def setUp(self):
        self.rust_gen = RustGenerator()
        self.py_gen = PythonGenerator()
        self.cpp_gen = CppGenerator()

    def get_file(self, output, path_suffix):
        """Find a file in the output dict by suffix match."""
        norm_suffix = os.path.normpath(path_suffix)
        for k in output:
            if os.path.normpath(k).endswith(norm_suffix):
                return output[k]
        raise KeyError(f"Path suffix '{path_suffix}' not found in {list(output.keys())}")

    # --- Rust Generator ---

    def test_rust_generator_basic(self):
        structs, services = _make_simple_service()
        output = self.rust_gen.generate(structs, services)
        # New generator produces per-service files + mod.rs
        mod_content = self.get_file(output, "rust/mod.rs")
        self.assertIn("pub mod", mod_content)
        # Check types file
        types_content = self.get_file(output, "rust/types.rs")
        self.assertIn("pub struct MyStruct", types_content)
        # Check service file
        svc_content = self.get_file(output, "rust/my_service.rs")
        self.assertIn("pub trait MyServiceProvider", svc_content)
        self.assertIn("pub struct MyServiceServer", svc_content)
        self.assertIn("pub struct MyServiceClient", svc_content)

    def test_rust_recursive_type(self):
        structs, services = _make_recursive_types()
        output = self.rust_gen.generate(structs, services)
        types_content = self.get_file(output, "rust/types.rs")
        self.assertIn("pub struct PathCollection", types_content)
        self.assertIn("Vec<Vec<Point>>", types_content)

    def test_rust_primitives(self):
        structs, services = _make_all_primitives()
        output = self.rust_gen.generate(structs, services)
        types_content = self.get_file(output, "rust/types.rs")
        self.assertIn("i32", types_content)   # int
        self.assertIn("f32", types_content)   # float
        self.assertIn("bool", types_content)  # bool
        self.assertIn("String", types_content)  # str

    def test_rust_rpc_methods(self):
        structs, services = _make_rpc_service()
        output = self.rust_gen.generate(structs, services)
        svc_content = self.get_file(output, "rust/math_service.rs")
        self.assertIn("pub fn add", svc_content)
        self.assertIn("pub fn fire_and_forget", svc_content)

    # --- Python Generator ---

    def test_python_generator_basic(self):
        structs, services = _make_simple_service()
        output = self.py_gen.generate(structs, services)
        bindings = self.get_file(output, "python/bindings.py")
        self.assertIn("class MyStruct", bindings)
        runtime = self.get_file(output, "python/runtime.py")
        self.assertIn("class MyServiceStub", runtime)
        self.assertIn("class MyServiceClient", runtime)

    def test_python_recursive_type(self):
        structs, services = _make_recursive_types()
        output = self.py_gen.generate(structs, services)
        content = self.get_file(output, "python/bindings.py")
        self.assertIn("class PathCollection", content)
        self.assertIn("for _item in", content)

    def test_python_sync_rpc(self):
        structs, services = _make_rpc_service()
        output = self.py_gen.generate(structs, services)
        runtime = self.get_file(output, "python/runtime.py")
        self.assertIn("wait_for_response=True", runtime)
        self.assertIn("wait_for_response=False", runtime)

    # --- C++ Generator ---

    def test_cpp_generator_basic(self):
        structs, services = _make_simple_service()
        output = self.cpp_gen.generate(structs, services)
        # New generator produces per-service headers + types.h + bindings.h
        types_content = self.get_file(output, "cpp/types.h")
        self.assertIn("struct MyStruct", types_content)
        self.assertIn("int32_t a;", types_content)
        self.assertIn("std::string b;", types_content)

    def test_cpp_recursive_type(self):
        structs, services = _make_recursive_types()
        output = self.cpp_gen.generate(structs, services)
        types_content = self.get_file(output, "cpp/types.h")
        self.assertIn("struct PathCollection", types_content)
        self.assertIn("std::vector<std::vector<Point>>", types_content)

    def test_cpp_primitives(self):
        structs, services = _make_all_primitives()
        output = self.cpp_gen.generate(structs, services)
        types_content = self.get_file(output, "cpp/types.h")
        self.assertIn("int32_t", types_content)
        self.assertIn("float", types_content)
        self.assertIn("bool", types_content)
        self.assertIn("std::string", types_content)


# Keep a legacy test for the AST parser if it still exists
try:
    from tools.codegen.parser import PythonASTParser

    class TestASTParser(unittest.TestCase):
        """Tests for the legacy AST parser (kept for backward compat)."""

        def setUp(self):
            self.parser = PythonASTParser()
            self.test_idl = """
import dataclasses
from typing import List

@dataclasses.dataclass
class MyStruct:
    a: int
    b: str

def service(id):
    def inner(cls): return cls
    return inner

def method(id):
    def inner(func): return func
    return inner

@service(id=0x1234)
class MyService:
    @method(id=1)
    def my_method(self, val: int) -> int:
        pass
"""
            self.tmp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py')
            self.tmp_file.write(self.test_idl)
            self.tmp_file.close()

        def tearDown(self):
            os.unlink(self.tmp_file.name)

        def test_parser(self):
            structs, services = self.parser.parse(self.tmp_file.name)
            self.assertEqual(len(structs), 1)
            self.assertEqual(structs[0].name, "MyStruct")
            self.assertEqual(len(services), 1)
            self.assertEqual(services[0].name, "MyService")
            self.assertEqual(services[0].id, 0x1234)

except ImportError:
    pass  # AST parser removed — that's fine


if __name__ == '__main__':
    unittest.main()
