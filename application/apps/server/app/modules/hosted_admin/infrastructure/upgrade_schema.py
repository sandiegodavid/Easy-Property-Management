"""Retained plans and explicit decisions are separate from runtime observations."""

SCHEMA = """
CREATE TABLE upgrade_plan (
 operation_id TEXT PRIMARY KEY REFERENCES operation(id),
 payload TEXT NOT NULL, created REAL NOT NULL
) STRICT;
CREATE TABLE upgrade_command (
 id TEXT PRIMARY KEY, identity TEXT NOT NULL, request TEXT NOT NULL,
 operation_id TEXT NOT NULL REFERENCES operation(id), result TEXT NOT NULL
) STRICT;
CREATE TABLE upgrade_decision (
 operation_id TEXT NOT NULL REFERENCES operation(id),
 command_id TEXT PRIMARY KEY REFERENCES upgrade_command(id),
 restore_access INTEGER NOT NULL CHECK(restore_access IN (0,1))
) STRICT;
CREATE TRIGGER upgrade_plan_no_update BEFORE UPDATE ON upgrade_plan BEGIN SELECT RAISE(ABORT,'immutable upgrade plan'); END;
CREATE TRIGGER upgrade_plan_no_delete BEFORE DELETE ON upgrade_plan BEGIN SELECT RAISE(ABORT,'immutable upgrade plan'); END;
CREATE TRIGGER upgrade_command_no_update BEFORE UPDATE ON upgrade_command BEGIN SELECT RAISE(ABORT,'immutable upgrade receipt'); END;
CREATE TRIGGER upgrade_command_no_delete BEFORE DELETE ON upgrade_command BEGIN SELECT RAISE(ABORT,'immutable upgrade receipt'); END;
CREATE TRIGGER upgrade_decision_no_update BEFORE UPDATE ON upgrade_decision BEGIN SELECT RAISE(ABORT,'immutable upgrade decision'); END;
CREATE TRIGGER upgrade_decision_no_delete BEFORE DELETE ON upgrade_decision BEGIN SELECT RAISE(ABORT,'immutable upgrade decision'); END;
CREATE TABLE upgrade_evidence (
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES operation(id),
 stage TEXT NOT NULL CHECK(stage IN ('recovery','target','rollback')),
 payload TEXT NOT NULL, created REAL NOT NULL
) STRICT;
CREATE TRIGGER upgrade_evidence_no_update BEFORE UPDATE ON upgrade_evidence BEGIN SELECT RAISE(ABORT,'immutable upgrade evidence'); END;
CREATE TRIGGER upgrade_evidence_no_delete BEFORE DELETE ON upgrade_evidence BEGIN SELECT RAISE(ABORT,'immutable upgrade evidence'); END;
CREATE TABLE upgrade_onboarding (
 command_id TEXT PRIMARY KEY REFERENCES upgrade_command(id),
 operation_id TEXT NOT NULL REFERENCES operation(id),
 handoff_id TEXT NOT NULL REFERENCES recovery_handoff(id),
 report_id TEXT NOT NULL REFERENCES recovery_report(id)
) STRICT;
CREATE TRIGGER upgrade_onboarding_no_update BEFORE UPDATE ON upgrade_onboarding BEGIN SELECT RAISE(ABORT,'immutable upgrade recovery link'); END;
CREATE TRIGGER upgrade_onboarding_no_delete BEFORE DELETE ON upgrade_onboarding BEGIN SELECT RAISE(ABORT,'immutable upgrade recovery link'); END;
CREATE UNIQUE INDEX one_host_upgrade ON operation((1)) WHERE kind IN ('upgrade','upgrade_rollback') AND state NOT IN ('succeeded','cancelled') AND cancel_requested=0;
"""
