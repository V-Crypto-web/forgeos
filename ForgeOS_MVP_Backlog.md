# 📦 ForgeOS MVP Engineering Backlog
*The Foundation for the Autonomous Development Infrastructure*

## 🎯 Phase 1: Engine Foundation (Months 1-2)
*Goal: Base Orchestrator, Deterministic Sandbox, and Intelligence Supply Layer.*

### Epic 1.1: Core Orchestrator & State Machine
- [ ] Implement `INIT` → `SPEC_SYNC` → `PLAN` → `EXECUTE` → `DONE/FAILED` State Machine.
- [ ] LangGraph setup for multi-agent loops (Planner, Coder, Verifier).
- [ ] Implement "Change Budget" logic (Planner task chunking if max files/LOC is exceeded).

### Epic 1.2: Intelligence Supply Layer (Model Router)
- [ ] Setup LiteLLM abstract router.
- [ ] Add support for Anthropic (Claude 3.7) & OpenAI (GPT-4o/mini) via single API.
- [ ] Implement fallback & failover routing logic.

### Epic 1.3: Deterministic Execution Sandbox
- [ ] Create Docker-based isolated execution container structure.
- [ ] Implement Command Allowlist (block `rm -rf`, raw OS calls).
- [ ] Implement timeout restrictions and secure file I/O layer.

### Epic 1.4: Multi-Agent Concurrency Control
- [ ] Implement Git Branch isolation per Coder agent.
- [ ] Implement file-locking mechanism for active agent targets.
- [ ] Add baseline orchestrator merge resolution logic.

---

## 🎯 Phase 2: Traceability & Observability (Months 3-4)
*Goal: Making the system predictable, auditable, and transparent.*

### Epic 2.1: Spec Engine, Repo Map & Traceability
- [ ] Spec & ADR ingestion parser (Markdown/JSON to Planner context).
- [ ] Build Repo Map generation module (AST-based module/dependency graph).
- [ ] Implement context injection: `spec_item_id` → `task_id` traceability link.
- [ ] Map commits to specific tasks internally in the database.

### Epic 2.2: Observability Stack & Telemetry
- [ ] Export internal state machine transitions to structured logs.
- [ ] Implement agent tracing (Planner latency, Coder loops).
- [ ] Configure basic OpenTelemetry output (OTel).

### Epic 2.3: Anti-Loop & Strategy Governor
- [ ] Implement Failure Memory (detect repeating errors).
- [ ] Implement heuristic progress metric (delta coverage, test results).
- [ ] Setup Strategy Switch tree (Patch -> Rewrite -> Test-Driven -> Escalate).

---

## 🎯 Phase 3: The Platform & Cloud (Months 5-6)
*Goal: Transforming the Engine into a B2B PaaS.*

### Epic 3.1: Developer API & Connectors
- [ ] Build FastAPI Public Router (`execute_task`, `create_pr`).
- [ ] Build GitHub Connector (Clone, Branch, PR creation, CI polling).
- [ ] Implement Jira/Linear webhook listeners (Issue to Task conversion).

### Epic 3.2: Multi-Tenant & Cost Governance
- [ ] Implement `Organization` -> `Workspace` Database Schema.
- [ ] Implemement Secrets Vault (Per-tenant AES-encrypted DB for API Keys).
- [ ] Build Cost Governance logic (Per-project token quota tracking).

### Epic 3.3: Human-in-the-Loop & VCS Policies
- [ ] Implement 'Assist Mode', 'Supervised Mode', and 'Autonomous Mode' toggles.
- [ ] Enforce VCS push restrictions via Policy Enforcement Layer.

---

## 🎯 Phase 4: Desktop Interface & Production (Months 7-8)
*Goal: Providing the CTO interface and artifact generation.*

### Epic 4.1: Forge Desktop UI (Tauri)
- [ ] Build macOS native Tauri shell.
- [ ] Implement Engineering Dashboard (Code Diff Viewer, Task Graph Tracker).
- [ ] Hook UI directly into the Core Orchestrator Local REST API.

### Epic 4.2: Documentation Engine & Artifacts
- [ ] Implement automatic PR description generation explicitly linked to Specs.
- [ ] Implement automated Release Note compilation based on Traceability logic.

### Epic 4.3: DevSim (Phase 1.0)
- [ ] Implement basic Three.js visualization of the Agent Town.
- [ ] Hook WebSocket logs to 3D models (Buildings lighting up on activity).
