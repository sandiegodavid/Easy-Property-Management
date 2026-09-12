"""FIN-008 owns authorization for deposit evidence links."""
from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileLink


class DepositFileLinkValidator:
    entity_types = frozenset({"security_deposit_receipt", "security_deposit_deduction", "security_deposit_refund", "security_deposit_settlement"})
    _purposes = {
        "security_deposit_receipt": frozenset({"proof_of_deposit", "payment_confirmation", "supporting_document"}),
        "security_deposit_deduction": frozenset({"invoice", "receipt", "estimate", "condition_evidence", "supporting_document"}),
        "security_deposit_refund": frozenset({"proof_of_refund", "payment_confirmation", "supporting_document"}),
        "security_deposit_settlement": frozenset({"settlement_statement", "correspondence", "supporting_document"}),
    }
    def __init__(self, operations): self.operations = operations
    def validate_create(self, connection, link: FileLink):
        self._target(connection, link)
        if self.operations.active_link_count(connection, link.entity_type, link.entity_id) >= 20: raise FileError("A security-deposit record may have at most twenty active evidence links.")
    def validate_archive(self, connection, link: FileLink): self._target(connection, link)
    def _target(self, connection, link):
        if link.purpose not in self._purposes[link.entity_type]: raise FileError("Unsupported security-deposit evidence purpose.")
        if not self.operations.exists(connection, link.entity_type, link.entity_id): raise FileError("The linked security-deposit record does not exist.")
