import os
import re
from typing import List, Dict, Any, Set
from forgeos.repo.repo_analyzer import RepoAnalyzer

class RepoIntelligenceLayer:
    """
    Module 15: Repo Intelligence Layer (Execution OS Layer)
    Provides deep semantic analysis of the repository structure.
    Implements Hotspot Detection to trace dependencies and find code areas
    most likely relevant to a given issue description, minimizing context windows.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.analyzer = RepoAnalyzer(workspace_path)
        
    def get_hotspots(self, issue_text: str, top_n: int = 15) -> List[str]:
        """
        Extracts keywords from the issue text and cross-references them
        with the Repo Map to find the most relevant files.
        """
        repo_map = self.analyzer.generate_repo_map()
        
        words = set(re.findall(r'\b[a-zA-Z_]+\b', issue_text.lower()))
        stopwords = {"this", "is", "a", "an", "the", "to", "and", "in", "of", "for", "with", "on", "it", "that", "as"}
        keywords = {w for w in words if len(w) > 3 and w not in stopwords}
        
        scores: Dict[str, int] = {}
        for filepath, data in repo_map.items():
            if "error" in data: continue
            
            score = 0
            file_str = filepath.lower()
            
            # Substring match in path highly weighted
            for kw in keywords:
                if kw in file_str: score += 5
                
            # Class match
            for cls in data.get("classes", []):
                cls_lower = cls.lower()
                for kw in keywords:
                    if kw in cls_lower: score += 3
                    
            # Function match
            for func in data.get("functions", []):
                func_lower = func.lower()
                for kw in keywords:
                    if kw in func_lower: score += 2
                    
            if score > 0:
                scores[filepath] = score
                
        # Sort by score descending
        sorted_files = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        return sorted_files[:top_n]
        
    def build_test_mapping_index(self) -> Dict[str, List[str]]:
        """
        Creates a robust map linking implementation files to their test files.
        Useful for the Execution OS Verification Phase to know what tests to run.
        """
        repo_map = self.analyzer.generate_repo_map()
        test_files = [f for f in repo_map.keys() if f.startswith("test_") or f.endswith("_test.py") or "/test_" in f or "/tests/" in f]
        impl_files = [f for f in repo_map.keys() if f not in test_files]
        
        test_map = {}
        for impl in impl_files:
            basename = os.path.basename(impl).replace(".py", "")
            linked_tests = []
            for t in test_files:
                if f"test_{basename}" in t or f"{basename}_test" in t:
                    linked_tests.append(t)
                # If imported into test file, also link
                elif impl.replace(".py", "").replace("/", ".") in repo_map[t].get("imports", []):
                    linked_tests.append(t)
            if linked_tests:
                test_map[impl] = list(set(linked_tests))
                
        return test_map
