import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/release-docs/scripts"
sys.path.insert(0, str(SCRIPTS))

import evidence_redaction


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("password=hunter2 token:abc123 secret=shh api_key='key-1'",
         "password=[REDACTED] token:[REDACTED] secret=[REDACTED] api_key=[REDACTED]"),
        ("Server=db;User ID=release;Password=hunter2;Database=release",
         "Server=db;User ID=[REDACTED];Password=[REDACTED];Database=release"),
        ("https://release:hunter2@example.test/path", "https://[REDACTED]@example.test/path"),
        ("sqlcmd -S local -U release -P hunter2", "sqlcmd -S local -U [REDACTED] -P [REDACTED]"),
        ("Bearer abcdefghijklmnop", "Bearer [REDACTED]"),
    ],
)
def test_redact_text_masks_labeled_connection_url_command_and_bearer_credentials(value, expected):
    assert evidence_redaction.redact_text(value) == expected


def test_known_secrets_are_replaced_even_without_credential_labels():
    assert evidence_redaction.redact_text("tool failed: hunter2", secrets=("hunter2",)) == \
        "tool failed: [REDACTED]"


def test_credential_material_with_unrecognized_value_fails_closed_without_echoing_input():
    value = "credential material: opaque-value"
    with pytest.raises(ValueError, match="secret_redaction_required") as error:
        evidence_redaction.redact_text(value)
    assert value not in str(error.value)


def test_known_credential_material_is_masked_without_failing_closed():
    assert evidence_redaction.redact_text(
        "credential material: known-secret", secrets=("known-secret",)
    ) == "credential material: [REDACTED]"


def test_text_user_id_assignment_is_masked_without_masking_sql_identifiers():
    value = "user_id=release-user; SELECT user_id FROM dbo.ReleaseUser"
    assert evidence_redaction.redact_text(value) == \
        "user_id=[REDACTED]; SELECT user_id FROM dbo.ReleaseUser"


def test_user_id_redaction_preserves_sql_update_identifiers_and_masks_prose():
    value = "UPDATE t SET user_id = source_user_id; login failed user_id=alice"
    assert evidence_redaction.redact_text(value) == \
        "UPDATE t SET user_id = source_user_id; login failed user_id=[REDACTED]"


def test_user_id_redaction_does_not_exempt_assignments_in_sql_comments():
    value = "UPDATE t SET user_id = source_user_id -- login failed user_id=alice"
    assert evidence_redaction.redact_text(value) == \
        "UPDATE t SET user_id = source_user_id -- login failed user_id=[REDACTED]"


def test_user_id_redaction_masks_quoted_rhs_even_inside_update_set():
    assert evidence_redaction.redact_text("UPDATE users SET user_id='alice'") == \
        "UPDATE users SET user_id=[REDACTED]"
    assert evidence_redaction.redact_text("UPDATE users SET [user_id]='alice'") == \
        "UPDATE users SET [user_id]=[REDACTED]"


def test_user_id_redaction_preserves_multiline_sql_identifier_rhs():
    value = "UPDATE users\nSET\n    user_id = source_user_id"
    assert evidence_redaction.redact_text(value) == value


def test_user_id_redaction_does_not_treat_sql_looking_quoted_note_as_sql():
    value = "note = 'example: UPDATE users SET user_id=alice'"
    assert evidence_redaction.redact_text(value) == \
        "note = 'example: UPDATE users SET user_id=[REDACTED]'"
    assert evidence_redaction.redact_text("UPDATE t SET note = user_id=alice") == \
        "UPDATE t SET note = user_id=[REDACTED]"


def test_double_quoted_sql_looking_note_does_not_create_sql_context():
    value = 'note = "example ""quoted"" text: UPDATE users SET user_id=alice"'
    assert evidence_redaction.redact_text(value) == \
        'note = "example ""quoted"" text: UPDATE users SET user_id=[REDACTED]"'


def test_comment_inside_set_preserves_sql_context_but_redacts_comment_prose():
    value = "UPDATE users SET /* login user_id=comment-user */ user_id=source_user_id"
    assert evidence_redaction.redact_text(value) == \
        "UPDATE users SET /* login user_id=[REDACTED] */ user_id=source_user_id"


def test_authorization_assignment_is_masked_and_raw_evidence_fails_closed():
    value = "Authorization=opaque-value"
    assert evidence_redaction.redact_text(value) == "Authorization=[REDACTED]"
    with pytest.raises(ValueError, match="secret_redaction_required"):
        evidence_redaction.assert_safe_evidence(value)


def test_user_id_redaction_consumes_doubled_quote_sql_literals():
    value = "UPDATE users SET note = 'safe ''quoted'' user_id=alice'"
    assert evidence_redaction.redact_text(value) == \
        "UPDATE users SET note = 'safe ''quoted'' user_id=[REDACTED]'"
    assert evidence_redaction.redact_text("UPDATE users SET user_id = 'ali''ce'") == \
        "UPDATE users SET user_id = [REDACTED]"


def test_user_id_redaction_preserves_sql_server_bracketed_rhs_identifier():
    value = "UPDATE users SET user_id = [source_user_id]"
    assert evidence_redaction.redact_text(value) == value
    bracketed_target = "UPDATE users SET [user_id] = [source_user_id]"
    assert evidence_redaction.redact_text(bracketed_target) == bracketed_target
    assert evidence_redaction.redact_text("UPDATE users SET user_id = 'source_user_id'") == \
        "UPDATE users SET user_id = [REDACTED]"
    assert evidence_redaction.redact_text("SELECT 'O''Brien' AS note, [source_user_id] FROM users") == \
        "SELECT 'O''Brien' AS note, [source_user_id] FROM users"


def test_user_id_redaction_scans_multiline_literals_but_not_comments_for_sql_context():
    value = "UPDATE users /* setup */\nSET note = 'line one,\nUPDATE x SET user_id=alice' -- user_id=bob"
    assert evidence_redaction.redact_text(value) == \
        "UPDATE users /* setup */\nSET note = 'line one,\nUPDATE x SET user_id=[REDACTED]' -- user_id=[REDACTED]"


@pytest.mark.parametrize("value", [
    "UPDATE users -- note\nSET user_id = alice",
    "UPDATE users /* note */\nSET user_id = alice",
])
def test_user_id_redaction_treats_comments_as_whitespace_in_sql_context(value):
    assert evidence_redaction.redact_text(value).endswith("user_id = alice")


def test_user_id_redaction_does_not_carry_sql_context_across_statements():
    value = "UPDATE users;\nSET user_id = alice"
    assert evidence_redaction.redact_text(value).endswith("user_id = [REDACTED]")


def test_user_id_redaction_keeps_comment_and_prose_assignments_masked():
    value = "-- failed login user_id=alice\nUPDATE users SET user_id = source_user_id"
    assert evidence_redaction.redact_text(value) == \
        "-- failed login user_id=[REDACTED]\nUPDATE users SET user_id = source_user_id"


def test_redact_mapping_recurses_and_preserves_safe_identifiers_hashes_paths_and_statuses():
    payload = {
        "finding": {"message": "token=abc123", "code": "business_data_validation"},
        "command": ["sqlcmd", "--password", "hunter2"],
        "artifact": "dbo.ReleaseConfig",
        "sha256": "a" * 64,
        "path": "C:/release/output.sql",
        "status": "passed",
    }

    cleaned = evidence_redaction.redact_mapping(payload)

    assert cleaned["finding"] == {"message": "token=[REDACTED]", "code": "business_data_validation"}
    assert cleaned["command"] == ["sqlcmd", "--password", "[REDACTED]"]
    assert cleaned["artifact"] == payload["artifact"]
    assert cleaned["sha256"] == payload["sha256"]
    assert cleaned["path"] == payload["path"]
    assert cleaned["status"] == payload["status"]
    evidence_redaction.assert_safe_evidence(cleaned)


@pytest.mark.parametrize("value", [
    "credential material: sk-live-0123456789abcdef0123456789",
])
def test_unrecognized_secret_like_material_fails_closed_without_echoing_input(value):
    with pytest.raises(ValueError, match="secret_redaction_required") as error:
        evidence_redaction.redact_text(value)
    assert value not in str(error.value)


def test_private_key_block_is_recognized_and_fully_masked():
    value = "before\n-----BEGIN PRIVATE KEY-----\nraw-private-key-material\n-----END PRIVATE KEY-----\nafter"
    assert evidence_redaction.redact_text(value) == "before\n[REDACTED]\nafter"


def test_sensitive_mapping_values_are_masked_regardless_of_json_type():
    assert evidence_redaction.redact_mapping({"api_key": {"raw": "secret-value"}}) == \
        {"api_key": "[REDACTED]"}


def test_assert_safe_evidence_rejects_unredacted_command_arguments():
    with pytest.raises(ValueError, match="secret_redaction_required"):
        evidence_redaction.assert_safe_evidence({"command": ["sqlcmd", "-P", "raw-password"]})
    with pytest.raises(ValueError, match="secret_redaction_required"):
        evidence_redaction.assert_safe_evidence({"command": "sqlcmd -P raw-password"})
