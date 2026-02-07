"""
Diagram Manager Module for Fusion Hawking

Manages PlantUML diagram extraction, rendering, and change detection.
Renders .puml files to PNG images automatically when changes are detected.
"""

import os
import re
import hashlib
import json
import subprocess
import sys
from typing import Dict, List, Tuple, Optional
from pathlib import Path


class DiagramManager:
    """Manages PlantUML diagram lifecycle: extraction, rendering, and tracking."""
    
    PLANTUML_PATTERN = re.compile(
        r'```plantuml\s*\n(.*?)```',
        re.DOTALL
    )
    
    def __init__(self, root_dir: str, reporter=None):
        self.root_dir = Path(root_dir)
        self.docs_dir = self.root_dir / "docs"
        self.diagrams_dir = self.docs_dir / "diagrams"
        self.images_dir = self.docs_dir / "images"
        self.hash_file = self.diagrams_dir / ".diagram_hashes.json"
        self.reporter = reporter
        
        # Ensure directories exist
        self.diagrams_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
    def check_dependencies(self) -> bool:
        """Check and install plantuml package if needed."""
        try:
            import plantuml
            print("  ✅ plantuml package available")
            return True
        except ImportError:
            print("  📦 Installing plantuml package...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "plantuml>=0.3.0", "-q"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print("  ✅ plantuml package installed")
                return True
            except subprocess.CalledProcessError as e:
                print(f"  ❌ Failed to install plantuml: {e}")
                return False
    
    def _get_hash(self, content: str) -> str:
        """Calculate MD5 hash of content."""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _load_hashes(self) -> Dict[str, str]:
        """Load stored diagram hashes."""
        if self.hash_file.exists():
            try:
                with open(self.hash_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_hashes(self, hashes: Dict[str, str]):
        """Save diagram hashes."""
        with open(self.hash_file, 'w') as f:
            json.dump(hashes, f, indent=2)
    
    def extract_diagrams_from_markdown(self) -> List[Tuple[str, str, str]]:
        """
        Extract PlantUML blocks from markdown files.
        Uses section headers to generate meaningful diagram names.
        Returns list of (source_file, diagram_name, content) tuples.
        """
        diagrams = []
        md_files = list(self.docs_dir.glob("*.md")) + list((self.root_dir / "examples").glob("*.md"))
        
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding='utf-8')
            except:
                continue
            
            # Find all PlantUML blocks with their positions
            lines = content.split('\n')
            current_section = "diagram"
            in_plantuml = False
            plantuml_content = []
            diagram_count = {}  # Track duplicates per section
            
            for line in lines:
                # Track section headers (## Header)
                if line.startswith('## '):
                    header_text = line[3:].strip()
                    # Convert to snake_case filename
                    current_section = self._header_to_name(header_text)
                    
                elif line.strip() == '```plantuml':
                    in_plantuml = True
                    plantuml_content = []
                    
                elif line.strip() == '```' and in_plantuml:
                    in_plantuml = False
                    
                    # Generate unique name based on section
                    base_name = current_section
                    if base_name in diagram_count:
                        diagram_count[base_name] += 1
                        name = f"{base_name}_{diagram_count[base_name]}"
                    else:
                        diagram_count[base_name] = 1
                        name = base_name
                    
                    diagrams.append((str(md_file), name, '\n'.join(plantuml_content)))
                    
                elif in_plantuml:
                    plantuml_content.append(line)
        
        return diagrams
    
    def _header_to_name(self, header: str) -> str:
        """Convert a markdown header to a snake_case filename."""
        import re
        # Remove special characters, convert to lowercase
        name = re.sub(r'[^\w\s-]', '', header.lower())
        # Replace spaces/hyphens with underscores
        name = re.sub(r'[\s-]+', '_', name)
        # Remove leading/trailing underscores
        name = name.strip('_')
        # Limit length
        return name[:40] if name else "diagram"
    
    def save_puml_sources(self, diagrams: List[Tuple[str, str, str]]) -> List[str]:
        """
        Save extracted PlantUML to .puml files.
        Returns list of saved file paths.
        """
        saved = []
        for source_file, name, content in diagrams:
            puml_path = self.diagrams_dir / f"{name}.puml"
            
            # Ensure content has @startuml/@enduml
            if not content.strip().startswith('@startuml'):
                content = f"@startuml\n{content}"
            if not content.strip().endswith('@enduml'):
                content = f"{content}\n@enduml"
            
            puml_path.write_text(content, encoding='utf-8')
            saved.append(str(puml_path))
        
        return saved
    
    def get_diagrams_needing_update(self) -> List[Path]:
        """
        Compare current .puml hashes with stored hashes.
        Returns list of .puml files that need re-rendering.
        """
        stored_hashes = self._load_hashes()
        needs_update = []
        
        for puml_file in self.diagrams_dir.glob("*.puml"):
            content = puml_file.read_text(encoding='utf-8')
            current_hash = self._get_hash(content)
            
            png_file = self.images_dir / f"{puml_file.stem}.png"
            stored_hash = stored_hashes.get(puml_file.stem, "")
            
            # Update needed if hash changed or PNG missing
            if current_hash != stored_hash or not png_file.exists():
                needs_update.append(puml_file)
        
        return needs_update
    
    def render_diagrams(self, puml_files: Optional[List[Path]] = None) -> Dict[str, str]:
        """
        Render .puml files to PNG images.
        Uses PlantUML web server (no Java required).
        Returns dict of {diagram_name: status}.
        """
        try:
            import plantuml
        except ImportError:
            return {"error": "plantuml package not installed"}
        
        server = plantuml.PlantUML(url='http://www.plantuml.com/plantuml/png/')
        
        if puml_files is None:
            puml_files = list(self.diagrams_dir.glob("*.puml"))
        
        results = {}
        hashes = self._load_hashes()
        
        for puml_file in puml_files:
            name = puml_file.stem
            png_file = self.images_dir / f"{name}.png"
            
            try:
                content = puml_file.read_text(encoding='utf-8')
                
                # Use plantuml library to render
                success = server.processes_file(str(puml_file), str(png_file))
                
                if success and png_file.exists() and png_file.stat().st_size > 0:
                    results[name] = "PASS"
                    hashes[name] = self._get_hash(content)
                    print(f"    ✅ {name}.png")
                else:
                    results[name] = "FAIL"
                    print(f"    ❌ {name}.png - render failed")
                    
            except Exception as e:
                results[name] = f"FAIL: {str(e)}"
                print(f"    ❌ {name}.png - {e}")
        
        self._save_hashes(hashes)
        return results
    
    def run(self) -> Dict[str, str]:
        """
        Main entry point: render .puml files to PNG.
        Only renders diagrams that have changed (based on hash comparison).
        Source .puml files in docs/diagrams/ are the source of truth.
        """
        print("\n=== Diagrams ===")
        
        # Check dependencies
        if not self.check_dependencies():
            return {"diagrams": "FAIL - missing dependencies"}
        
        # Find existing .puml source files
        puml_files = list(self.diagrams_dir.glob("*.puml"))
        
        if not puml_files:
            print("  ℹ️  No .puml files found in docs/diagrams/")
            return {"diagrams": "SKIP"}
        
        print(f"  📊 Found {len(puml_files)} diagram source files")
        
        # Check what needs updating
        needs_update = self.get_diagrams_needing_update()
        
        if not needs_update:
            print("  ✅ All diagrams up to date")
            return {"diagrams": "PASS"}
        
        print(f"  🔄 Rendering {len(needs_update)} diagram(s)...")
        
        # Render changed diagrams
        results = self.render_diagrams(needs_update)
        
        # Summary
        failed = [k for k, v in results.items() if "FAIL" in str(v)]
        if failed:
            return {"diagrams": f"FAIL ({len(failed)} errors)"}
        
        return {"diagrams": "PASS"}
    
    def get_image_ref(self, diagram_name: str) -> str:
        """Get the markdown image reference for a diagram."""
        return f"![{diagram_name}](images/{diagram_name}.png)"
    
    def get_source_link(self, diagram_name: str) -> str:
        """Get the markdown source link for a diagram."""
        return f"[View Source](diagrams/{diagram_name}.puml)"


def main():
    """CLI entry point for standalone diagram generation."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate PlantUML diagrams")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--force", action="store_true", help="Force re-render all")
    args = parser.parse_args()
    
    manager = DiagramManager(args.root)
    
    if args.force:
        # Clear hashes to force re-render
        if manager.hash_file.exists():
            manager.hash_file.unlink()
    
    results = manager.run()
    print(f"\nResults: {results}")


if __name__ == "__main__":
    main()
