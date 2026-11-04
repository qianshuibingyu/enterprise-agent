from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_business_revision_is_the_only_migration_head():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())

    assert [revision.revision for revision in revisions] == [
        "0009_outlook_account_credential",
        "0008_gmail_account_runtime",
        "0007_message_handling_status",
        "0006_manual_handling_status",
        "0005_channel_external_account",
        "0004_inquiry_events",
        "0003_messages",
        "0002_business_authorization",
        "0001_auth_sessions",
    ]
    assert revisions[0].down_revision == "0008_gmail_account_runtime"
    assert revisions[1].down_revision == "0007_message_handling_status"
    assert revisions[2].down_revision == "0006_manual_handling_status"
    assert revisions[3].down_revision == "0005_channel_external_account"
    assert revisions[4].down_revision == "0004_inquiry_events"
    assert revisions[5].down_revision == "0003_messages"
    assert revisions[6].down_revision == "0002_business_authorization"
    assert revisions[7].down_revision == "0001_auth_sessions"
    assert revisions[8].down_revision is None


def test_auth_migration_contains_only_auth_tables():
    migration = (BACKEND_DIR / "migrations" / "versions" / "0001_auth_sessions.py").read_text(encoding="utf-8")

    assert 'op.create_table(\n        "users"' in migration
    assert 'op.create_table(\n        "user_sessions"' in migration
    assert '"roles"' not in migration
    assert '"permissions"' not in migration
    assert "drop_table(\"user_sessions\")" in migration
    assert "drop_table(\"users\")" in migration


def test_message_migration_contains_provider_scoped_message_tables():
    migration = (BACKEND_DIR / "migrations" / "versions" / "0003_messages.py").read_text(encoding="utf-8")

    assert '"messages"' in migration
    assert '"message_attachments"' in migration
    assert '"channel_account_id"' in migration
    assert '"external_message_id"' in migration
    assert "uq_messages_account_provider_external_id" in migration
    assert "direction IN ('inbound', 'outbound')" in migration
    assert "status IN ('received', 'processed', 'failed')" in migration
    assert "drop_table(\"message_attachments\")" in migration
    assert "drop_table(\"messages\")" in migration


def test_business_migration_contains_only_confirmed_authorization_tables():
    migration = (BACKEND_DIR / "migrations" / "versions" / "0002_business_authorization.py").read_text(encoding="utf-8")

    for table in (
        '"channel_accounts"',
        '"channel_grants"',
        '"inquiries"',
        '"inquiry_attachments"',
        '"internal_notifications"',
    ):
        assert table in migration
    assert '"roles"' not in migration
    assert '"permissions"' not in migration
    assert "status IN ('new', 'assigned')" in migration
    assert "drop_table(\"internal_notifications\")" in migration
    assert "drop_table(\"channel_accounts\")" in migration


def test_channel_external_account_migration_adds_runtime_mapping():
    migration = (BACKEND_DIR / "migrations" / "versions" / "0005_channel_external_account.py").read_text(encoding="utf-8")

    assert '"channel_accounts"' in migration
    assert '"external_account_id"' in migration
    assert "ix_channel_accounts_external_account_id" in migration
    assert 'down_revision = "0004_inquiry_events"' in migration
    assert 'op.drop_column("channel_accounts", "external_account_id")' in migration


def test_inquiry_event_migration_contains_minimal_timeline_schema():
    migration = (BACKEND_DIR / "migrations" / "versions" / "0004_inquiry_events.py").read_text(encoding="utf-8")

    assert '"inquiry_events"' in migration
    assert '"inquiry_id"' in migration
    assert '"event_type"' in migration
    assert '"actor_user_id"' in migration
    assert '"target_user_id"' in migration
    assert "event_type IN ('inquiry_created', 'inquiry_transferred')" in migration
    assert "ix_inquiry_events_timeline" in migration
    assert "drop_table(\"inquiry_events\")" in migration


def test_manual_handling_migrations_add_separate_status_columns():
    inquiry_migration = (BACKEND_DIR / "migrations" / "versions" / "0006_manual_handling_status.py").read_text(encoding="utf-8")
    message_migration = (BACKEND_DIR / "migrations" / "versions" / "0007_message_handling_status.py").read_text(encoding="utf-8")

    assert 'down_revision = "0005_channel_external_account"' in inquiry_migration
    assert '"handling_status"' in inquiry_migration
    assert "handling_status IN ('pending', 'processed', 'ignored')" in inquiry_migration
    assert "inquiry_processed" in inquiry_migration
    assert "inquiry_ignored" in inquiry_migration
    assert 'down_revision = "0006_manual_handling_status"' in message_migration
    assert '"handling_status"' in message_migration
    assert "handling_status IN ('pending', 'processed', 'ignored')" in message_migration
    assert "drop_column(\"messages\", \"handling_status\")" in message_migration


def test_alembic_offline_environment_does_not_import_database_url():
    env = (BACKEND_DIR / "migrations" / "env.py").read_text(encoding="utf-8")

    assert 'url="postgresql+psycopg://"' in env
    assert "def run_migrations_online()" in env
    assert "    from app.database import get_database_url" in env
    assert "        get_database_url()," in env
    assert "\nfrom app.database import DATABASE_URL" not in env
