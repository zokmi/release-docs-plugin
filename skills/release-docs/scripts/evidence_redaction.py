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
    r"(\[?(?:password|passwd|pwd|token|secret|credential|connection.?string|api.?key|"
    r"private.?key|access.?key|auth(?:orization)?|client.?secret|user(?:name)?|user[_ -]?id|uid)\]?\s*[=:]\s*)"
    r"(\"(?:\"\"|[^\"])*\"|'(?:''|[^'])*'|[^\s;&|,'\"]+)",
    re.IGNORECASE,
)
_SQL_IDENTIFIER_PART = r"(?:[A-Za-z_][A-Za-z0-9_$]*|\[(?:[^\]]|\]\])+\])"
_SQL_IDENTIFIER = re.compile(rf"{_SQL_IDENTIFIER_PART}(?:\.{_SQL_IDENTIFIER_PART})*")
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


def normalize_secrets(secrets: Iterable[str] = ()) -> tuple[str, ...]:
    """Materialize and validate secrets once for callers that reuse them."""
    return tuple(_secret_values(secrets))


def _sql_update_set_targets(text: str) -> list[bool]:
    """Mark assignment targets in lexical UPDATE ... SET code regions."""
    positions = [False] * len(text)
    i = 0
    saw_update = False
    in_set = False
    target_expected = False
    paren_depth = 0
    while i < len(text):
        if text.startswith("--", i):
            end = text.find("\n", i + 2)
            i = len(text) if end < 0 else end + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        if text[i] in "'\"":
            quote = text[i]
            i += 1
            while i < len(text):
                if text[i] == quote:
                    if i + 1 < len(text) and text[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if text[i] == "[":
            start = i
            i += 1
            while i < len(text):
                if text[i] == "]":
                    if i + 1 < len(text) and text[i + 1] == "]":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            if target_expected:
                positions[start] = True
                target_expected = False
            continue
        if text[i] == ";":
            saw_update = in_set = target_expected = False
            i += 1
            continue
        if text[i].isalpha() or text[i] == "_":
            start = i
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] in "_$"):
                i += 1
            word = text[start:i].upper()
            if word == "UPDATE":
                saw_update, in_set, target_expected = True, False, False
            elif word == "SET" and saw_update:
                in_set = True
                target_expected = True
            elif in_set and target_expected:
                positions[start] = True
                target_expected = False
            continue
        if text[i] == "(":
            paren_depth += 1
        elif text[i] == ")":
            paren_depth = max(0, paren_depth - 1)
        elif text[i] == "," and in_set and paren_depth == 0:
            target_expected = True
        elif in_set and target_expected and not text[i].isspace():
            target_expected = False
        i += 1
    return positions


def _is_sql_user_id_identifier_assignment(text: str, match: re.Match,
                                          update_set_targets: list[bool] | None = None) -> bool:
    key = match.group(1).split("=", 1)[0].split(":", 1)[0].strip().lower().strip("[]")
    value = match.group(2)
    if (key not in {"user_id", "userid", "user id"}
            or not _SQL_IDENTIFIER.fullmatch(value)):
        return False
    if update_set_targets is None:
        update_set_targets = _sql_update_set_targets(text)
    return match.start() < len(update_set_targets) and update_set_targets[match.start()]


def _redact_assignments(text: str) -> str:
    update_set_targets = _sql_update_set_targets(text)
    return _ASSIGNMENT.sub(
        lambda match: match.group(0) if _is_sql_user_id_identifier_assignment(
            text, match, update_set_targets
        )
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
            update_set_targets = _sql_update_set_targets(item)
            if any(secret in item for secret in secret_values):
                raise _fail_closed()
            if (_UNCLASSIFIED_TOKEN.search(item)
                    or _UNRECOGNIZED_CREDENTIAL_MATERIAL.search(item)
                    or _URL_CREDENTIALS.search(item)
                    or _PEM_PRIVATE_KEY.search(item)):
                raise _fail_closed()
            if (any(match.group(2).strip("\"'") != REDACTED
                    and not _is_sql_user_id_identifier_assignment(
                        item, match, update_set_targets
                    )
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
