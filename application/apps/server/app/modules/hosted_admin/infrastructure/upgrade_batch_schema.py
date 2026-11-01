"""Current greenfield batch membership, readiness history and immutable receipts."""

SCHEMA = """
CREATE TABLE upgrade_batch (
 id TEXT PRIMARY KEY, identity TEXT NOT NULL, generation INTEGER NOT NULL,
 request TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
 state TEXT NOT NULL CHECK(state IN ('checking','ready','blocked','running','paused','cancelled','completed','mixed')),
 attempt TEXT NOT NULL, run_command TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL,
 visits INTEGER NOT NULL DEFAULT 0 CHECK(visits>=0)
) STRICT;
CREATE TABLE upgrade_batch_member (
 batch_id TEXT NOT NULL REFERENCES upgrade_batch(id), sequence INTEGER NOT NULL CHECK(sequence>=0 AND sequence<50),
 instance TEXT NOT NULL, expected_revision INTEGER NOT NULL CHECK(expected_revision>=1),
 child_id TEXT UNIQUE REFERENCES operation(id), skipped INTEGER NOT NULL DEFAULT 0 CHECK(skipped IN (0,1)),
 PRIMARY KEY(batch_id,sequence), UNIQUE(batch_id,instance)
) STRICT;
CREATE TABLE upgrade_batch_command (
 id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES upgrade_batch(id),
 identity TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL, created REAL NOT NULL
) STRICT;
CREATE TABLE upgrade_batch_readiness (
 batch_id TEXT NOT NULL REFERENCES upgrade_batch(id), attempt TEXT NOT NULL REFERENCES upgrade_batch_command(id),
 sequence INTEGER NOT NULL, plan TEXT, error TEXT, observed REAL NOT NULL,
 PRIMARY KEY(batch_id,attempt,sequence),
 FOREIGN KEY(batch_id,sequence) REFERENCES upgrade_batch_member(batch_id,sequence),
 CHECK((plan IS NULL) != (error IS NULL))
) STRICT;
CREATE TABLE upgrade_batch_child (
 child_id TEXT PRIMARY KEY REFERENCES operation(id), batch_id TEXT NOT NULL REFERENCES upgrade_batch(id),
 sequence INTEGER NOT NULL, run_command TEXT NOT NULL REFERENCES upgrade_batch_command(id),
 attempt TEXT NOT NULL REFERENCES upgrade_batch_command(id), admitted REAL NOT NULL,
 UNIQUE(batch_id,sequence), FOREIGN KEY(batch_id,sequence) REFERENCES upgrade_batch_member(batch_id,sequence)
) STRICT;
CREATE TABLE upgrade_batch_skip (
 command_id TEXT PRIMARY KEY REFERENCES upgrade_batch_command(id) DEFERRABLE INITIALLY DEFERRED, batch_id TEXT NOT NULL REFERENCES upgrade_batch(id),
 sequence INTEGER NOT NULL, child_id TEXT NOT NULL REFERENCES upgrade_batch_child(child_id), generation INTEGER NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('queued','failed','completed')), error TEXT, created REAL NOT NULL,
 FOREIGN KEY(batch_id,sequence) REFERENCES upgrade_batch_member(batch_id,sequence)
) STRICT;
CREATE INDEX batch_schedule ON upgrade_batch(state,visits,created,id);
CREATE INDEX batch_directory ON upgrade_batch(identity,created DESC,id DESC);
CREATE TABLE upgrade_batch_event (
 batch_id TEXT NOT NULL REFERENCES upgrade_batch(id), revision INTEGER NOT NULL CHECK(revision>=1),
 action TEXT NOT NULL, reference TEXT NOT NULL, payload TEXT NOT NULL, recorded REAL NOT NULL,
 PRIMARY KEY(batch_id,revision)
) STRICT;
CREATE TRIGGER upgrade_batch_event_no_update BEFORE UPDATE ON upgrade_batch_event BEGIN SELECT RAISE(ABORT,'immutable batch history'); END;
CREATE TRIGGER upgrade_batch_event_no_delete BEFORE DELETE ON upgrade_batch_event BEGIN SELECT RAISE(ABORT,'immutable batch history'); END;
CREATE INDEX batch_rollback_parent ON operation(json_extract(payload,'$.parent')) WHERE kind='upgrade_rollback';
CREATE TRIGGER upgrade_batch_child_no_update BEFORE UPDATE ON upgrade_batch_child BEGIN SELECT RAISE(ABORT,'immutable batch admission'); END;
CREATE TRIGGER upgrade_batch_child_no_delete BEFORE DELETE ON upgrade_batch_child BEGIN SELECT RAISE(ABORT,'immutable batch admission'); END;
CREATE TRIGGER upgrade_batch_skip_intent_immutable BEFORE UPDATE OF command_id,batch_id,sequence,child_id,generation,created ON upgrade_batch_skip BEGIN SELECT RAISE(ABORT,'immutable skip intent'); END;
CREATE TRIGGER upgrade_batch_skip_completed BEFORE UPDATE ON upgrade_batch_skip WHEN OLD.state='completed' BEGIN SELECT RAISE(ABORT,'immutable skip result'); END;
CREATE TRIGGER upgrade_batch_skip_no_delete BEFORE DELETE ON upgrade_batch_skip BEGIN SELECT RAISE(ABORT,'immutable skip intent'); END;
CREATE TRIGGER upgrade_batch_intent_immutable BEFORE UPDATE OF id,identity,request,created ON upgrade_batch BEGIN SELECT RAISE(ABORT,'immutable batch intent'); END;
CREATE TRIGGER upgrade_batch_no_delete BEFORE DELETE ON upgrade_batch BEGIN SELECT RAISE(ABORT,'immutable batch'); END;
CREATE TRIGGER upgrade_batch_membership_immutable BEFORE UPDATE OF batch_id,sequence,instance,expected_revision ON upgrade_batch_member BEGIN SELECT RAISE(ABORT,'immutable batch membership'); END;
CREATE TRIGGER upgrade_batch_child_immutable BEFORE UPDATE OF child_id ON upgrade_batch_member WHEN OLD.child_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'immutable batch child'); END;
CREATE TRIGGER upgrade_batch_skip_immutable BEFORE UPDATE OF skipped ON upgrade_batch_member WHEN OLD.skipped=1 BEGIN SELECT RAISE(ABORT,'immutable batch skip'); END;
CREATE TRIGGER upgrade_batch_member_no_delete BEFORE DELETE ON upgrade_batch_member BEGIN SELECT RAISE(ABORT,'immutable batch membership'); END;
CREATE TRIGGER upgrade_batch_command_no_update BEFORE UPDATE ON upgrade_batch_command BEGIN SELECT RAISE(ABORT,'immutable batch receipt'); END;
CREATE TRIGGER upgrade_batch_command_no_delete BEFORE DELETE ON upgrade_batch_command BEGIN SELECT RAISE(ABORT,'immutable batch receipt'); END;
CREATE TRIGGER upgrade_batch_readiness_no_update BEFORE UPDATE ON upgrade_batch_readiness BEGIN SELECT RAISE(ABORT,'immutable batch readiness'); END;
CREATE TRIGGER upgrade_batch_readiness_no_delete BEFORE DELETE ON upgrade_batch_readiness BEGIN SELECT RAISE(ABORT,'immutable batch readiness'); END;
"""
