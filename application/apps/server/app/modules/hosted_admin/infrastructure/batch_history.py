"""Append-only control snapshots make parent decisions independently reviewable."""

from app.modules.hosted_admin.application.operations import canonical

FIELDS = ("revision", "state", "attempt", "run_command", "generation", "error")


def record_event(connection, store, identifier, action, reference):
    row = connection.execute("SELECT * FROM upgrade_batch WHERE id=?", (identifier,)).fetchone()
    connection.execute(
        "INSERT INTO upgrade_batch_event VALUES (?,?,?,?,?,?)",
        (
            identifier,
            row["revision"],
            action,
            reference,
            canonical({field: row[field] for field in FIELDS}),
            store.clock(),
        ),
    )
