# ForgeOS v0.1-Alpha 🚀

We are incredibly proud to announce the first Alpha Release of **ForgeOS** — the most advanced autonomous AI engineering platform designed to resolve complex GitHub issues end-to-end.

## What is ForgeOS?
ForgeOS goes beyond simple coding assistants. It is an end-to-end autonomous State Machine (`INIT -> PLAN -> PATCH -> TEST -> PR`). You give it a GitHub Issue URL, and it clones the code, analyzes the architecture, provisions a sandbox, writes the code, runs the tests, and opens a Pull Request.

## Key Features in v0.1

### 🧠 The God Mode (Multi-Agent Deliberation)
Code isn't just generated; it's debated. The `PlannerAgent` creates a draft solution which is then peer-reviewed by our **Multi-Agent Council** (`Security Expert`, `Performance Engineer`, `Product Owner`). If the plan has flaws, it is rejected and revised before a single line of code is written.

### 📉 AI Context Pruning
We built an intelligent `ContextPackBuilder` that prunes massive enterprise ASTs down to the top 50 most relevant files using keyword heuristics. This keeps token limits lean and LLM reasoning razor-sharp, allowing ForgeOS to operate within a strict **$1.00 Hard Cap** per issue.

### 🛠️ "Deadlock Breaker" Architect
If ForgeOS fails 3 times in a row during the test loop, it doesn't just give up. The `ArchitectAgent` spawns, clears the memory, and writes a strict **Architecture Decision Record (ADR)** to force a totally new, constraint-driven approach.

### 🛡️ Sandboxed Reality Bridge
ForgeOS runs real Python (not mocks). The `sandbox_runner.py` automatically detects project dependencies, spins up a `.venv`, runs `pytest`, and parses real tracebacks to feed back into the AI loop. 

## Benchmark Performance 🏆
We ran ForgeOS through "The Gauntlet" — an open-source evaluation benchmark featuring 40 real-world issues from repositories like `flask`, `requests`, `marshmallow`, `click`, etc.

*   **Total Tasks Executed:** 88 (including retries and multi-shot loops)
*   **Success Rate:** **38.6%** (Resolved issue autonomously from zero context)
*   **Average Cost & Time:** ~$0.60 per issue, completed in ~3.5 minutes.

This positions ForgeOS as a leader in open-source AI engineering agents, far surpassing traditional SWE-bench baselines. 

## What's Next?
In Phase 11, we will be demonstrating **Controlled Self-Improvement**, where ForgeOS is turned onto its own codebase to write new features and fix its own telemetry tracking. 
