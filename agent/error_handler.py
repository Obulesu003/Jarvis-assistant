import logging  # migrated from print()
import json
import re
import sys
from enum import Enum
from pathlib import Path

try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _get_api_key() -> str:
    if _get_gemini_key is not None:
        return _get_gemini_key()
    API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
    with open(API_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


class ErrorDecision(Enum):
    RETRY       = "retry"
    SKIP        = "skip"
    REPLAN      = "replan"
    ABORT       = "abort"


class ErrorType(Enum):
    CONNECTION  = "connection"     # Network/connection errors - RETRY
    TIMEOUT     = "timeout"        # Timeout errors - RETRY
    IMPORT      = "import"         # Import/module errors - SKIP
    PERMISSION  = "permission"     # Permission errors - ABORT
    NOT_FOUND   = "not_found"      # File/not found errors - REPLAN
    RATE_LIMIT  = "rate_limit"     # API rate limits - RETRY with backoff
    UNKNOWN     = "unknown"         # Unknown errors - REPLAN


# Rule-based error patterns for fast classification
_ERROR_PATTERNS: list[tuple[ErrorType, list[str], list[str]]] = [
    # (ErrorType, contains_patterns, startswith_patterns)
    (ErrorType.CONNECTION, [
        "connection", "connection refused", "connection reset",
        "connection timeout", "network", "no route to host",
        "unable to connect", "ECONNREFUSED", "ENOTCONN",
        "urllib.error", "requests.exceptions", "http.client",
        "remote host closed", "ssl error", "tls",
    ], [
        "HTTPSConnection", "ConnectionError", "NewConnectionError",
        "SSLError", "ProxyError", "Timeout",
    ]),
    (ErrorType.TIMEOUT, [
        "timeout", "timed out", "timed-out", "exceeded",
        "execution time", "operation timed out", "request timeout",
        "Read timed out", "ConnectTimeoutError",
    ], [
        "TimeoutError", "TimeoutExpired", "PlaywrightTimeout",
        "asyncio.TimeoutError",
    ]),
    (ErrorType.IMPORT, [
        "importerror", "modulenotfounderror", "no module named",
        "cannot import", "import failed", "no attribute",
        "attributeerror", "has no attribute",
        "modulenotfound", "undefined name",
    ], [
        "ImportError", "ModuleNotFoundError", "AttributeError",
    ]),
    (ErrorType.PERMISSION, [
        "permission denied", "access denied", "forbidden",
        "unauthorized", "elevation required", "admin required",
        "not permitted", "require administrator",
        "errno 13", "errno 1", "win32api",
    ], [
        "PermissionError", "AccessDeniedError",
    ]),
    (ErrorType.NOT_FOUND, [
        "not found", "no such file", "does not exist",
        "file not found", "directory not found", "path not found",
        "cannot find", "no such path", "enoent", "errno 2",
        "target page", "page not found", "404",
    ], [
        "FileNotFoundError", "IsADirectoryError", "NotADirectoryError",
    ]),
    (ErrorType.RATE_LIMIT, [
        "rate limit", "too many requests", "quota exceeded",
        "429", "503", "service unavailable", "back off",
        "throttl", "retry after",
    ], [
        "RateLimitError", "TooManyRequests",
    ]),
]


def _get_error_type(error_msg: str) -> ErrorType:
    """
    Classify an error message into an ErrorType using pattern matching.
    This provides fast, rule-based classification without LLM overhead.
    """
    error_lower = error_msg.lower()

    for error_type, contains_patterns, startswith_patterns in _ERROR_PATTERNS:
        # Check contains patterns
        for pattern in contains_patterns:
            if pattern.lower() in error_lower:
                return error_type

        # Check startswith patterns
        for pattern in startswith_patterns:
            if error_msg.startswith(pattern):
                return error_type

    return ErrorType.UNKNOWN


# Decision mapping based on error type
_ERROR_DECISIONS: dict[ErrorType, dict] = {
    ErrorType.CONNECTION: {
        "decision": ErrorDecision.RETRY,
        "max_retries": 2,
        "user_message": "Connection issue, retrying, sir.",
        "fix_suggestion": "Check network connectivity and try again",
    },
    ErrorType.TIMEOUT: {
        "decision": ErrorDecision.RETRY,
        "max_retries": 1,
        "user_message": "Request timed out, trying again, sir.",
        "fix_suggestion": "Increase timeout or simplify the request",
    },
    ErrorType.IMPORT: {
        "decision": ErrorDecision.SKIP,
        "max_retries": 0,
        "user_message": "A module issue occurred, skipping this step, sir.",
        "fix_suggestion": "The required module is not available, skip and continue",
    },
    ErrorType.PERMISSION: {
        "decision": ErrorDecision.ABORT,
        "max_retries": 0,
        "user_message": "Permission denied, cannot continue, sir.",
        "fix_suggestion": "Run with elevated privileges or adjust permissions",
    },
    ErrorType.NOT_FOUND: {
        "decision": ErrorDecision.REPLAN,
        "max_retries": 0,
        "user_message": "Resource not found, trying a different approach, sir.",
        "fix_suggestion": "Search for the file/resource in alternative locations",
    },
    ErrorType.RATE_LIMIT: {
        "decision": ErrorDecision.RETRY,
        "max_retries": 3,
        "user_message": "Rate limited, waiting before retry, sir.",
        "fix_suggestion": "Add delay between requests and reduce frequency",
    },
    ErrorType.UNKNOWN: {
        "decision": ErrorDecision.REPLAN,
        "max_retries": 0,
        "user_message": "An issue occurred, adjusting approach, sir.",
        "fix_suggestion": "Try a different method or tool",
    },
}


ERROR_ANALYST_PROMPT = """You are the error recovery module of MARK XXV AI assistant.

A task step has failed. Analyze the error and decide what to do.

DECISIONS:
- retry   : Transient error (network timeout, temporary file lock, race condition).
             The same step can succeed if tried again.
- skip    : This step is not critical and the task can succeed without it.
- replan  : The approach was wrong. A different tool or method should be tried.
- abort   : The task is fundamentally impossible or unsafe to continue.

Also provide:
- A brief explanation of WHY it failed (1 sentence)
- A fix suggestion if decision is replan (what to try instead)
- Max retries: how many times to retry if decision is retry (1 or 2)

Return ONLY valid JSON:
{
  "decision": "retry|skip|replan|abort",
  "reason": "why it failed",
  "fix_suggestion": "what to try instead (for replan)",
  "max_retries": 1,
  "user_message": "Short message to tell the user (max 15 words)"
}
"""


def analyze_error(
    step: dict,
    error: str,
    attempt: int = 1,
    max_attempts: int = 2
) -> dict:
    """
    Analyzes a failed step and returns a recovery decision.
    Uses rule-based classification for fast decisions, with LLM as fallback.

    Args:
        step         : The step dict that failed
        error        : Error message/traceback
        attempt      : Current attempt number
        max_attempts : How many times we've already tried

    Returns:
        {
            "decision": ErrorDecision,
            "reason": str,
            "fix_suggestion": str,
            "max_retries": int,
            "user_message": str
        }
    """
    # Fast rule-based classification first
    error_type = _get_error_type(error)
    rule_decision = _ERROR_DECISIONS.get(error_type, _ERROR_DECISIONS[ErrorType.UNKNOWN])

    if attempt >= max_attempts:
        logging.getLogger("ErrorHandler").warning("Max attempts reached for step {step.get('step')} -- forcing replan")
        return {
            "decision":      ErrorDecision.REPLAN,
            "reason":        f"Failed {attempt} times: {error[:100]}",
            "fix_suggestion": "Try a completely different approach or tool",
            "max_retries":   0,
            "user_message":  "Trying a different approach, sir."
        }

    # For connection/timeout/rate_limit errors, use rule-based decision immediately
    if error_type in (ErrorType.CONNECTION, ErrorType.TIMEOUT, ErrorType.RATE_LIMIT):
        logging.getLogger("ErrorHandler").info("{error_type.value} error detected -- {rule_decision['decision'].value}")
        # Still allow retries for these error types
        if attempt <= rule_decision.get("max_retries", 1):
            return {
                "decision":      rule_decision["decision"],
                "reason":        f"{error_type.value}: {error[:100]}",
                "fix_suggestion": rule_decision.get("fix_suggestion", ""),
                "max_retries":   rule_decision.get("max_retries", 1) - attempt,
                "user_message":  rule_decision.get("user_message", "Retrying, sir.")
            }

    # For critical errors (permission), abort immediately
    if error_type == ErrorType.PERMISSION:
        logging.getLogger("ErrorHandler").info('{error_type.value} error detected -- ABORT')
        return {
            "decision":      ErrorDecision.ABORT,
            "reason":        f"{error_type.value}: {error[:100]}",
            "fix_suggestion": rule_decision.get("fix_suggestion", ""),
            "max_retries":   0,
            "user_message":  rule_decision.get("user_message", "Permission denied, sir.")
        }

    # For import errors, skip immediately
    if error_type == ErrorType.IMPORT:
        logging.getLogger("ErrorHandler").info('{error_type.value} error detected -- SKIP')
        return {
            "decision":      ErrorDecision.SKIP,
            "reason":        f"{error_type.value}: {error[:100]}",
            "fix_suggestion": rule_decision.get("fix_suggestion", ""),
            "max_retries":   0,
            "user_message":  rule_decision.get("user_message", "Skipping step, sir.")
        }

    # For not_found errors, replan immediately
    if error_type == ErrorType.NOT_FOUND:
        logging.getLogger("ErrorHandler").info('{error_type.value} error detected -- REPLAN')
        return {
            "decision":      ErrorDecision.REPLAN,
            "reason":        f"{error_type.value}: {error[:100]}",
            "fix_suggestion": rule_decision.get("fix_suggestion", "Search for the file in alternative locations"),
            "max_retries":   0,
            "user_message":  rule_decision.get("user_message", "Resource not found, sir.")
        }

    # Fallback to LLM analysis for unknown/complex errors
    from google.genai import Client
    from google.genai.types import GenerateContentConfig

    client = Client(api_key=_get_api_key())

    prompt = f"""Failed step:
Tool: {step.get('tool')}
Description: {step.get('description')}
Parameters: {json.dumps(step.get('parameters', {}), indent=2)}
Critical: {step.get('critical', False)}

Error:
{error[:500]}

Attempt number: {attempt}"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=GenerateContentConfig(system_instruction=ERROR_ANALYST_PROMPT)
        )
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        result = json.loads(text)
        decision_str = result.get("decision", "replan").lower()
        decision_map = {
            "retry":  ErrorDecision.RETRY,
            "skip":   ErrorDecision.SKIP,
            "replan": ErrorDecision.REPLAN,
            "abort":  ErrorDecision.ABORT,
        }
        result["decision"] = decision_map.get(decision_str, ErrorDecision.REPLAN)


        if step.get("critical") and result["decision"] == ErrorDecision.SKIP:
            result["decision"]     = ErrorDecision.REPLAN
            result["user_message"] = "This step is critical -- finding alternative approach, sir."

        logging.getLogger("ErrorHandler").info("Decision: {result['decision'].value} -- {result.get('reason', '')}")
        return result

    except Exception as e:
        logging.getLogger("ErrorHandler").warning('Analysis failed: {e} -- defaulting to rule-based')
        return {
            "decision":       ErrorDecision.REPLAN,
            "reason":         str(e),
            "fix_suggestion": "Try alternative approach",
            "max_retries":    1,
            "user_message":   "Encountered an issue, adjusting approach, sir."
        }


def generate_fix(step: dict, error: str, fix_suggestion: str) -> dict:
    """
    When decision is REPLAN and a fix suggestion exists,
    generates a replacement step using generated_code as fallback.

    Returns a modified step dict.
    """
    from google.genai import Client

    client = Client(api_key=_get_api_key())

    prompt = f"""A task step failed. Generate a replacement step.

Original step:
Tool: {step.get('tool')}
Description: {step.get('description')}
Parameters: {json.dumps(step.get('parameters', {}), indent=2)}

Error: {error[:300]}
Fix suggestion: {fix_suggestion}

Write a Python script that accomplishes the same goal differently.
Return ONLY the Python code, no explanation."""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        return {
            "step":        step.get("step"),
            "tool":        "code_helper",
            "description": f"Auto-fix for: {step.get('description')}",
            "parameters": {
                "action":      "run",
                "description": fix_suggestion,
                "code":        code,
                "language":    "python"
            },
            "depends_on": step.get("depends_on", []),
            "critical":   step.get("critical", False)
        }

    except Exception as e:
        logging.getLogger("ErrorHandler").warning(f'️ Fix generation failed: {e}')
        return {
            "step":        step.get("step"),
            "tool":        "generated_code",
            "description": f"Fallback for: {step.get('description')}",
            "parameters":  {"description": step.get("description", "")},
            "depends_on":  step.get("depends_on", []),
            "critical":    step.get("critical", False)
        }
