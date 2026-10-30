"""Current greenfield recovery registry; reports and completions remain history."""

SCHEMA = """
CREATE TABLE recovery_handoff (
 id TEXT PRIMARY KEY, instance TEXT NOT NULL, binding TEXT NOT NULL,
 created REAL NOT NULL, identity TEXT NOT NULL, generation INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX recovery_exact_binding ON recovery_handoff(instance,binding,generation);
CREATE TABLE recovery_report (
 id TEXT PRIMARY KEY, handoff_id TEXT NOT NULL REFERENCES recovery_handoff(id),
 payload TEXT NOT NULL, registered REAL NOT NULL
) STRICT;
CREATE INDEX recovery_report_history ON recovery_report(handoff_id,registered DESC,id DESC);
CREATE TABLE onboarding_completion (
 operation_id TEXT PRIMARY KEY REFERENCES admission(id),
 handoff_id TEXT NOT NULL REFERENCES recovery_handoff(id),
 report_id TEXT NOT NULL REFERENCES recovery_report(id), completed REAL NOT NULL
) STRICT;
CREATE TABLE recovery_attention (
 handoff_id TEXT PRIMARY KEY REFERENCES recovery_handoff(id),
 state TEXT NOT NULL CHECK(state IN ('unknown','failed','warning','overdue','verified','stale')),
 checked REAL NOT NULL, acknowledged REAL
) STRICT;
CREATE TRIGGER recovery_handoff_immutable BEFORE UPDATE ON recovery_handoff
 BEGIN SELECT RAISE(ABORT,'immutable recovery handoff'); END;
CREATE TRIGGER recovery_handoff_no_delete BEFORE DELETE ON recovery_handoff
 BEGIN SELECT RAISE(ABORT,'retained recovery handoff'); END;
CREATE TRIGGER recovery_report_immutable BEFORE UPDATE ON recovery_report
 BEGIN SELECT RAISE(ABORT,'immutable recovery report'); END;
CREATE TRIGGER recovery_report_no_delete BEFORE DELETE ON recovery_report
 BEGIN SELECT RAISE(ABORT,'retained recovery report'); END;
CREATE TRIGGER onboarding_completion_immutable BEFORE UPDATE ON onboarding_completion
 BEGIN SELECT RAISE(ABORT,'immutable onboarding completion'); END;
CREATE TRIGGER onboarding_completion_no_delete BEFORE DELETE ON onboarding_completion
 BEGIN SELECT RAISE(ABORT,'retained onboarding completion'); END;
"""
