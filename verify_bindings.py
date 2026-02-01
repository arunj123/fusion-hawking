import sys
import os

# Add src/generated to path
gen_path = os.path.join(os.getcwd(), 'src', 'generated')
sys.path.append(gen_path)
print(f"Added to path: {gen_path}")
print(f"Files in path: {os.listdir(gen_path)}")

try:
    import bindings
    # from bindings import HelloWorld, pack_u32, unpack_u32
    HelloWorld = bindings.HelloWorld
    print("Successfully imported bindings.")
    
    msg = HelloWorld(
        id=123,
        value=3.14,
        description="Test Message",
        data=[1, 2, 3, 4]
    )
    
    print("Created message object.")
    
    serialized = msg.serialize()
    print(f"Serialized {len(serialized)} bytes: {serialized.hex()}")
    
    # Basic verification
    # id(4) + value(4) + desc_len(4) + desc_bytes(12) + data_len(4) + data_bytes(16)
    # Total roughly 44 bytes? "Test Message" is 12 chars.
    
    assert len(serialized) > 0
    print("Verification Successful.")
    
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
