class MigrationSchemaError(RuntimeError):
    """A recorded migration does not match the local schema."""
