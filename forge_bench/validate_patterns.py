import os
import shutil
from forgeos.memory.pattern_library import PatternLibrary, PatternRecord
from forgeos.providers.model_router import ProviderRouter

def run_validation():
    storage = "/tmp/forgeos_patterns_validation"
    if os.path.exists(storage):
        shutil.rmtree(storage)

    library = PatternLibrary(storage_dir=storage)
    router = ProviderRouter()

    print("--- 1. Generating Embeddings for Mock Bugs ---")
    
    # Bug A1: Simple NoneType error
    bug_a1_text = "Issue: tiny_bugfix When passing None to the parse_json function, it crashes with AttributeError instead of returning empty dict. Failure: AttributeError: 'NoneType' object has no attribute 'get'"
    emb_a1 = router.get_embedding(bug_a1_text)
    
    # Bug A2: Another simple NoneType error (should merge with A1)
    bug_a2_text = "Issue: tiny_bugfix The dict parser dies if the input payload is null. Failure: AttributeError: 'NoneType' object has no attribute 'get'"
    emb_a2 = router.get_embedding(bug_a2_text)

    # Bug B1: Async timeout regression
    bug_b1_text = "Issue: timeout_regression The async worker hangs indefinitely if the downstream API does not respond within the 5s window. Failure: TimeoutError: Operation timed out"
    emb_b1 = router.get_embedding(bug_b1_text)

    # Bug C1: Async semantic break (missing await)
    bug_c1_text = "Issue: async_bug The database query result is a coroutine object, not the actual User record. Failure: TypeError: 'coroutine' object is not subscriptable"
    emb_c1 = router.get_embedding(bug_c1_text)

    print("--- 2. Saving Mock Bugs (Testing Canonicalization) ---")
    
    records = [
        PatternRecord(
            pattern_id="bug_a1", repo_class="backend", issue_class="tiny_bugfix",
            failure_signature="AttributeError: 'NoneType' object", strategy="add_none_guard",
            test_scope="unit", patch_width="narrow", outcome="success", embedding=emb_a1, description="Added None guard"
        ),
        PatternRecord(
            pattern_id="bug_a2", repo_class="backend", issue_class="tiny_bugfix",
            failure_signature="AttributeError: 'NoneType' object", strategy="add_none_guard",
            test_scope="unit", patch_width="narrow", outcome="success", embedding=emb_a2, description="Handled null input"
        ),
        PatternRecord(
            pattern_id="bug_b1", repo_class="backend", issue_class="timeout_regression",
            failure_signature="TimeoutError", strategy="add_asyncio_wait_for",
            test_scope="integration", patch_width="narrow", outcome="success", embedding=emb_b1, description="Added wait_for"
        ),
        PatternRecord(
            pattern_id="bug_c1", repo_class="backend", issue_class="async_bug",
            failure_signature="TypeError: 'coroutine'", strategy="add_await_keyword",
            test_scope="unit", patch_width="narrow", outcome="success", embedding=emb_c1, description="Awaited DB call"
        )
    ]

    for rec in records:
        library.save_pattern(rec)

    print("\n--- 3. Canonicalization Results ---")
    print(f"Total separate records in library: {len(library.patterns)}")
    for p in library.patterns:
        print(f"  - ID: {p.pattern_id} | Usage: {p.usage_count} | Conf: {p.confidence_score:.2f} | Desc: {p.description}")

    print("\n--- 4. Testing Hybrid Retrieval ---")
    
    query_text = "Issue: async_bug The API handler returns a coroutine instead of a Response object because the service method was not awaited. Failure: TypeError: 'coroutine' object has no attribute 'status_code'"
    print(f"Query: {query_text}")
    query_emb = router.get_embedding(query_text)
    
    results = library.find_similar_patterns(repo_class="backend", issue_class="async_bug", query_embedding=query_emb, top_k=2)
    
    print("\nRetrieval Results:")
    print(f"Status: {results.get('status', 'OK')}")
    print(f"Strategies recommended: {results.get('recommended_strategies', [])}")
    print(f"Historical notes: {results.get('historical_notes', [])}")

if __name__ == "__main__":
    run_validation()
