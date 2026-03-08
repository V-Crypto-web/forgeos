import os
import ast
import json
import hashlib
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Tuple

class SymbolVisitor(ast.NodeVisitor):
    def __init__(self):
        self.classes = []
        self.functions = []
        self.imports = []
        
    def visit_ClassDef(self, node):
        self.classes.append({'name': node.name, 'lineno': getattr(node, 'lineno', 1), 'end_lineno': getattr(node, 'end_lineno', getattr(node, 'lineno', 1))})
        self.generic_visit(node)
        
    def visit_FunctionDef(self, node):
        self.functions.append({'name': node.name, 'lineno': getattr(node, 'lineno', 1), 'end_lineno': getattr(node, 'end_lineno', getattr(node, 'lineno', 1))})
        self.generic_visit(node)
        
    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

class RepoAnalyzer:
    """
    Analyzes a repository to extract module structure, dependencies, and build a Repo Map.
    For MVP, we focus on parsing Python files via AST to find imports, functions, and classes.
    """
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        
    def get_all_python_files(self) -> List[str]:
        py_files = []
        for root, _, files in os.walk(self.repo_path):
            if ".git" in root or "venv" in root or "__pycache__" in root:
                continue
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))
        return py_files

    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """Analyzes a single Python file using AST to extract symbols."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content)
        except Exception as e:
            return {"error": str(e)}

        analyzer = SymbolVisitor()
        analyzer.visit(tree)
        
        # Extract source code snippets
        lines = content.split('\n')
        rich_classes = []
        rich_functions = []
        
        for cls in analyzer.classes:
            start_idx = max(0, cls['lineno'] - 1)
            end_idx = min(len(lines), cls['end_lineno'])
            snippet = '\n'.join(lines[start_idx:end_idx])
            rich_classes.append({'name': cls['name'], 'snippet': snippet})
            
        for func in analyzer.functions:
            start_idx = max(0, func['lineno'] - 1)
            end_idx = min(len(lines), func['end_lineno'])
            snippet = '\n'.join(lines[start_idx:end_idx])
            rich_functions.append({'name': func['name'], 'snippet': snippet})
        
        return {
            "classes": rich_classes,
            "functions": rich_functions,
            "imports": analyzer.imports
        }

    def get_git_info(self) -> Tuple[str, str]:
        branch = "unknown_branch"
        commit = "unknown_commit"
        try:
            branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.repo_path, text=True, stderr=subprocess.DEVNULL).strip()
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo_path, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            pass
        return branch, commit

    def get_file_hash(self, filepath: str) -> str:
        hasher = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                buf = f.read()
                hasher.update(buf)
            return hasher.hexdigest()
        except Exception:
            return ""

    def generate_repo_map(self) -> Dict[str, Dict[str, Any]]:
        """Generates a complete AST map of the repository with commit and hash-based caching."""
        branch, commit = self.get_git_info()
        
        # We use a cache directory structure: .forgeos/cache/{branch}/{commit}
        # to ensure strong branch/commit isolation
        cache_dir = os.path.join(self.repo_path, ".forgeos", "cache", branch, commit)
        manifest_file = os.path.join(cache_dir, "cache_manifest.json")
        repo_map_file = os.path.join(cache_dir, "repo_map.json")
        
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            pass
            
        manifest = {
            "branch": branch,
            "commit_hash": commit,
            "file_hashes": {}
        }
        
        repo_map = {}
        
        # Load existing cache if available
        if os.path.exists(manifest_file) and os.path.exists(repo_map_file):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                with open(repo_map_file, "r", encoding="utf-8") as f:
                    repo_map = json.load(f)
            except Exception:
                manifest = {
                    "branch": branch,
                    "commit_hash": commit,
                    "file_hashes": {}
                }
                repo_map = {}
                
        files = self.get_all_python_files()
        cache_updated = False
        
        # Track valid rel_paths to remove deleted files from cache
        valid_rel_paths = set()
        updated_modules = set() # Track modified files to invalidate dependents
        
        for file in files:
            rel_path = os.path.relpath(file, self.repo_path)
            valid_rel_paths.add(rel_path)
            current_hash = self.get_file_hash(file)
            
            # Check if file changed or is missing from repo map
            if rel_path in manifest["file_hashes"] and manifest["file_hashes"][rel_path] == current_hash and rel_path in repo_map:
                # True Cache Hit - file hasn't changed
                pass
            else:
                # Cache miss or file changed - analyze file
                data = self.analyze_file(file)
                repo_map[rel_path] = data
                manifest["file_hashes"][rel_path] = current_hash
                cache_updated = True
                module_name = rel_path.replace(".py", "").replace("/", ".")
                updated_modules.add(module_name)
                
        # Dependency-Aware Invalidation: 
        # If A imports B, and B was updated, we should re-analyze A (this assumes we do deeper analysis later, MVP just tracks it)
        if cache_updated and updated_modules and os.path.exists(os.path.join(cache_dir, "import_graph.json")):
            try:
                with open(os.path.join(cache_dir, "import_graph.json"), "r") as f:
                    old_import_graph = json.load(f)
                    
                for rel_path, data in repo_map.items():
                    if rel_path not in valid_rel_paths: continue
                    # Re-analyze if it imports an updated module, and we haven't already just analyzed it
                    module_name = rel_path.replace(".py", "").replace("/", ".")
                    if module_name not in updated_modules:
                        imports = old_import_graph.get(rel_path, [])
                        if any(imp in updated_modules for imp in imports):
                            data = self.analyze_file(os.path.join(self.repo_path, rel_path))
                            repo_map[rel_path] = data
            except Exception:
                pass

        # Remove deleted files from manifest and repo_map
        deleted_files = set(manifest["file_hashes"].keys()) - valid_rel_paths
        for deleted_file in deleted_files:
            if deleted_file in manifest["file_hashes"]:
                del manifest["file_hashes"][deleted_file]
            if deleted_file in repo_map:
                del repo_map[deleted_file]
            cache_updated = True
            
        if cache_updated or not os.path.exists(manifest_file):
            self._save_cache_artifacts(cache_dir, manifest, repo_map)
            
        return repo_map

    def _save_cache_artifacts(self, cache_dir: str, manifest: dict, repo_map: dict):
        try:
            # Generate derivative artifacts for targeted test selection and prompt compression
            symbol_index = {"files": {}}
            symbol_definitions = {"files": {}}
            import_graph = {}
            test_map = {}
            
            # Pre-calculate test files for the heuristic test map
            test_files = [f for f in repo_map.keys() if f.startswith("test_") or f.endswith("_test.py") or "/test_" in f or "/tests/" in f]
            impl_files = [f for f in repo_map.keys() if f not in test_files]
            
            for filepath, data in repo_map.items():
                if "error" in data:
                    continue
                    
                # Build Symbol Index matching ContextPackBuilder's expectation: {"files": {"path/to/file": {"Symbol": "class/func"}}}
                # And build Symbol Definitions: {"files": {"path/to/file": {"Symbol": {"type": "class", "snippet": "..."}}}}
                if filepath not in symbol_index["files"]:
                    symbol_index["files"][filepath] = {}
                    symbol_definitions["files"][filepath] = {}
                    
                for cls in data.get("classes", []):
                    # Handle both old (string) and new (dict) formats during cache transition
                    name = cls["name"] if isinstance(cls, dict) else cls
                    snippet = cls.get("snippet", "") if isinstance(cls, dict) else ""
                    symbol_index["files"][filepath][name] = "class"
                    symbol_definitions["files"][filepath][name] = {"type": "class", "snippet": snippet}
                    
                for func in data.get("functions", []):
                    name = func["name"] if isinstance(func, dict) else func
                    snippet = func.get("snippet", "") if isinstance(func, dict) else ""
                    symbol_index["files"][filepath][name] = "function"
                    symbol_definitions["files"][filepath][name] = {"type": "function", "snippet": snippet}
                    
                import_graph[filepath] = data.get("imports", [])
                
                # Heuristic Test Map for this specific file (if it's an impl file)
                if filepath in impl_files:
                    basename = os.path.basename(filepath).replace(".py", "")
                    likely_tests = []
                    for t in test_files:
                        if f"test_{basename}" in t or f"{basename}_test" in t:
                            likely_tests.append(t)
                    test_map[filepath] = likely_tests
                
            manifest["generated_at"] = datetime.utcnow().isoformat()
            manifest["files_indexed"] = len(repo_map)
            
            with open(os.path.join(cache_dir, "cache_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            with open(os.path.join(cache_dir, "repo_map.json"), "w", encoding="utf-8") as f:
                json.dump(repo_map, f, indent=2)
            with open(os.path.join(cache_dir, "symbol_index.json"), "w", encoding="utf-8") as f:
                json.dump(symbol_index, f, indent=2)
            with open(os.path.join(cache_dir, "symbol_definitions.json"), "w", encoding="utf-8") as f:
                json.dump(symbol_definitions, f, indent=2)
            with open(os.path.join(cache_dir, "import_graph.json"), "w", encoding="utf-8") as f:
                json.dump(import_graph, f, indent=2)
            with open(os.path.join(cache_dir, "test_map.json"), "w", encoding="utf-8") as f:
                json.dump(test_map, f, indent=2)
        except Exception as e:
            print(f"Failed to save cache artifacts: {e}")

    def get_repo_map_summary(self, max_length: int = 12000) -> str:
        """Returns a string representation of the repo map suitable for LLM context, with compression."""
        mapping = self.generate_repo_map()
        lines = ["# Repository Map"]
        current_length = len(lines[0])
        
        for filepath, data in mapping.items():
            file_summary = []
            file_summary.append(f"\n## {filepath}")
            if "error" in data:
                file_summary.append(f"  Error parsing: {data['error']}")
            else:
                if data.get('classes'):
                    file_summary.append(f"  Classes: {', '.join(data['classes'])}")
                if data.get('functions'):
                    file_summary.append(f"  Functions: {', '.join(data['functions'])}")
                if data.get('imports'):
                    file_summary.append(f"  Dependencies: {', '.join(data['imports'])}")
            
            # Skip files with no meaningful symbols to compress prompt further
            if len(file_summary) == 1:
                continue
                
            block = "\n".join(file_summary)
            if current_length + len(block) > max_length:
                lines.append("\n## ... (Repo Map Truncated due to size limits. Use precise imports.) ...")
                break
                
            lines.append(block)
            current_length += len(block)
            
        return "\n".join(lines)
