import os
import ast
import logging
from typing import Dict, List, Optional, Set

# Configure logging
logging.basicConfig(level=logging.INFO, format="[ID Manager] %(message)s")
logger = logging.getLogger("IDManager")

class IDManager:
    """
    Manages Service IDs by scanning Python IDL files.
    """
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.used_ids: Dict[int, str] = {} # ID -> Filename/Context

    def scan_ids(self) -> Dict[int, str]:
        """
        Scans for SERVICE_ID constants in python files.
        Returns a dict of {id: filepath}.
        """
        self.used_ids.clear()
        
        # Walk through relevant directories
        search_dirs = [
            os.path.join(self.project_root, "examples"),
            os.path.join(self.project_root, "src"),
        ]
        
        for search_dir in search_dirs:
            if not os.path.exists(search_dir): continue
            
            for root, _, files in os.walk(search_dir):
                for file in files:
                    if file.endswith(".py"):
                        filepath = os.path.join(root, file)
                        self._parse_file(filepath)
                        
        return self.used_ids

    def _parse_file(self, filepath: str):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)
                
            for node in ast.walk(tree):
                # Look for assignments: SERVICE_ID = 0x1234
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            # print(f"DEBUG: Found assignment to {target.id} in {filepath}")
                            if target.id == "SERVICE_ID":
                                self._extract_id(node.value, filepath, "SERVICE_ID")
                            elif target.id.endswith("_SERVICE_ID"): # Handle SOMEIPY_SERVICE_ID
                                self._extract_id(node.value, filepath, target.id)
                        
                # Look for class definitions with SERVICE_ID
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id == "SERVICE_ID":
                                    self._extract_id(item.value, filepath, f"{node.name}.SERVICE_ID")

        except Exception as e:
            logger.debug(f"Skipping {filepath}: {e}")

    def _extract_id(self, value_node, filepath, context):
        try:
            # Handle straightforward integers across Python versions
            if isinstance(value_node, ast.Constant): # Python 3.8+
                 if isinstance(value_node.value, int):
                     self._register_id(value_node.value, filepath, context)
            elif isinstance(value_node, ast.Num): # Python < 3.8
                 if isinstance(value_node.n, int):
                     self._register_id(value_node.n, filepath, context)
        except Exception:
            pass

    def _register_id(self, id_val: int, filepath: str, context: str):
        if id_val in self.used_ids:
            existing = self.used_ids[id_val]
            # Don't flag if it's the exact same file (re-scanning)
            if existing != f"{filepath} ({context})":
                logger.warning(f"Duplicate ID 0x{id_val:04x} found in {filepath} ({context}). Previously seen in {existing}")
        self.used_ids[id_val] = f"{filepath} ({context})"

    def validate(self) -> bool:
        """
        Returns True if no duplicates found (logic to be enhanced).
        Currently _register_id logs warnings.
        """
        # Re-scan to populate
        self.scan_ids()
        # For strict validation, we would track duplicates explicitly.
        # This implementation assumes the user checks the logs for now.
        return True

    def suggest_next_id(self) -> int:
        self.scan_ids()
        if not self.used_ids:
            return 0x1000
        return max(self.used_ids.keys()) + 1

if __name__ == "__main__":
    import sys
    root = os.getcwd()
    if len(sys.argv) > 1:
        root = sys.argv[1]
    
    manager = IDManager(root)
    print(f"Scanning {root}...")
    ids = manager.scan_ids()
    
    print("\nUsed IDs:")
    for eid in sorted(ids.keys()):
        print(f"  0x{eid:04x}: {ids[eid]}")
        
    print(f"\nNext Available ID: 0x{manager.suggest_next_id():04x}")
