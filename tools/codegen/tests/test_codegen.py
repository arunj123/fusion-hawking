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
from tools.codegen.models import Service, Struct

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

    def test_rust_generator(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.rust_gen.generate(structs, services)
        self.assertIn("src/generated/mod.rs", output)
        content = output["src/generated/mod.rs"]
        
        self.assertIn("pub struct MyStruct", content)
        self.assertIn("pub trait MyServiceProvider", content)
        self.assertIn("pub struct MyServiceServer", content)
        self.assertIn("pub struct MyServiceClient", content)

    def test_python_generator(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.py_gen.generate(structs, services)
        self.assertIn("src/generated/bindings.py", output)
        content = output["src/generated/bindings.py"]
        
        self.assertIn("class MyStruct:", content)
        self.assertIn("class MyServiceStub:", content)
        self.assertIn("class MyServiceClient:", content)

    def test_cpp_generator(self):
        structs, services = self.parser.parse(self.tmp_file.name)
        output = self.cpp_gen.generate(structs, services)
        self.assertIn("src/generated/bindings.h", output)
        content = output["src/generated/bindings.h"]
        
        self.assertIn("struct MyStruct", content)
        # Check generated types
        self.assertIn("int32_t a;", content) 
        self.assertIn("std::string b;", content)

if __name__ == '__main__':
    unittest.main()
