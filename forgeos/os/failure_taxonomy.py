from enum import Enum

class FailureCategory(str, Enum):
    """
    Standardized taxonomy of execution failures.
    Allows the Engine to understand *why* a run failed, rather than just knowing it failed.
    """
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"      # OS level, missing packages, bad path
    DEPENDENCY_CONFLICT = "DEPENDENCY_CONFLICT"      # pip/poetry install failed, ModuleNotFoundError
    TEST_SELECTION_FAILURE = "TEST_SELECTION_FAILURE" # Elected to run tests that don't exist
    PATCH_REGRESSION = "PATCH_REGRESSION"            # Introduced a bug or failed existing test
    NONDETERMINISM = "NONDETERMINISM"                # Flaky test (succeeded then failed)
    SYNTAX_ERROR = "SYNTAX_ERROR"                    # Invalid Python/JSON syntax in the patch
    CONTEXT_FAILURE = "CONTEXT_FAILURE"              # Max tokens exceeded, context dropped
    UNKNOWN = "UNKNOWN"

class FailureTaxonomyEngine:
    """
    Module 13: Failure Taxonomy (Execution OS Layer)
    Categorizes the reason a task attempt failed based on test output,
    lint errors, or environmental crash logs.
    """
    @staticmethod
    def classify_error(error_output: str, command: str) -> FailureCategory:
        error_lower = error_output.lower()
        command_lower = command.lower()
        
        if "modulenotfounderror" in error_lower or "importerror" in error_lower:
            return FailureCategory.DEPENDENCY_CONFLICT
            
        if "syntaxerror" in error_lower or "indentationerror" in error_lower:
            return FailureCategory.SYNTAX_ERROR
            
        if "command not found" in error_lower or "no such file or directory" in error_lower:
            # Differentiate between a test file missing and a global command missing
            if "pytest" in command_lower and "no such file" in error_lower:
                return FailureCategory.TEST_SELECTION_FAILURE
            return FailureCategory.ENVIRONMENT_FAILURE
            
        if "pytest" in command_lower and ("failed" in error_lower or "error" in error_lower):
            return FailureCategory.PATCH_REGRESSION
            
        return FailureCategory.UNKNOWN
