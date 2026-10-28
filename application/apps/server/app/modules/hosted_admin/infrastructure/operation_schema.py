"""Current control-plane format, separate from every portable business workspace."""

SCHEMA = """
CREATE TABLE operation_target (
 target TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>=0),
 fence INTEGER NOT NULL CHECK(fence>=0)
) STRICT;
CREATE TABLE operation (
 id TEXT PRIMARY KEY, identity TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>0),
 kind TEXT NOT NULL CHECK(kind IN ('source','provision','qualification_test')),
 target TEXT NOT NULL REFERENCES operation_target(target),
 request_hash TEXT NOT NULL, payload TEXT NOT NULL, target_fence INTEGER NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>0),
 state TEXT NOT NULL CHECK(state IN ('queued','running','waiting','unknown','failed','paused','cancelled','succeeded')),
 cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
 claim TEXT, claim_until REAL, error TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL,
 CHECK((claim IS NULL)=(claim_until IS NULL))
) STRICT;
CREATE UNIQUE INDEX one_target_operation ON operation(target)
 WHERE state IN ('queued','running','waiting','unknown','failed','paused') AND cancel_requested=0;
CREATE INDEX recent_identity_operations ON operation(identity,created DESC,id DESC);
CREATE TRIGGER operation_intent_immutable BEFORE UPDATE OF id,identity,kind,target,request_hash,payload,created ON operation
 BEGIN SELECT RAISE(ABORT,'immutable operation intent'); END;
CREATE TRIGGER operation_no_delete BEFORE DELETE ON operation BEGIN SELECT RAISE(ABORT,'retained operation'); END;
CREATE TRIGGER operation_result_immutable BEFORE UPDATE OF result ON operation WHEN OLD.result IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'immutable operation result'); END;
CREATE TABLE operation_step (
 operation_id TEXT NOT NULL REFERENCES operation(id), sequence INTEGER NOT NULL,
 kind TEXT NOT NULL, spec_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','intent','verified')),
 reference TEXT, result TEXT, checked REAL,
 PRIMARY KEY(operation_id,sequence), UNIQUE(operation_id,kind)
) STRICT;
CREATE TRIGGER step_spec_immutable BEFORE UPDATE OF operation_id,sequence,kind,spec_hash ON operation_step
 BEGIN SELECT RAISE(ABORT,'immutable step intent'); END;
CREATE TRIGGER step_verified_immutable BEFORE UPDATE ON operation_step WHEN OLD.state='verified'
 BEGIN SELECT RAISE(ABORT,'immutable verified step'); END;
CREATE TABLE reservation (
 kind TEXT NOT NULL, identity TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0),
 operation_id TEXT NOT NULL REFERENCES operation(id), target TEXT NOT NULL,
 PRIMARY KEY(kind,identity)
) STRICT;
CREATE TABLE operation_audit (
 sequence INTEGER PRIMARY KEY, operation_id TEXT NOT NULL, action TEXT NOT NULL,
 identity TEXT NOT NULL, recorded REAL NOT NULL
) STRICT;
CREATE TRIGGER operation_audit_no_update BEFORE UPDATE ON operation_audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
CREATE TRIGGER operation_audit_no_delete BEFORE DELETE ON operation_audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
CREATE TABLE capacity (
 id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL CHECK(revision>0),
 ceiling INTEGER NOT NULL CHECK(ceiling>=0), environment_hash TEXT NOT NULL
) STRICT;
CREATE TABLE qualification (
 id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, payload TEXT NOT NULL,
 identity TEXT NOT NULL, generation INTEGER NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 state TEXT NOT NULL CHECK(state IN ('planned','running','aborted','retired','promoted')),
 created REAL NOT NULL
) STRICT;
CREATE TRIGGER qualification_intent_immutable BEFORE UPDATE OF id,request_hash,payload,identity,created ON qualification
 BEGIN SELECT RAISE(ABORT,'immutable qualification'); END;
CREATE TABLE qualification_evidence (
 id TEXT PRIMARY KEY, qualification_id TEXT NOT NULL REFERENCES qualification(id),
 kind TEXT NOT NULL, digest TEXT NOT NULL, environment_hash TEXT NOT NULL,
 observed REAL NOT NULL, expires REAL NOT NULL, passed INTEGER NOT NULL CHECK(passed IN (0,1)),
 UNIQUE(qualification_id,kind)
) STRICT;
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON qualification_evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON qualification_evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
CREATE TABLE qualification_receipt (
 id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, result TEXT NOT NULL
) STRICT;
CREATE TRIGGER qualification_receipt_no_update BEFORE UPDATE ON qualification_receipt BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
CREATE TRIGGER qualification_receipt_no_delete BEFORE DELETE ON qualification_receipt BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
"""
