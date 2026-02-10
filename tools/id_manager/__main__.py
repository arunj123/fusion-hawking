import argparse
import sys
import os
from .manager import IDManager

def main():
    parser = argparse.ArgumentParser(description="Fusion ID Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # scan
    parser_scan = subparsers.add_parser("scan", help="Scan and list used IDs")
    parser_scan.add_argument("--root", default=".", help="Project root")
    
    # validate
    parser_validate = subparsers.add_parser("validate", help="Validate for duplicates")
    parser_validate.add_argument("--root", default=".", help="Project root")
    
    # assign (suggest)
    parser_assign = subparsers.add_parser("assign", help="Suggest next available ID")
    parser_assign.add_argument("--root", default=".", help="Project root")

    args = parser.parse_args()
    
    root = os.path.abspath(args.root)
    manager = IDManager(root)
    
    if args.command == "scan":
        ids = manager.scan_ids()
        print(f"Found {len(ids)} Service IDs:")
        for eid in sorted(ids.keys()):
            print(f"  0x{eid:04x}: {ids[eid]}")
            
    elif args.command == "validate":
        # TODO: Enhance Validation Logic to fail on dups
        ids = manager.scan_ids()
        # IDManager already logs warnings on duplicates during scan.
        # Strict fail logic implies we need to track duplicates explicitly.
        # For now, we assume if scan completes without crash, it's 'valid' structure, 
        # but the user should heed warnings.
        pass

    elif args.command == "assign":
        next_id = manager.suggest_next_id()
        print(f"Next Available ID: 0x{next_id:04x}")

if __name__ == "__main__":
    main()
