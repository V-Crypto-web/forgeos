import re

class SecretRedactor:
    """
    Module 8 (Security): Secrets Vault Layer.
    Intercepts and redacts sensitive credentials from being leaked to upstream LLM API providers.
    Uses regex and entropy heuristics.
    """
    
    # Standard patterns for common API keys and tokens
    PATTERNS = {
        "OPENAI_API_KEY": r"(sk-[a-zA-Z0-9]{48})",
        "ANTHROPIC_API_KEY": r"(sk-ant-[a-zA-Z0-9-_]+)",
        "AWS_ACCESS_KEY_ID": r"(?<![A-Z0-9])([A-Z0-9]{20})(?![A-Z0-9])",
        "AWS_SECRET_ACCESS_KEY": r"(?<![A-Za-z0-9/+=])([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])",
        "GITHUB_TOKEN": r"(gh[p|o|u|s|r]_[a-zA-Z0-9]{36})",
        "SLACK_TOKEN": r"(xox[baprs]-[a-zA-Z0-9]+)",
        "GENERIC_BEARER": r"(?i)bearer\s+([a-zA-Z0-9-_\.]+)",
        "GENERIC_JWT": r"(eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)"
    }

    @classmethod
    def redact(cls, text: str) -> str:
        """
        Scans text and replaces any detected secrets with a REDACTED placeholder.
        """
        if not text:
            return text
            
        redacted_text = text
        for token_type, pattern in cls.PATTERNS.items():
            # Replace match with a specific redacted tag
            redacted_text = re.sub(pattern, f"[REDACTED_{token_type}]", redacted_text)
            
        return redacted_text
