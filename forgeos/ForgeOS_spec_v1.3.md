# 🏗️ Техническое задание (ТЗ) v1.1: ForgeOS
**Agentic Engineering OS (Mac + Cloud)**

## 1. Концепция: Development as Computation
**Описание:** ForgeOS — это не просто IDE или AI-ассистент, это потенциально **новая категория продуктов**. Эволюция выглядит так: IDE → AI Assistant (Cursor) → Autonomous Development OS (ForgeOS).
В отличие от редакторов кода, требующих вовлечения разработчика, ForgeOS реализует **полный цикл автономной разработки** (Plan → Code → Verify → Loop). Это **Forge Development Engine**, превращающий разработку в вычислимый процесс.

**Три ключевых режима работы:**
1. **Engineering Mode:** Классический профессиональный интерфейс для контроля (код, diff, тесты, задачи).
2. **Simulation Mode (Game Mode):** Observability layer. Визуальный UX-слой процесса разработки в стиле SimCity для управления сложными потоками задач и экономикой токенов. Это "Grafana для AI-разработки", но визуализированная.
3. **API Mode (Autonomous Dev Engine as a Service):** Доступ к ядру через API для развертывания на серверах. Это мощнейшая независимая часть продукта — использовать движок разработки как вычислительный ресурс.

*Стратегический поинт:* ForgeOS — это не IDE. IDE — это просто интерфейс. Главный продукт — это автономный **Forge Development Engine** (software development as computation).

---

## 2. Архитектура системы (High-Level)

### 2.1. Клиент-серверная архитектура
- **Desktop Client (macOS):** Native-оболочка (Tauri + React/Three.js) — *Forge Desktop*.
- **Core Orchestrator:** Сердце системы (FastAPI + Python + LangGraph) — *Forge Development Engine*.
- **Execution Sandboxes:** Изолированные контейнеры (Docker/PTY) со строгим Security Layer.
- **API Gateway & Connector Layer (Cloud):** Точка входа для серверного/enterprise-режима и коннекторы к GitHub, GitLab, Jira, Slack, CI/CD. — *Forge Cloud*.

### 2.2. Ролевая модель интеллекта (The Brains)
Самая частая причина падения AI IDE — одна модель делает всё. В ForgeOS роли жестко разделены:
1. **Spec Brain:** Переводит требования в структурированное ТЗ. Главный арбитр Definition of Done.
2. **Planner Brain (Orchestrator):** Умная модель (GPT-4o/Claude 3.7). Строит Task Graph, назначает работу. Не пишет код!
3. **Coder Brain (Executor):** Быстрая/дешевая модель (Haiku/GPT-4o-mini). Пишет только diff-ы.
4. **Verifier Brain:** Анализирует выводы тестов и линтеров.
5. **Critic Brain:** Ищет архитектурный долг и уязвимости.
6. **Resource Scheduler (ex-Token Economist):** Управляет пулом моделей, токенами, параллелизмом и приоритетами. Перекидывает простые задачи на дешевые быстрые модели, а сложные — на дорогие (GPT-4o/Claude 3.7). Фиксирует прожорливые лупы и оптимизирует затраты на лету.
7. **Anti-Loop Governor:** Гибрид (Heuristic Engine + Small LLM). Контролирует метрики прогресса и меняет стратегии, защищая от циклов. LLM-слой лишь помогает принимать сложные решения, но базовые правила — жесткая эвристика (чтобы сам Governor не галлюцинировал).

### 2.3. Intelligence Supply Layer (LLM Vendor Abstraction)
ForgeOS использует *plural intelligence infrastructure*, где модели рассматриваются как взаимозаменяемые вычислительные узлы. Система не зависит от одного AI-провайдера.
- **Multi-Provider Routing:** Одновременная работа с OpenAI, Anthropic, Google и локальными open-weight моделями через единый слой абстракции.
- **Role-based Assignment:** Назначение разных моделей под разные агентские роли (Planner = GPT-4o, Coder = Haiku, Critic = Claude 3.5 Sonnet).
- **Fallback & Failover:** Автоматическое переключение на резервную модель, если основной провайдер деградировал (упал или уперся в rate limits).
- **A/B Benchmarking:** Динамическое сравнение качества моделей на потоке задач проекта.

---

## 3. Ключевые системные модули продукта

### Module 1: Live Spec Engine & Traceability (Killer Feature 🔥)
Главное преимущество над рынком. Система, которая реально "держит Spec". Хранит актуальное ТЗ, Acceptance Criteria, связи с кодом. В обычных системах ТЗ размывается в чате.
- **Spec-to-Code Traceability:** Каждое изменение кода (или таска) имеет строгую цепочку линкования: `spec_item_id` → `acceptance_criteria` → `task_id` → `decision_id` → `commit_id`. Это дает 100% обратную трассировку, enterprise-аудит и объяснимость (Why was this code changed?).

### Module 2: Memory Architecture & Context Compression
Решает проблему "взрыва контекста". Planner не должен через 20 итераций начать галлюцинировать. **LLM не является источником правды** — она лишь принимает решения на основе жестких данных (Spec, Repo Graph, Tests, ADR).
Типы памяти:
- **Short-term context:** Текущая подзадача и диффы.
- **Repo Map (Критично):** Контекст всего репозитория (структура модулей, зависимости, импорты, API, тесты), строящийся через AST. Позволяет Planner понимать масштаб изменений (если меняем A, сломается B).
- **Spec & Architecture Decision Records (ADR):** Историческая память решений (почему выбрали Redis, почему архитектура именно такая). Planner всегда читает ADR перед планированием новых задач. 
- **Failure Memory:** Запоминает неудачные попытки (фэйл-сигнатуры: `test_timeout` -> попытались 3 раза -> failed -> пометили стратегию как неверную). Это предотвращает бесконечный "ремонт".

### Module 3: Deterministic Operations & Execution Sandbox
Строгое правило: LLM только выдает инструкции (reasoning), действия делают **детерминированные инструменты** (tools). LLM сама не парсит код регулярками и не дергает `bash` сырыми командами.
- **Policy Enforcement Layer (Критично!):** Централизованный контроллер политик. Решает: можно ли пушить, мержить, запускать опасные команды, трогать red-zone код. Включает Command allowlist, filesystem & network restrictions, строгий timeout control.

### Module 4: Execution State Machine, Concurrency & Oversight
Для предотвращения хаоса система подчиняется строгой State Machine:
`INIT` → `SPEC_SYNC` → `PLAN` → `IMPACT_ANALYSIS` → `TASK_PICK` → `EXECUTE` → `VERIFY` → `CRITIQUE` → `RETRY` → `DONE` (или `FAILED`).
Так как работают несколько Coder Agents одновременно, модуль включает **Concurrency Control**:
- File locking, Branch isolation, Merge validation.
- **Change Budget (Ограничение масштаба):** Система жестко лимитирует размер одной задачи (например, max files per task = 10, max LOC = 500). Если задача превышает лимит, Planner обязан разбить её. Это защищает проект от поведения "AI решил переписать половину кодовой базы".
- **Artifact Layer:** Система работает как *artifact-producing engine*, явно генерируя и сохраняя: PRs, commits, patches, test reports, benchmark reports, release notes, architecture decisions.
- **Human Oversight Modes (Уровни автономии):** Настраиваются per-project для безопасного adoption:
  - *Plan Mode:* генерирует план задач, код не пишет.
  - *Assist Mode:* предлагает patch, человек подтверждает.
  - *Supervised Mode:* самостоятельно выполняет задачи, PR требует review.
  - *Autonomous Mode:* выполняет задачи, auto-merge только для low-risk изменений.
  - *Full Autonomous Mode:* полностью автоматический цикл (trusted environments).

### Module 5: Anti-Loop Governor & Strategy Switching
Не просто делает "хард-стоп". Он измеряет **Progress Metric** (tests passed, compile success, coverage change, file delta, error signature, spec match).
Если прогресс остановился, Governor идет по дереву смены стратегий (Strategy Switching):
1. `Patch Strategy` (попробуй починить текущий код) →
2. `Rewrite Strategy` (перепиши эту функцию с нуля) →
3. `Test-driven Strategy` (сначала напиши изолированный тест, потом код) →
4. `Isolate Module Strategy` (вынеси проблему в изолированный sandbox) →
5. `Rollback Strategy` (откат ветки `git reset --hard`) →
6. `Escalate` (сжатый алерт кожаному CTO о блоке).

### Module 6: Observability Stack & Telemetry
Базовый фундамент прозрачности системы (до реализации Game Mode). 
Логирует все метрики, трейсы агентов, cost events, rollback rates и Audit Trail каждого шага State Machine. Без этого слоя система — черный ящик.

### Module 7: Evaluation & Benchmark Layer
Модуль для контроля качества ядра и proof of self-improvement. Разделен на два контура:
1. **Task-level Evaluation:** Прошла ли конкретная задача, прошел ли код линтеры и тесты.
2. **Engine-level Evaluation:** Оценивает сам движок на `benchmark repos`. Сравнивает latency, token cost, success rate и regression rate кандидатной версии движка с baseline. Любое самоулучшение (кандидат) верифицируется здесь, предохраняя систему.

### Module 8: Model Provider Layer & Routing Engine
Отвечает за provider registry, model routing policies и независимость от конкурентных вендоров. Обеспечивает failover logic, cost/performance optimization. Делает B2B-продажи возможными для клиентов, требующих использовать только свои API-ключи, private deployments или локальные датацентры.

### Module 9: Documentation & Reporting Engine
ForgeOS автоматически генерирует и поддерживает актуальную документацию системы и проекта, неразрывно связанную с Traceability Layer (`spec` → `commit` → `doc`).
- **Code & Arch Docs:** генерация README, docstrings, API docs, архитектурных диаграмм и графов зависимостей (Markdown, HTML, OpenAPI).
- **Development & Release Reports:** генерация отчетов о том, что реализовано, тестов, остаточных рисков и полных release notes по фичам/багам.
- **Improvement Reports:** метрики самоулучшения движка (token cost reductions, latency changes).

### Module 10: Plugin & Tooling Framework
ForgeOS поддерживает расширения через открытую plugin-архитектуру, что критично для превращения продукта в экосистему.
- **Capabilities:** Плагины могут добавлять новые deterministic tools, security scanners, custom linters, internal APIs и company-specific CI features.
- **Plugin API:** Поддерживает tool registration, sandbox execution policies и artifact reporting. Все плагины ограничены Role-Based политиками (Policy Enforcement Layer).

### Module 11: Change Impact Engine (Smart Engineering Navigator)
Оценивает радиус воздействия любого изменения **до применения патча**. Использует repo map, call graph, test map, traceability links и failure memory для расчёта `impact radius`, `risk score` и `required verification scope`.
В отличие от обычных AI-IDE, которые применяют патч и смотрят, что сломалось, этот модуль позволяет ForgeOS заранее понимать системную цену изменения.
- **Impact Radius & Risk Score:** Оценка рисков (low, medium, high, critical) на базе того, сколько файлов/модулей затронуто (например, 1 файл = low; `auth.py` или `billing` = critical).
- **Required Verification Set:** Определение, какие проверки нужны (только локальные unit-тесты, full regression suite или e2e).
- **Allowed Strategy:** Установка ограничений (разрешен только local patch, запрещен rewrite модуля, или требуется human approval).

---

## 4. Спецификация Game Mode ("DevSim")
*Важно: Game Mode / DevSim — это выдающийся визуальный интерфейс, 3D-надстройка над фундаментальным **Observability Layer**, поэтому реализуется в конце (Phase 3).*
- **Визуальная метафора:** Город (Фабрика), где тикеты-задачи перемещаются по дорогам между агентами-зданиями.
- **Объекты карты:** Planning Hub, Coder Plants, Test Labs.
- **Полигон CTO:** Визуализация токен-экономики. Если здание (Coder Agent) зависло на 2 часа и сжирает бюджет, над ним горит "пожар" — CTO в 1 клик его "охлаждает" или меняет модель фабрике.
- **Инструменты:** React Fiber, Three.js / WebGL + Data Streaming.

---

## 5. Forge Development Engine API & Cloud Capabilities
Ядро ForgeOS как backend-сервис (Autonomous Dev Team API). Интеграция с GitHub/Jira через встроенный **Connector Layer**: вызов агентов по вебхукам, рефакторинг "в облаке", продажа мощности движка как B2B SaaS.

---

## 6. Технологический стек (MVP)
- **Desktop Shell:** Tauri + React. (Максимально быстрый, легкий, native interface).
- **Core Orchestrator:** FastAPI + Python (LangGraph/Pydantic AI).
- **Deterministic Ops:** Ripgrep, Tree-sitter, Git Cbindings.
- **Model Router:** LiteLLM (единое окно).
- **Sandbox:** Docker Engine SDK + macOS Process Restrictions.

---

## 7. Roadmap Разработки (От идеи до релиза)

### Phase 1: MVP "Terminal & Core" (Месяцы 1-2)  *✅ Реалистично*
- Headless-режим. Запуск Base Planner -> Coder -> Verifier loop в терминале.
- Интеграция Spec Engine, Failure Memory, Security Sandbox.

### Phase 2: "Mac-Native GUI + API Engine" (Месяцы 3-4)  *✅ Реалистично*
- Интеграция Tauri-оболочки (Engineering UI: логи, diff, граф задач).
- Вывод оркестратора в фоновый демон с REST API. Движок "оживает".

### Phase 3: "Game Mode & Enterprise Cloud" (Месяцы 5-8) *⚠ Обновлено с учетом Data Streaming*
- Разработка WebGL/Three.js UX-слоя (SimCity style). Привязка 3D-движка к реалтайм REST/WebSocket логам API.
- Настройка billing-архитектуры для Enterprise SaaS.

---

## 8. Оценка Команды и Стоимости (Для MVP / v1.0)

Компактная "A-Team" для старта:
1. **AI / LLM Architect & Core Backend**
2. **Infrastructure Dev (Sandboxing, AST, Security, API)**
3. **Frontend / WebGL Engineer (Tauri/React, Three.js UX)**
4. **Product Owner / QA (Генерация Specs)**

### Финансовая оценка бюджета (На 6–8 месяцев для MVP):
- **Mid-tier / Global setup:** $150,000 – $250,000 (реалистичный бюджет для крепкой remote/open-source команды).
- **Silicon Valley Style (In-house rockstars в США):** $300,000 – $600,000.
*(Включает отдельный бюджет $3000-$5000 только на API ключи GPT-4o / Claude 3.7 во время глубокой разработки и тестов).*

---

## 9. Multi-Tenant API Platform & Self-Improvement Architecture
**Ключевое отличие продукта от локальной IDE:** ForgeOS спроектирован как Development Infrastructure Layer, готовый к работе в облаке как B2B-сервис и поддерживающий безопасные механизмы самоулучшения.

### 9.1. Multi-Tenant Cloud Platform
Forge Cloud поддерживает server-hosted режим с изоляцией ресурсов (Tenant Isolation). Платформа может обслуживать сотни проектов:
- **Сущности:** Organization → Workspace → Project → Repository.
- **Разделение данных:** Отдельная память вектора, Spec файлов и контекста.
- **Provider Governance:** Каждый Tenant/Project имеет собственный whitelist провайдеров и бюджеты токенов.
- **Cost Governance Layer:** Строгий контроль рентабельности разработки: per-project token budgets, per-tenant limits, execution quotas (e.g. max 5k tasks/day), system alerts и cost-aware model routing.
- **Secrets & Credentials Model (Критично):** Встроенный Secrets Vault, per-project credentials, short-lived tokens. **LLM никогда не получает секреты в открытом виде** (доступ через tool-mediated secret use).
- **Policy Enforcement & RBAC:** Централизованный контроль того, что могут делать агенты (push, merge, commands).
- **External Telemetry Export Layer:** Нативная интеграция с OpenCloud, Datadog, Grafana через экспорт метрик разработки и агентов (OpenTelemetry traces, Metrics Export, Audit Log Export). Разделение телеметрии по Tenant-ам.
- **Audit & Compliance:** Управление ключами, квотами, биллингом и полным Audit Logging для Enterprise-клиентов.

### 9.2. Public Developer API & Connectors (Developer Platform Layer)
**Forge Development Engine** доступен как Platform as a Service (PaaS) для интеграции в сторонние CI/CD и SaaS системы.
Возможности API: 
- `create_project`, `execute_task`, `run_improvement_cycle`, `retrieve_artifacts`, `access_telemetry`.
- **Connector Priorities (MVP):** GitHub, Jira/Linear, Slack, GitHub Actions, OpenTelemetry/Sentry, Notion (Markdown export). В будущем: GitLab, Datadog, Enterprise Registries.
- **GitHub Execution Capabilities:** Движок умеет `clone`, `branch`, `commit`, `push`, открывать PR, комментировать статусы CI и прикреплять артефакты.
- **VCS Policy Modes (Контроль доступа):** 
  - *Restricted:* Только экспорт патчей (no push).
  - *Safe Mode:* Создает branch + draft PR.
  - *Supervised:* Создает PR, merge только по человеческому Approval.
  - *Trusted:* Auto-merge разрешен только для Green-zone changes.

### 9.3. Controlled Self-Improvement Loop (Самоулучшение)
ForgeOS может улучшать **сам себя**, но не через бесконтрольное рекурсивное переписывание (что ведет к краху), а через **Instrumented Recursive Improvement through Gated Releases**.
Система собирает идеи улучшений из failure logs, token overspend, UI-фрикций и bottlenecks, складывая их в `Improvement Backlog`.

#### Safe Self-Modification Rules (Risk Zones)
Любое изменение ядром самого себя проходит строгую Risk Classification:
- 🟢 **Green Zone (Auto-merge):** Документация, UI-компоненты (Game Mode Dashboards), промпты, тесты, non-critical helpers. Можно улучшать почти автоматически.
- 🟡 **Yellow Zone (PR + Full Verification):** Логика Planner/Critic, стратегии retry, rules compression. Требует прогона полного benchmark-suite.
- 🔴 **Red Zone (Human Approval Only):** Tenant isolation, Auth/Secrets, Billing, Sandbox permissions, Command Allowlist, Core Governor. **No Unbounded Recursive Self-Modification**. Система не имеет права сама ослаблять свои ограничения или менять критерии собственного допуска.

### 9.4. Release Governance
Управляемая раскатка обновлений самого себя и изоляция версий движка для B2B-клиентов:
- Поддержка **canary release, staged rollout и rollback release**.
- **Version Pinning:** Engine version per tenant/project. Клиенты не должны получать "самоулучшенную" версию движка без их ведома.

**Пример цикла:** MVP `v0.1` запускается на реальных задачах → собирает bottleneck-телеметрию → инициирует controlled self-improvement sprint → вносит оптимизации в Yellow Zone → модуль *Evaluation & Benchmark* подтверждает рост качества → выпускается Canary release `v0.2`. Цикл повторяется.
