import sys
import os

# Ensure we can import from tools.fusion
# If running as script, add project root to path
if __name__ == "__main__" and __package__ is None:
    # Assuming this file is at tools/fusion/test.py
    # We want to add project root (../..) to sys.path
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, project_root)
    __package__ = "tools.fusion"

from .runner import Tester

if __name__ == "__main__":
    # Allow running this script directly for quick testing
    from .main import main
    main()
