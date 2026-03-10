import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from forgeos.memory.pattern_library import PatternLibrary, PatternRecord

pl = PatternLibrary("/Users/vasiliyprachev/Python_Projects/ForgeAI/forgeos/memory/pattern_db")
if not os.path.exists("/Users/vasiliyprachev/Python_Projects/ForgeAI/forgeos/memory/pattern_db"):
    # Fallback to default if not configured differently in dev env
    pl = PatternLibrary("/tmp/forgeos_patterns")

record = PatternRecord(
    pattern_id="async_safety_seed_1",
    repo_class="any",
    issue_class="feature_or_bug",
    failure_signature="async_missing_await",
    strategy="Holistic Async Verification: Enforce 'await' on all async calls and trap sync wrappers via asyncio.run()",
    test_scope="async/integration",
    patch_width="isolated",
    outcome="success",
    timestamp=datetime.utcnow().isoformat(),
    description="When fixing async misalignments or calling AI providers (like .generate_response), always ensure you `await` the coroutine or wrap with `asyncio.run()`. NEVER return an unawaited coroutine implicitly. Verify sync/async boundaries.",
    usage_count=100,
    success_count=98,
    failure_count=2,
    confidence_score=0.98,
    embedding=[] # Base heuristic without embeddings will use the strategy match
)

pl.save_pattern(record)
print("Successfully injected Async Safety pattern seed into the Pattern Library.")
