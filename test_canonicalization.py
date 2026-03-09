import os
import shutil
from forgeos.memory.pattern_library import PatternLibrary, PatternRecord
from forgeos.providers.model_router import ProviderRouter

def run_test():
    storage = "/tmp/forgeos_patterns_test"
    if os.path.exists(storage):
        shutil.rmtree(storage)

    library = PatternLibrary(storage_dir=storage)
    router = ProviderRouter()

    print("Embedding pattern...")
    embedding = router.get_embedding("Issue: tiny_bugfix The NoneType token is unhandled. Failure: NoneType object has no attribute strip")
    
    # Fallback for deterministic tests when API key is missing
    if not embedding:
        print("Using deterministic mock embedding for local test...")
        embedding = [0.1] * 1536
    
    p1 = PatternRecord(
        pattern_id="test_pat_1",
        repo_class="http_client",
        issue_class="tiny_bugfix",
        failure_signature="NoneType object has no attribute strip",
        strategy="minimal_guard_patch",
        test_scope="unit_tests",
        patch_width="narrow_local",
        outcome="success",
        embedding=embedding
    )
    
    # Save once
    library.save_pattern(p1)
    print(f"Saved Pat 1. Library size: {len(library.patterns)}")
    
    # Create an identical bug but different run
    p2 = PatternRecord(
        pattern_id="test_pat_2",
        repo_class="http_client",
        issue_class="tiny_bugfix",
        failure_signature="NoneType object has no attribute strip",
        strategy="minimal_guard_patch",
        test_scope="unit_tests",
        patch_width="narrow_local",
        outcome="failed", # This one failed
        embedding=embedding # Same embedding
    )
    
    # Save second time
    library.save_pattern(p2)
    print(f"Saved Pat 2. Library size: {len(library.patterns)}")
    
    final_pat = library.patterns[0]
    print(f"Usage count: {final_pat.usage_count}")
    print(f"Success/Fail: {final_pat.success_count}/{final_pat.failure_count}")
    print(f"Confidence score: {final_pat.confidence_score:.3f}")

if __name__ == "__main__":
    run_test()
