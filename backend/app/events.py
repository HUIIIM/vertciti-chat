# Copyright (c) 2026 vertciti. All rights reserved.
#
# vertciti clean-room engineering: original expression written for the vertciti
# chat module (codename `chat`, module id `chat`). No code was copied from any
# prior codebase (clean-room chain; the 2023 line is read-only
# learning material only).

"""Product events with a fixed severity taxonomy.

Severities follow the seven-level scheme used by flight-software event logs
(mapped by analogy, not claimed): FATAL, WARNING_HI, WARNING_LO, COMMAND,
ACTIVITY_HI, ACTIVITY_LO, DIAGNOSTIC. Every event type is registered here with
one severity; an unregistered type is a programming error.
"""

from __future__ import annotations

from typing import Any

from . import db as _db

SEVERITIES = (
    "FATAL", "WARNING_HI", "WARNING_LO", "COMMAND", "ACTIVITY_HI", "ACTIVITY_LO", "DIAGNOSTIC",
)

EVENT_SEVERITY: dict[str, str] = {
    # server-side
    "session_created": "ACTIVITY_LO",
    "message_sent": "ACTIVITY_LO",
    "agent_unavailable": "WARNING_HI",
    # client-side (allowlisted in models.CLIENT_EVENT_TYPES)
    "cta_click": "ACTIVITY_HI",
    "workbench_entry": "ACTIVITY_LO",
    "module_switch": "ACTIVITY_LO",
}


def record_event(etype: str, session_id: str | None, detail: dict[str, Any] | None = None, *,
                 subject: str | None = None) -> None:
    severity = EVENT_SEVERITY[etype]
    _db.get_store().execute(
        "INSERT INTO events(ts, type, session_id, detail_json, severity, subject) VALUES(?,?,?,?,?,?)",
        (_db.utcnow(), etype, session_id, _db.dumps(detail or {}), severity, subject),
    )
