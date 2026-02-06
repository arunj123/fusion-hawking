"""
IDL Demo - Showcases recursive types and synchronous RPC.

This demo generates Python bindings from the MapService IDL and tests
serialization of nested types.
"""
import sys
import os

# Add project paths
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)  # Add root for tools import
sys.path.insert(0, os.path.join(project_root, 'src', 'python'))
sys.path.insert(0, os.path.join(project_root, 'build', 'generated', 'python'))

def run_codegen():
    """Generate bindings from MapService IDL"""
    from tools.codegen.parser import PythonASTParser
    from tools.codegen.generators.python import PythonGenerator
    
    parser = PythonASTParser()
    generator = PythonGenerator()
    
    idl_path = os.path.join(project_root, 'examples', 'map_service.py')
    structs, services = parser.parse(idl_path)
    
    print(f"Parsed {len(structs)} structs and {len(services)} services")
    
    output = generator.generate(structs, services)
    
    # Write generated files
    for path, content in output.items():
        full_path = os.path.join(project_root, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        print(f"Generated: {path}")

def test_serialization():
    """Test serialization of generated types"""
    try:
        from bindings import Point, PointList
    except ImportError:
        print("Running codegen first...")
        run_codegen()
        # Re-import after generation
        import importlib
        import bindings
        importlib.reload(bindings)
        from bindings import Point, PointList
    
    print("\n=== Serialization Test ===")
    
    p1 = Point(x=10, y=20)
    p2 = Point(x=30, y=40)
    
    print(f"Created Point(10, 20) and Point(30, 40)")
    
    # Serialize individual point
    p1_data = p1.serialize()
    print(f"Point serialized to {len(p1_data)} bytes")
    
    # Deserialize
    p1_restored = Point.deserialize(p1_data)
    print(f"Restored: Point({p1_restored.x}, {p1_restored.y})")
    
    # Test nested list
    point_list = PointList(points=[p1, p2])
    list_data = point_list.serialize()
    print(f"\nPointList with 2 points serialized to {len(list_data)} bytes")
    
    restored_list = PointList.deserialize(list_data)
    print(f"Restored PointList with {len(restored_list.points)} points:")
    for i, p in enumerate(restored_list.points):
        print(f"  Point {i}: ({p.x}, {p.y})")
    
    # Verify integrity
    assert p1_restored.x == 10 and p1_restored.y == 20
    assert len(restored_list.points) == 2
    print("\n✓ All serialization tests passed!")

def show_sync_rpc_pattern():
    """Show how sync RPC would work (conceptual)"""
    print("\n=== Synchronous RPC Pattern ===")
    print("""
Generated client code pattern:

    class MapServiceClient:
        def get_path(self, start, end):
            req = MapServiceGetPathRequest(start=start, end=end)
            res = self.runtime.send_request(
                self.SERVICE_ID, 1, req.serialize(), target,
                wait_for_response=True  # <-- This blocks until response!
            )
            if res:
                return MapServiceGetPathResponse.deserialize(res).result
            return None

When wait_for_response=True, the runtime:
1. Generates a session ID for request/response matching
2. Sends the request
3. Blocks until a matching response arrives or timeout
4. Returns the response payload
""")

def main():
    print("=" * 50)
    print("Fusion Hawking IDL Demo")
    print("=" * 50)
    
    os.chdir(project_root)
    
    run_codegen()
    test_serialization()
    show_sync_rpc_pattern()
    
    print("\nDemo complete!")

if __name__ == "__main__":
    main()
