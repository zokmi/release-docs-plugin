"""Validate an explicit source review against current, non-circular evidence identity."""
import json
import re
from validate_release_output import lifecycle_root, plain_path

CHECKS = {'definition', 'preconditions', 'rerun', 'dependencies', 'preservation'}
CONCLUSIONS = {'passed', 'pending', 'failed'}


def _finding(code='semantic_review_pending', failed=False):
    return {'code': 'semantic_sql_defect' if failed else code, 'domain': 'sql_content',
            'blocking': failed, 'status': '未通過' if failed else '待確認'}


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
        if (any(item.get(k) != unit.get(k) or not isinstance(item.get(k), str) or not item[k]
                for k in ('source_path', 'source_revision', 'source_hash'))
                or item.get('conclusion') not in CONCLUSIONS
                or not isinstance(item.get('checks'), dict) or set(item['checks']) != CHECKS
                or not all(_review(check) for check in item['checks'].values())):
            return [_finding()]
        conclusions.append(item['conclusion'])
        conclusions.extend(check['conclusion'] for check in item['checks'].values())
    if 'failed' in conclusions:
        return [_finding(failed=True)]
    if record['unresolved'] or 'pending' in conclusions:
        return [_finding()]
    return []


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
