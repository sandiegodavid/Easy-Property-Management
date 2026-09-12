from sqlalchemy import select
from app.modules.finance.infrastructure.sqlalchemy_models import SecurityDepositDeductionModel, SecurityDepositReceiptModel, SecurityDepositRefundModel, SecurityDepositSettlementModel

_MODELS = {"security_deposit_receipt": SecurityDepositReceiptModel, "security_deposit_deduction": SecurityDepositDeductionModel, "security_deposit_refund": SecurityDepositRefundModel, "security_deposit_settlement": SecurityDepositSettlementModel}

class SQLiteDepositFileLinkOperations:
    def __init__(self, file_operations): self.file_operations = file_operations
    def exists(self, connection, entity_type, entity_id): return connection.execute(select(_MODELS[entity_type].id).where(_MODELS[entity_type].id == entity_id)).first() is not None
    def active_link_count(self, connection, entity_type, entity_id): return self.file_operations.active_link_count(connection, entity_type, entity_id)
