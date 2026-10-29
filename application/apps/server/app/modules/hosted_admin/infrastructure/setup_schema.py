"""Current-format setup drafts, pinned resource plans and immutable create receipts."""

SCHEMA = """
CREATE TABLE setup_draft (
 id TEXT PRIMARY KEY, identity TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 state TEXT NOT NULL CHECK(state IN ('draft','discarded','started')),
 data TEXT NOT NULL, plan TEXT, operation_id TEXT UNIQUE REFERENCES operation(id),
 saved REAL NOT NULL,
 CHECK((state='started')=(operation_id IS NOT NULL)),
 CHECK((state='started')=(plan IS NOT NULL))
) STRICT;
CREATE TRIGGER setup_started_immutable BEFORE UPDATE ON setup_draft WHEN OLD.state!='draft'
 BEGIN SELECT RAISE(ABORT,'retained setup'); END;
CREATE TRIGGER setup_no_delete BEFORE DELETE ON setup_draft
 BEGIN SELECT RAISE(ABORT,'retained setup'); END;
CREATE INDEX setup_identity ON setup_draft(identity,saved DESC,id DESC);
"""
