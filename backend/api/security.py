"""
Input security guards for user-submitted text.

Two threat vectors are blocked:
1. Code injection — attempts to smuggle executable code into the pipeline.
2. Architecture probing — attempts to extract system internals, credentials,
   or configuration through the chat/topic interface.

These checks run at the API boundary before any LLM or database call.
"""

import re
from fastapi import HTTPException, status

# ── Code injection patterns ───────────────────────────────────────────────────
# Anchored or context-sensitive to avoid false positives on natural language.

_CODE_REGEXES: list[re.Pattern] = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in [
    r"^[ \t]*(def |async def )\s*\w+\s*\(",            # Python function def
    r"^[ \t]*class\s+\w+[\s(:]",                       # Python/JS class
    r"^[ \t]*(import |from \w+ import )\w+",           # Python import statement
    r"\b(require|import)\s*\(\s*['\"]",                # JS require/import
    r"\b(exec|eval)\s*\(",                             # exec() / eval()
    r"\bsubprocess\.(run|Popen|call|check_output)\b",  # subprocess
    r"\bos\.(system|popen|execv|execvp)\b",            # os shell calls
    r"__import__\s*\(",                                # Python import hack
    r"(?i)\bSELECT\b.{1,80}\bFROM\b",                # SQL SELECT
    r"(?i)\b(INSERT\s+INTO|DROP\s+TABLE|ALTER\s+TABLE|CREATE\s+TABLE)\b",  # SQL DML/DDL
    r"```\s*\w*\s*\n.+```",                           # fenced code block
    r"<script[\s>]",                                   # script tag
    r"\bfetch\s*\(\s*['\"]https?://",                 # JS fetch with URL
    r"\bxmlhttprequest\b",                             # XHR
    r"\bcurl\s+-",                                     # curl with flags
]]

# ── Architecture probing patterns ─────────────────────────────────────────────

_PROBE_REGEXES: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    r"\bsystem\s+prompt\b",
    r"\byour\s+instructions\b",
    r"\bignore\s+(previous|above|prior|all)\b",
    r"\bdisregard\s+(previous|above|prior|all)\b",
    r"\bprompt\s+injection\b",
    r"\bjailbreak\b",
    r"\bbypass\s+(your|the)\s+(rules|instructions|restrictions)\b",
    r"\b(api[\s_-]?key|secret[\s_-]?key|jwt[\s_-]?secret|access[\s_-]?token)\b",
    r"\benvironment\s+variable\b",
    r"\b\.env\b",
    r"\bdatabase\s+(password|credentials|schema|connection|url)\b",
    r"\b(postgres|postgresql|sqlite)\s+(url|dsn|connection)\b",
    r"\bsource\s+code\b",
    r"\bhow\s+(is|does|are)\s+(the\s+)?(backend|server|pipeline|app|api)\s+(set\s+up|work|configured|built)\b",
    r"\bwhat\s+(model|llm|ai\s+model)\s+(are\s+you|is\s+used|powers)\b",
    r"\breveal\s+(your|the)\s+(prompt|instructions|config|key|secret)\b",
    r"\binternal\s+(architecture|implementation|config|database)\b",
    r"\banthrop(ic)?\s+api\b",
    r"\bdocker\s+(compose|file|container|image)\b",
]]


def validate_user_input(text: str, field: str = "input") -> None:
    """
    Validate that user-supplied text does not contain code or architecture probes.

    Args:
        text:  The raw user input string.
        field: Name of the field (used in error messages).

    Raises:
        HTTPException 422 if code is detected.
        HTTPException 403 if architecture probing is detected.
    """
    if not text or not text.strip():
        return

    for pattern in _CODE_REGEXES:
        if pattern.search(text):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid {field}: programming code is not accepted as input.",
            )

    for pattern in _PROBE_REGEXES:
        if pattern.search(text):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Invalid {field}: requests about system internals, "
                    "credentials, or application architecture are not permitted."
                ),
            )


def validate_topic(topic: str) -> str:
    """
    Pydantic-compatible validator for StoryCreate.topic.
    Raises ValueError (converted to 422 by FastAPI) on violations.
    """
    for pattern in _CODE_REGEXES:
        if pattern.search(topic):
            raise ValueError("Programming code is not accepted as a story topic.")
    for pattern in _PROBE_REGEXES:
        if pattern.search(topic):
            raise ValueError(
                "Requests about system internals or architecture are not permitted as a story topic."
            )
    return topic
