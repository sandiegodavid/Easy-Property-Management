"""Finance-owned authorization for FILE-001 expense evidence."""

from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileLink
from app.modules.finance.application.expense_ports import ExpenseFileLinkOperations


class ExpenseFileLinkValidator:
    entity_types = frozenset({"expense"})
    _purposes = frozenset({"receipt", "invoice", "proof_of_payment", "supporting_document"})

    def __init__(self, operations: ExpenseFileLinkOperations) -> None:
        self.operations = operations

    def validate_create(self, connection, link: FileLink) -> None:
        self._validate_target(connection, link)
        if self.operations.active_link_count(connection, link.entity_id) >= 20:
            raise FileError("An expense may have at most twenty active evidence links.")

    def validate_archive(self, connection, link: FileLink) -> None:
        self._validate_target(connection, link)

    def _validate_target(self, connection, link: FileLink) -> None:
        if link.purpose not in self._purposes:
            raise FileError("Unsupported expense evidence purpose.")
        if not self.operations.expense_exists(connection, link.entity_id):
            raise FileError("The linked expense does not exist.")
