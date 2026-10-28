from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import DBAPIError

from app.message_ingestion import InboundMessageInput, ingest_message


def test_non_unique_database_error_is_propagated():
    db = Mock()
    db.query.return_value.filter.return_value.one_or_none.return_value = None
    db.flush.side_effect = DBAPIError.instance(
        statement="INSERT INTO messages",
        params={},
        orig=RuntimeError("database unavailable"),
        dbapi_base_err=RuntimeError,
    )

    with pytest.raises(DBAPIError, match="database unavailable"):
        ingest_message(
            db,
            InboundMessageInput(
                channel_account_id=1,
                provider="gmail_api_pubsub",
                external_message_id="db-error",
                direction="inbound",
                status="received",
                occurred_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
                raw_content="body",
            ),
        )
    db.rollback.assert_not_called()
