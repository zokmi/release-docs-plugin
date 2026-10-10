"""Validate an explicit source review against current, non-circular evidence identity."""
import json
import re
from validate_release_output import (_approved_provider_body, _finding as domain_finding,
                                     lifecycle_root, plain_path)
from assemble_deployment_sql import _lex

CHECKS = {'definition', 'preconditions', 'rerun', 'dependencies', 'preservation'}
CONCLUSIONS = {'passed', 'pending', 'failed'}


def _finding(code='semantic_review_pending', failed=False):
    return domain_finding('semantic_sql_defect' if failed else code, blocking=failed)


def classify_data_impact(unit: dict) -> str:
    """Classify pinned execution SQL; names, phases and unproved labels are not evidence."""
    if not isinstance(unit, dict):
        return 'unknown'
    definition = unit.get('target_definition')
    sql = unit.get('sql', definition.get('sql') if isinstance(definition, dict) else None)
    if not isinstance(sql, str) or not sql.strip():
        return 'unknown'
    code, malformed = _lex(sql)
    if malformed:
        return 'unknown'
    # FK referential actions describe a constraint, not a current row mutation.
    code = re.sub(r'\bON\s+(?:DELETE|UPDATE)\s+(?:CASCADE|NO\s+ACTION|SET\s+(?:NULL|DEFAULT))\b', '', code)
    if (re.search(r'\b(?:UPDATE|DELETE|MERGE|TRUNCATE)\b|\bDROP\s+TABLE\b', code)
            or re.search(r'\bALTER\s+TABLE\b[^;]*(?:\b(?:ALTER|DROP)\s+COLUMN\b|\bWITH\s+VALUES\b)', code)):
        return 'mutation'
    provider = _approved_provider_body(unit, sql)
    if re.search(r'\bEXEC(?:UTE)?\b', code):
        if not provider:
            return 'unknown'
        code = re.sub(r'\bEXEC(?:UTE)?\b[^;\n]*(?:;|$)', '', code, flags=re.M)
    if re.search(r'\b(?:INSERT|INTO|BULK|DBCC|BACKUP|RESTORE|GRANT|REVOKE|DENY|OPENROWSET|OPENQUERY)\b', code):
        return 'unknown'
    for statement in code.split(';'):
        leader = re.match(r'\s*([A-Z_]+)', statement)
        if leader and leader[1] not in {'CREATE', 'ALTER', 'SELECT', 'IF', 'BEGIN', 'END',
                                       'ELSE', 'DECLARE', 'SET', 'THROW', 'PRINT'}:
            return 'unknown'
    operations = list(re.finditer(r'\b(?:CREATE|ALTER|DROP)\b', code))
    for operation in operations:
        tail = code[operation.start():]
        if not re.match(r'(?:CREATE\s+(?:TABLE\b|(?:UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?INDEX\b)'
                        r'|ALTER\s+TABLE\b[^;]*?\b(?:ADD|DROP\s+CONSTRAINT)\b)', tail):
            return 'unknown'
    return 'non_mutating' if operations or provider or re.search(r'\bSELECT\b', code) else 'unknown'


def _no_existing_row_mutation(reason):
    return bool(re.search(r'無既有資料列異動|no existing (?:persistent )?rows? mutations?'
                          r'|does not modify existing (?:persistent )?rows',
                          reason.replace('-', ' '), re.I))


def _preservation(check, unit, impact):
    if not isinstance(check, dict) or not isinstance(check.get('reason'), str) or not check['reason'].strip():
        return False
    conclusion, reason = check.get('conclusion'), check['reason']
    if impact == 'non_mutating' and conclusion in ('passed', 'N/A'):
        path, line = unit.get('source_path'), unit.get('source_line')
        located = (isinstance(path, str) and type(line) is int and line > 0
                   and re.search(re.escape(f'{path}:{line}') + r'(?!\d)', reason))
        provider = unit.get('provider_kind')
        described = (isinstance(provider, str) and provider in reason
                     and 'provider' in reason.lower())
        return _no_existing_row_mutation(reason) and (located or described)
    return _review(check) and not (impact == 'mutation' and (
        _no_existing_row_mutation(reason) or re.search(r'\bN/A\b', reason, re.I)))


def _review(value):
    return (isinstance(value, dict) and value.get('conclusion') in CONCLUSIONS
            and isinstance(value.get('reason'), str) and bool(value['reason'].strip()))


def validate_semantic_review(record, source, exclusions, fingerprint_sha256):
    if (not isinstance(record, dict) or record.get('schema_version') != 1
            or not re.fullmatch(r'[0-9a-f]{64}', str(fingerprint_sha256))
            or record.get('evidence_fingerprint') != fingerprint_sha256
            or not isinstance(record.get('method'), str) or not record['method'].strip()
            or record.get('conclusion') not in CONCLUSIONS
            or not isinstance(record.get('unresolved'), list)):
        return [_finding()]
    if not _review(record.get('scope_review')) or not _review(record.get('parameter_review')):
        return [_finding()]
    units = source.get('units')
    reviews = record.get('unit_reviews')
    if not isinstance(units, list) or not isinstance(reviews, list):
        return [_finding()]
    excluded = {uid for entry in exclusions for uid in entry['unit_ids']}
    included = {u['unit_id']: u for u in units if isinstance(u, dict) and u.get('unit_id') not in excluded}
    ids = [item.get('unit_id') for item in reviews if isinstance(item, dict)]
    if len(ids) != len(reviews) or any(not isinstance(uid, str) for uid in ids):
        return [_finding()]
    if len(ids) != len(set(ids)) or set(ids) != set(included):
        return [_finding()]
    conclusions = [record['conclusion'], record['scope_review']['conclusion'], record['parameter_review']['conclusion']]
    for item in reviews:
        unit = included[item['unit_id']]
        impact = classify_data_impact(unit)
        if (any(item.get(k) != unit.get(k) or not isinstance(item.get(k), str) or not item[k]
                for k in ('source_path', 'source_revision', 'source_hash'))
                or item.get('conclusion') not in CONCLUSIONS
                or not isinstance(item.get('checks'), dict) or set(item['checks']) != CHECKS
                or not all(_review(check) for name, check in item['checks'].items() if name != 'preservation')
                or not _preservation(item['checks']['preservation'], unit, impact)):
            return [_finding()]
        conclusions.append(item['conclusion'])
        conclusions.extend('passed' if check['conclusion'] == 'N/A' else check['conclusion']
                           for check in item['checks'].values())
        if impact == 'unknown':
            conclusions.append('pending')
    if 'failed' in conclusions:
        return [_finding(failed=True)]
    business = [entry for entry in record['unresolved'] if isinstance(entry, dict)
                and entry.get('domain') == 'business_data_validation'
                and isinstance(entry.get('reason'), str) and entry['reason'].strip()
                and isinstance(entry.get('code', 'business_data_validation'), str)
                and domain_finding(entry.get('code', 'business_data_validation'),
                                   domain=entry['domain'])['domain'] == 'business_data_validation']
    findings = [domain_finding('business_data_validation', domain='business_data_validation')] if business else []
    if len(business) != len(record['unresolved']) or 'pending' in conclusions:
        findings.append(_finding())
    return findings


def write_semantic_review(run_root, record):
    run = lifecycle_root(run_root)
    if not isinstance(record, dict) or record.get('schema_version') != 1:
        raise ValueError('Invalid semantic review schema')
    path = plain_path(run / 'semantic_review_record.json')
    data = (json.dumps(record, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode()
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('Semantic review evidence is immutable; create a new run')
    else:
        with path.open('xb') as stream:
            stream.write(data)
    return path
