import os
import re
import json
import logging

logger = logging.getLogger("fusion.docs_updater")

class DocsUpdater:
    """Updates documentation files with test results."""
    
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.state_file = os.path.join(root_dir, "build", "run_state.json")
        self.test_matrix_path = os.path.join(root_dir, "docs", "test_matrix.md")

    def _get_state(self):
        if not os.path.exists(self.state_file):
            return {}
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
            return {}

    def update_test_matrix(self):
        """Updates the verification checklist in test_matrix.md."""
        if not os.path.exists(self.test_matrix_path):
            logger.warning(f"test_matrix.md not found at {self.test_matrix_path}")
            return False

        state = self._get_state()
        
        # Mapping: {Checklist Label Fragment: State Key}
        mapping = {
            "All unit tests pass": "test:all",
            "Cross-language RPC verified": ["demos:someipy", "demos:integrated", "demos:all"],
            "Service Discovery works": ["demos:simple", "demos:all"],
            "Events delivered to all subscribers": ["demos:pubsub", "demos:all"],
            "Coverage reports generated": "coverage:all"
        }

        with open(self.test_matrix_path, "r", encoding='utf-8') as f:
            content = f.read()

        updated_content = content
        for label, keys in mapping.items():
            # If keys is a list, any PASS is enough. If single string, that one must PASS.
            if isinstance(keys, str):
                passed = state.get(keys) == "PASS"
            else:
                passed = any(state.get(k) == "PASS" for k in keys)

            # Regex to find the checklist item and update it
            # - [ ] Label -> - [x] Label (if passed)
            # - [x] Label -> - [ ] Label (if failed)
            mark = "x" if passed else " "
            
            # Escape label for regex
            pattern = rf"- \[[ x]\] ({re.escape(label)}.*)"
            replacement = rf"- [{mark}] \1"
            
            if re.search(pattern, updated_content):
                updated_content = re.sub(pattern, replacement, updated_content)
                logger.info(f"Updated checklist item '{label}' to [{mark}]")

        if updated_content != content:
            with open(self.test_matrix_path, "w", encoding='utf-8') as f:
                f.write(updated_content)
            print(f"[docs] Updated {os.path.relpath(self.test_matrix_path, self.root_dir)} with latest results.")
            return True
        
        return False

def update_docs(root_dir):
    updater = DocsUpdater(root_dir)
    updater.update_test_matrix()
