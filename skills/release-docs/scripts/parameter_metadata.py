"""Bounded, redacted parameter descriptors shared by persistence and rendering."""
import re

SENSITIVE = re.compile(r'password|passwd|pwd|token|secret|credential|connection.?string|api.?key|private.?key', re.I)
FIELDS = ('environment', 'service', 'key', 'format_example', 'apply', 'reload',
          'validation', 'sensitive', 'source_reference')


def redact_text(value, secrets=()):
    text = str(value)
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', text, flags=re.I)
    return re.sub(r'((?:' + SENSITIVE.pattern + r')\s*[=:]\s*)(?:"[^"]*"|\'[^\']*\'|[^\s;&|]+)',
                  r'\1[REDACTED]', text, flags=re.I)


def sanitize_parameter_changes(changes):
    if not isinstance(changes, list):
        raise ValueError('Parameter changes must be explicit descriptors')
    secrets = set()
    for item in changes:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip()
                                            for k in ('environment', 'service', 'key')):
            raise ValueError('Parameter scope is incomplete')
        if SENSITIVE.search(item['key']) or item.get('sensitive') is True:
            secrets.update(item[k] for k in ('value', 'raw_value', 'old_value', 'new_value', 'format_example')
                           if isinstance(item.get(k), str) and item[k])
    result = []
    for item in changes:
        clean = {key: redact_text(item[key], secrets) for key in FIELDS
                 if key in item and key != 'sensitive'}
        clean['sensitive'] = bool(SENSITIVE.search(item['key']) or item.get('sensitive') is True)
        if clean['sensitive']:
            clean['format_example'] = '字串，例如 [REDACTED]（由機密儲存取得）'
        result.append(clean)
    return result
