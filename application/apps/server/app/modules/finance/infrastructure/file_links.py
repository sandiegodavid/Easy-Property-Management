"""SQLite queries used by Finance's FILE-001 authorization policy."""

from sqlalchemy import select

from app.modules.finance.infrastructure.sqlalchemy_models import ExpenseModel


class SQLiteExpenseFileLinkOperations:
    def __init__(self, file_operations):
        self.file_operations = file_operations

    def expense_exists(self, connection, expense_id):
        return connection.execute(select(ExpenseModel.id).where(
            ExpenseModel.id == expense_id
        ).limit(1)).first() is not None

    def active_link_count(self, connection, expense_id):
        return self.file_operations.active_link_count(connection, "expense", expense_id)
