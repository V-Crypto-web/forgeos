import os
import json
import math
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    if not vec1 or not vec2:
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)

class PatternRecord(BaseModel):
    pattern_id: str
    repo_class: str
    issue_class: str
    failure_signature: str
    strategy: str
    test_scope: str
    patch_width: str
    outcome: str # "success" or "failed"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    description: str = ""
    # Epic 44 Additions
    usage_count: int = 1
    success_count: int = 0
    failure_count: int = 0
    confidence_score: float = 0.5
    embedding: List[float] = Field(default_factory=list)

class PatternLibrary:
    def __init__(self, storage_dir: str = "/tmp/forgeos_patterns"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.patterns: List[PatternRecord] = self._load_all_patterns()

    def _load_all_patterns(self) -> List[PatternRecord]:
        patterns = []
        for filename in os.listdir(self.storage_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.storage_dir, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                        patterns.append(PatternRecord(**data))
                except Exception as e:
                    print(f"Failed to load pattern {filename}: {e}")
        return patterns

    def save_pattern(self, pattern: PatternRecord) -> None:
        # Initialize counts if needed
        if pattern.outcome == "success":
            pattern.success_count = 1
            pattern.failure_count = 0
        else:
            pattern.success_count = 0
            pattern.failure_count = 1
        pattern.confidence_score = 0.5

        # Canonicalization / Deduplication
        if pattern.embedding:
            for existing in self.patterns:
                # Layer A match for merging
                if existing.repo_class == pattern.repo_class and existing.strategy == pattern.strategy:
                    sim = cosine_similarity(pattern.embedding, existing.embedding)
                    print(f"DEBUG MERGE: {pattern.pattern_id} vs {existing.pattern_id} -> Sim: {sim:.3f}")
                    if sim >= 0.75:
                        print(f"Canonicalizing pattern {pattern.pattern_id} into {existing.pattern_id} (Sim: {sim:.2f})")
                        # Merge into existing
                        existing.usage_count += 1
                        if pattern.outcome == "success":
                            existing.success_count += 1
                        else:
                            existing.failure_count += 1
                        
                        # Recalculate confidence (Bayesian smoothed)
                        # Avoid 0 division and extreme swings early on
                        existing.confidence_score = (existing.success_count + 1) / (existing.usage_count + 2)
                        
                        # Save updated existing record and return to prevent duplicating
                        self._write_to_disk(existing)
                        return

        # No match found, save as new
        if pattern.usage_count > 0:
            pattern.confidence_score = (pattern.success_count + 1) / (pattern.usage_count + 2)
            
        self._write_to_disk(pattern)
        self.patterns.append(pattern)

    def _write_to_disk(self, pattern: PatternRecord):
        # We write using pattern_id. Overwrites if canonicalized.
        filename = f"{pattern.pattern_id}.json"
        filepath = os.path.join(self.storage_dir, filename)
        with open(filepath, "w") as f:
            json.dump(pattern.dict(), f, indent=2)

    def find_similar_patterns(self, repo_class: str, issue_class: str, query_embedding: List[float] = None, top_k: int = 3) -> Dict[str, Any]:
        """
        Hybrid 3-Layer Retrieval Stack.
        """
        scored_patterns = []
        for p in self.patterns:
            # Layer A: Hard semantic filters (we can be somewhat soft, but give huge boosts)
            layer_a_score = 0.0
            if p.repo_class.lower() == repo_class.lower():
                layer_a_score += 1.0 # Base match requirement
                
            # Discard if fundamentally mismatched repo class
            if layer_a_score == 0.0 and len(self.patterns) > 5:
                continue
                
            if p.issue_class.lower() == issue_class.lower():
                layer_a_score += 0.5
                
            # Layer B: Embedding-based similarity
            layer_b_score = 0.0
            if query_embedding and p.embedding:
                layer_b_score = cosine_similarity(query_embedding, p.embedding)
                print(f"DEBUG LAYER B: {p.pattern_id} -> Sim: {layer_b_score:.3f}")
                if layer_b_score < 0.60:
                    continue # Discard dissimilar shapes
            
            # Layer C: Hybrid Ranking Formula
            # If we don't have embeddings, fallback purely to hard heuristics + confidence
            if query_embedding and p.embedding:
                final_score = (layer_b_score * 0.6) + (p.confidence_score * 0.4) + (layer_a_score * 0.2)
            else:
                final_score = (layer_a_score * 0.6) + (p.confidence_score * 0.4)
                
            print(f"DEBUG RETRIEVE: {p.pattern_id} | Layer A: {layer_a_score} | Layer B: {layer_b_score:.3f} | Conf: {p.confidence_score:.2f} | Final: {final_score:.3f}")
                
            if final_score > 0.3:
                scored_patterns.append((final_score, p))
                
        # Sort by final score descending
        scored_patterns.sort(key=lambda x: x[0], reverse=True)
        top_matches = [p for _, p in scored_patterns[:top_k]]
        
        successes = [p for p in top_matches if p.success_count > p.failure_count or p.outcome == "success"]
        failures = [p for p in top_matches if p.failure_count >= p.success_count and p.outcome == "failed"]
        
        if not top_matches:
            return {"similar_patterns_found": 0, "status": "No strict engineering pattern match found."}
            
        recommended_strategies = list(set([p.strategy for p in successes]))
        avoid_strategies = list(set([p.strategy for p in failures]))
        test_scopes = list(set([p.test_scope for p in successes]))
        
        return {
            "similar_patterns_found": len(top_matches),
            "recommended_strategies": recommended_strategies if recommended_strategies else ["Requires novel approach"],
            "avoid_strategies": avoid_strategies,
            "recommended_test_scopes": test_scopes,
            "historical_notes": [f"{p.description} (Success: {p.success_count}/{p.usage_count}, Conf: {p.confidence_score:.2f})" for p in successes]
        }
