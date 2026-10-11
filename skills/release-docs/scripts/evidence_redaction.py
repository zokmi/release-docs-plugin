"""Shared fail-closed redaction for durable release evidence."""
from __future__ import annotations

import re
from typing import Any, Iterable


REDACTED = "[REDACTED]"
_SENSITIVE = re.compile(
    r"(?:^|[^A-Za-z])(?:password|passwd|pwd|token|secret|credential|connection.?string|"
    r"api.?key|private.?key|access.?key|auth(?:orization)?|client.?secret|"
    r"user(?:[_ -]?(?:name|id))?|uid)(?:$|[^A-Za-z])", re.IGNORECASE,
)
_ASSIGNMENT = re.compile(
    r"((?:password|passwd|pwd|token|secret|credential|connection.?string|api.?key|"
    r"private.?key|access.?key|client.?secret|user(?:name)?|user[_ -]?id|uid)\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s;&|,]+)",
    re.IGNORECASE,
)
_SQL_UPDATE_SET = re.compile(r"\bUPDATE\b[\s\S]*\bSET\b[^;]*$", re.IGNORECASE)
_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*")
_URL_CREDENTIALS = re.compile(r"(https?://)[^\s/@]+:[^\s/@]+@", re.IGNORECASE)
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER = re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_UNCLASSIFIED_TOKEN = re.compile(
    r"\b(?:sk|rk|pk|ghp|gho|ghu|ghs|github_pat|xox[baprs])-"
    r"[A-Za-z0-9_-]{12,}\b", re.IGNORECASE,
)
_UNRECOGNIZED_CREDENTIAL_MATERIAL = re.compile(
    r"\bcredential\s+material\s*[:=]\s*(?!\[REDACTED\])[^\s;&|,]+", re.IGNORECASE,
)
_FLAG = re.compile(
    r"^(?:--?|/)(?:password|passwd|pwd|token|secret|api[-_]?key|user(?:name)?|uid|"
    r"credential|connection[-_]?string|private[-_]?key|access[-_]?key|p|u)$",
    re.IGNORECASE,
)
_COMMAND_ARGUMENT = re.compile(
    r"((?:--?(?:password|passwd|pwd|token|secret|api[-_]?key|user(?:name)?|uid|p|u)|"
    r"/(?:password|passwd|pwd|token|secret|api[-_]?key|user(?:name)?|uid))\s+)"
    r"(\"[^\"]*\"|'[^']*'|[^\s]+)", re.IGNORECASE,
)


def _fail_closed() -> ValueError:
    return ValueError("secret_redaction_required")


def _secret_values(secrets: Iterable[str]) -> list[str]:
    if isinstance(secrets, str):
        secrets = (secrets,)
    try:
        values = list(secrets)
    except TypeError as exc:
        raise _fail_closed() from exc
    if any(not isinstance(secret, str) or not secret for secret in values):
        raise _fail_closed()
    return sorted(set(values), key=len, reverse=True)


def _is_sql_user_id_identifier_assignment(text: str, match: re.Match) -> bool:
    key = match.group(1).split("=", 1)[0].split(":", 1)[0].strip().lower()
    value = match.group(2).strip("\"'")
    if key not in {"user_id", "userid", "user id"} or not _SQL_IDENTIFIER.fullmatch(value):
        return False
    statement_start = max(text.rfind(";", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
    preceding = text[statement_start:match.start()]
    if re.search(r"--|/\*", preceding):
        return False
    return _SQL_UPDATE_SET.search(preceding) is not None


def _redact_assignments(text: str) -> str:
    return _ASSIGNMENT.sub(
        lambda match: match.group(0) if _is_sql_user_id_identifier_assignment(text, match)
        else match.group(1) + REDACTED,
        text,
    )


def _redact_text(value: str, secrets: list[str]) -> str:
    text = value
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    text = _PEM_PRIVATE_KEY.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(r"\1" + REDACTED + "@", text)
    text = _redact_assignments(text)
    text = _BEARER.sub(lambda match: match.group(1) + REDACTED, text)
    text = _COMMAND_ARGUMENT.sub(lambda match: match.group(1) + REDACTED, text)
    if (_UNCLASSIFIED_TOKEN.search(text)
            or _UNRECOGNIZED_CREDENTIAL_MATERIAL.search(text)):
        raise _fail_closed()
    return text


def redact_text(value: str, secrets: Iterable[str] = ()) -> str:
    """Redact recognizable credentials or fail without echoing unsafe input."""
    return _redact_text(str(value), _secret_values(secrets))


def _redact(value: Any, secrets: list[str], *, command=False):
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, list):
        result = []
        redact_next = False
        for item in value:
            if redact_next:
                result.append(REDACTED)
                redact_next = False
                continue
            cleaned = _redact(item, secrets)
            result.append(cleaned)
            redact_next = isinstance(item, str) and bool(_FLAG.fullmatch(item.strip()))
        return result
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _fail_closed()
            clean_key = _redact_text(key, secrets)
            if _SENSITIVE.search(key):
                cleaned = REDACTED
            else:
                cleaned = _redact(item, secrets, command=key.lower() == "command")
            result[clean_key] = cleaned
        return result
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _fail_closed()
        return value
    raise _fail_closed()


def redact_mapping(value: Any, secrets: Iterable[str] = ()) -> dict | list:
    """Recursively sanitize JSON evidence, including argv-style commands."""
    if not isinstance(value, (dict, list)):
        raise _fail_closed()
    clean = _redact(value, _secret_values(secrets))
    assert_safe_evidence(clean, secrets=secrets)
    return clean


def assert_safe_evidence(value: Any, secrets: Iterable[str] = ()) -> None:
    """Reject credential-like material that remains after redaction."""
    secret_values = _secret_values(secrets)

    def visit(item):
        if isinstance(item, str):
            if any(secret in item for secret in secret_values):
                raise _fail_closed()
            if (_UNCLASSIFIED_TOKEN.search(item)
                    or _UNRECOGNIZED_CREDENTIAL_MATERIAL.search(item)
                    or _URL_CREDENTIALS.search(item)
                    or _PEM_PRIVATE_KEY.search(item)):
                raise _fail_closed()
            if (any(match.group(2).strip("\"'") != REDACTED
                    and not _is_sql_user_id_identifier_assignment(item, match)
                    for match in _ASSIGNMENT.finditer(item))
                    or any(match.group(2).strip("\"'") != REDACTED
                           for match in _COMMAND_ARGUMENT.finditer(item))
                    or _BEARER.search(item)):
                raise _fail_closed()
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise _fail_closed()
                visit(key)
                if _SENSITIVE.search(key) and child not in (REDACTED, None):
                    raise _fail_closed()
                visit(child)
        elif isinstance(item, list):
            redact_next = False
            for child in item:
                if redact_next:
                    if child != REDACTED:
                        raise _fail_closed()
                    redact_next = False
                    continue
                visit(child)
                redact_next = isinstance(child, str) and bool(_FLAG.fullmatch(child.strip()))
            if redact_next:
                raise _fail_closed()
        elif item is None or isinstance(item, (bool, int, float)):
            return
        else:
            raise _fail_closed()

    visit(value)
