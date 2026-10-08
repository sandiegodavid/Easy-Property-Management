"""Named helpers for business fixtures; no replacement of public service methods."""

from json import loads


def owner_command(service, action, *args, **kwargs):
    key = args[0].idempotency_key if action == "create" else args[-1]

    def read(tx):
        prior = tx.report_by_operation_key(key)
        if prior is not None:
            return prior["expected_revision"], loads(prior["request_json"])["payload"].get(
                "expected_ledger_revision"
            )
        if action == "create":
            return 0, None
        item = tx.report(args[0])
        return item.report_revision, tx.ledger_revision(
            item.lease_id
        ) if action == "verify" else None

    revision, ledger = service.unit_of_work.read(read)
    kwargs.setdefault("expected_revision", revision)
    if action == "verify":
        kwargs.setdefault("expected_ledger_revision", ledger)
    return getattr(service, action)(*args, **kwargs)
