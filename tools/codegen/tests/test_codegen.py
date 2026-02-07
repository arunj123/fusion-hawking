import unittest
import tempfile
import os
import sys

# Ensure tools is in path
sys.path.append(os.path.join(os.getcwd()))

from tools.codegen.parser import PythonASTParser
from tools.codegen.generators.rust import RustGenerator
from tools.codegen.generators.python import PythonGenerator
from tools.codegen.generators.cpp import CppGenerator
from tools.codegen.models import Service, Struct, Type

class TestCodegen(unittest.TestCase):
    def setUp(self):
        self.parser = PythonASTParser()
        self.rust_gen = RustGenerator()
        self.py_gen = PythonGenerator()
        self.cpp_gen = CppGenerator()
        
        # Create a mock file
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
        self.assertEqual(len(structs[0].fields), 2)
        self.assertEqual(structs[0].fields[0].name, "a")
        self.assertEqual(structs[0].fields[0].type.name, "int")
        
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0].name, "MyService")
        self.assertEqual(services[0].id, 0x1234)
        self.assertEqual(len(services[0].methods), 1)
        self.assertEqual(services[0].methods[0].name, "my_method")
        self.assertEqual(services[0].methods[0].id, 1)

    def get_file(self, output, path):
        # Normalize path separators for Windows
        norm_path = os.path.normpath(path)
        # Try finding exact match or normalized match
        if path in output: return output[path]
        if norm_path in output: return output[norm_path]
        # Try matching partials if absolute paths involved (fallback)
        for k in output:
            if os.path.normpath(k).endswith(norm_path):
                return output[k]
        raise KeyError(f"Path '{path}' (norm: '{norm_path}') not found in {list(output.keys())}")

    def test_rust_generator(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.rust_gen.generate(structs, services)
        content = self.get_file(output, "build/generated/rust/mod.rs")
        
        self.assertIn("pub struct MyStruct", content)
        self.assertIn("pub trait MyServiceProvider", content)
        self.assertIn("pub struct MyServiceServer", content)
        self.assertIn("pub struct MyServiceClient", content)

    def test_python_generator(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.py_gen.generate(structs, services)
        content = self.get_file(output, "build/generated/python/bindings.py")
        
        self.assertIn("class MyStruct", content)
        
        runtime_content = self.get_file(output, "build/generated/python/runtime.py")
        self.assertIn("class MyServiceStub", runtime_content)
        self.assertIn("class MyServiceClient", runtime_content)

    def test_cpp_generator(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.cpp_gen.generate(structs, services)
        content = self.get_file(output, "build/generated/cpp/bindings.h")
        
        self.assertIn("struct MyStruct", content)
        # Check generated types
        self.assertIn("int32_t a;", content) 
        self.assertIn("std::string b;", content)


class TestRecursiveTypes(unittest.TestCase):
    """Tests for recursive/nested type handling."""
    
    def setUp(self):
        self.parser = PythonASTParser()
        self.rust_gen = RustGenerator()
        self.py_gen = PythonGenerator()
        self.cpp_gen = CppGenerator()
        
        # Create IDL with recursive types
        self.test_idl = """
import dataclasses
from typing import List

@dataclasses.dataclass
class Point:
    x: int
    y: int

@dataclasses.dataclass
class Path:
    points: List[Point]

@dataclasses.dataclass
class PathCollection:
    paths: List[List[Point]]
"""
        self.tmp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py')
        self.tmp_file.write(self.test_idl)
        self.tmp_file.close()

    def tearDown(self):
        os.unlink(self.tmp_file.name)
        
    def get_file(self, output, path):
        # Normalize path separators for Windows
        norm_path = os.path.normpath(path)
        for k in output:
            if os.path.normpath(k) == norm_path:
                return output[k]
        raise KeyError(f"Path '{path}' not found in {list(output.keys())}")

    def test_parser_nested_list(self):
        structs, _ = self.parser.parse(self.tmp_file.name)
        
        # Find PathCollection struct
        path_collection = next(s for s in structs if s.name == "PathCollection")
        paths_field = path_collection.fields[0]
        
        # Check nested type structure
        self.assertEqual(paths_field.type.name, "list")
        self.assertIsNotNone(paths_field.type.inner)
        self.assertEqual(paths_field.type.inner.name, "list")
        self.assertIsNotNone(paths_field.type.inner.inner)
        self.assertEqual(paths_field.type.inner.inner.name, "Point")

    def test_rust_recursive_type(self):
        structs, _ = self.parser.parse(self.tmp_file.name)
        output = self.rust_gen.generate(structs, [])
        content = self.get_file(output, "build/generated/rust/mod.rs")
        
        self.assertIn("pub struct PathCollection", content)
        self.assertIn("Vec<Vec<Point>>", content)

    def test_python_recursive_type(self):
        structs, _ = self.parser.parse(self.tmp_file.name)
        output = self.py_gen.generate(structs, [])
        content = self.get_file(output, "build/generated/python/bindings.py")
        
        self.assertIn("class PathCollection", content)
        # Check for nested list serialization
        self.assertIn("for _item in", content)

    def test_cpp_recursive_type(self):
        structs, _ = self.parser.parse(self.tmp_file.name)
        output = self.cpp_gen.generate(structs, [])
        content = self.get_file(output, "build/generated/cpp/bindings.h")
        
        self.assertIn("struct PathCollection", content)
        self.assertIn("std::vector<std::vector<Point>>", content)


class TestNewPrimitives(unittest.TestCase):
    """Tests for new primitive type support."""
    
    def setUp(self):
        self.parser = PythonASTParser()
        self.rust_gen = RustGenerator()
        self.py_gen = PythonGenerator()
        self.cpp_gen = CppGenerator()
        
        # Create IDL with various primitives
        self.test_idl = """
import dataclasses

@dataclasses.dataclass
class AllPrimitives:
    a: int
    b: float
    c: bool
    d: str
"""
        self.tmp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py')
        self.tmp_file.write(self.test_idl)
        self.tmp_file.close()

    def tearDown(self):
        os.unlink(self.tmp_file.name)
        
    def get_file(self, output, path):
        # Normalize path separators for Windows
        norm_path = os.path.normpath(path)
        for k in output:
            if os.path.normpath(k) == norm_path:
                return output[k]
        raise KeyError(f"Path '{path}' not found in {list(output.keys())}")

    def test_rust_primitives(self):
        structs, _ = self.parser.parse(self.tmp_file.name)
        output = self.rust_gen.generate(structs, [])
        content = self.get_file(output, "build/generated/rust/mod.rs")
        
        self.assertIn("i32", content)  # int
        self.assertIn("f32", content)  # float
        self.assertIn("bool", content)  # bool
        self.assertIn("String", content)  # str

    def test_cpp_primitives(self):
        structs, _ = self.parser.parse(self.tmp_file.name)
        output = self.cpp_gen.generate(structs, [])
        content = self.get_file(output, "build/generated/cpp/bindings.h")
        
        self.assertIn("int32_t", content)  # int
        self.assertIn("float", content)  # float
        self.assertIn("bool", content)  # bool
        self.assertIn("std::string", content)  # str


class TestSyncRpcGeneration(unittest.TestCase):
    """Tests for synchronous RPC stub generation."""
    
    def setUp(self):
        self.parser = PythonASTParser()
        self.rust_gen = RustGenerator()
        self.py_gen = PythonGenerator()
        
        # Create IDL with methods having return types
        self.test_idl = """
def service(id):
    def inner(cls): return cls
    return inner

def method(id):
    def inner(func): return func
    return inner

class Result:
    value: int

@service(id=0x5678)
class MathService:
    @method(id=1)
    def add(self, a: int, b: int) -> int:
        pass
    
    @method(id=2)
    def fire_and_forget(self, msg: str):
        pass
"""
        self.tmp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py')
        self.tmp_file.write(self.test_idl)
        self.tmp_file.close()

    def tearDown(self):
        os.unlink(self.tmp_file.name)
        
    def get_file(self, output, path):
        # Normalize path separators for Windows
        norm_path = os.path.normpath(path)
        for k in output:
            if os.path.normpath(k) == norm_path:
                return output[k]
        raise KeyError(f"Path '{path}' not found in {list(output.keys())}")

    def test_python_sync_rpc(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.py_gen.generate(structs, services)
        runtime_content = self.get_file(output, "build/generated/python/runtime.py")
        
        # Check that sync RPC uses wait_for_response=True
        self.assertIn("wait_for_response=True", runtime_content)
        # Check that fire-and-forget uses wait_for_response=False
        self.assertIn("wait_for_response=False", runtime_content)

    def test_rust_async_rpc(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.rust_gen.generate(structs, services)
        content = self.get_file(output, "build/generated/rust/mod.rs")
        
        # Check that client methods exist and have correct signatures
        self.assertIn("pub fn add", content)
        self.assertIn("pub fn fire_and_forget", content)
        # Check that methods with return types indicate sync RPC is not yet implemented
        self.assertIn("Sync RPC not yet implemented", content)


if __name__ == '__main__':
    unittest.main()
