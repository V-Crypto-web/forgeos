import re

class DocRetriever:
    """
    Module 9 (Intelligence): Doc Retriever Agent.
    Analyzes the issue text and attempts to fetch contextual documentation snippets
    for relevant libraries (FastAPI, Pydantic, SQLAlchemy, etc).
    """
    
    # Very basic static mock knowledge base for MVP
    # In a real system, this would call Tavily API or a local Qdrant Vector DB
    MOCK_KNOWLEDGE_BASE = {
        "fastapi": "FastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.8+ based on standard Python type hints. Key concepts: APIRouter, Depends, HTTPException.",
        "pydantic": "Pydantic v2 uses `model_validator` instead of `root_validator`. `BaseModel` requires `model_config` instead of `Config` class. Field types are enforced strictly.",
        "sqlalchemy": "SQLAlchemy 2.0 uses `select()` instead of `query()`. Execution is done via `Session.execute(stmt)`. Models should inherit from `DeclarativeBase`.",
        "litellm": "LiteLLM uses `completion(model='...', messages=[...])`. The response object contains `choices[0].message.content` and `usage` for prompt/completion tokens.",
        "pytest": "Pytest uses `assert` statements. Fixtures are defined with `@pytest.fixture`. Async tests require `pytest_asyncio` and `@pytest.mark.asyncio`.",
        "react": "React 18 uses `createRoot`. Hooks include `useState` and `useEffect`. Don't mutate state directly.",
        "threejs": "Three.js core components: Scene, Camera, WebGLRenderer. Objects are Meshes (Geometry + Material). Requires an animation loop `requestAnimationFrame`.",
        "marshmallow": "Marshmallow uses `Schema` with fields like `fields.String()`, `fields.Integer()`. Deserialization via `schema.load()`, serialization via `schema.dump()`.",
        "flask": "Flask uses `app.route()` or `Blueprint`. Request data accessed via `request.json` or `request.form`. Context locals include `g`, `current_app`, `request`, `session`.",
        "click": "Click uses `@click.command()`, `@click.option()`, `@click.argument()`. Context can be passed via `@click.pass_context`.",
        "starlette": "Starlette is a lightweight ASGI framework. Core primitives: `Request`, `Response`, `WebSocket`. Routing via `Router`, `Route`, `Mount`."
    }
    
    def __init__(self):
        # List of keywords to detect in issue descriptions
        self.library_keywords = list(self.MOCK_KNOWLEDGE_BASE.keys())

    def retrieve_context(self, issue_text: str) -> str:
        """
        Extracts library names from the issue text and fetches documentation excerpts.
        """
        if not issue_text:
            return ""
            
        detected_libraries = []
        text_lower = issue_text.lower()
        
        for lib in self.library_keywords:
            if re.search(r'\b' + lib + r'\b', text_lower):
                detected_libraries.append(lib)
                
        if not detected_libraries:
            return ""
            
        context_snippets = []
        for lib in detected_libraries:
            snippet = self.MOCK_KNOWLEDGE_BASE.get(lib)
            if snippet:
                context_snippets.append(f"### {lib.upper()} Context:\n{snippet}")
                
        if context_snippets:
            header = "=== EXTERNAL LIBRARY DOCUMENTATION ===\n"
            return header + "\n\n".join(context_snippets) + "\n"
        
        return ""
