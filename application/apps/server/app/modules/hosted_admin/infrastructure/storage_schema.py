"""Current greenfield protected storage reservations; IDs survive retirement."""

SCHEMA = """
CREATE TABLE storage_profile (
 id TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>=1),
 payload TEXT NOT NULL, digest TEXT NOT NULL UNIQUE, evidence TEXT, created REAL NOT NULL
) STRICT;
CREATE TABLE storage_allocation (
 operation_id TEXT PRIMARY KEY, instance TEXT NOT NULL, filesystem_uuid TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>=1),
 state TEXT NOT NULL CHECK(state IN ('reserved','active','retiring','retired')),
 request TEXT NOT NULL, fingerprint TEXT NOT NULL, identity TEXT NOT NULL,
 generation INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
) STRICT;
CREATE UNIQUE INDEX storage_live_instance ON storage_allocation(instance) WHERE state!='retired';
CREATE INDEX storage_filesystem ON storage_allocation(filesystem_uuid,state);
CREATE TABLE storage_project (
 filesystem_uuid TEXT NOT NULL, project_id INTEGER NOT NULL CHECK(project_id>0 AND project_id<4294967296),
 operation_id TEXT NOT NULL REFERENCES storage_allocation(operation_id),
 role TEXT NOT NULL CHECK(role IN ('workspace','scratch','control')),
 directory TEXT NOT NULL, hard_bytes INTEGER NOT NULL CHECK(hard_bytes>0),
 hard_inodes INTEGER NOT NULL CHECK(hard_inodes>0),
 allocated_bytes INTEGER NOT NULL DEFAULT 0 CHECK(allocated_bytes>=0),
 allocated_inodes INTEGER NOT NULL DEFAULT 0 CHECK(allocated_inodes>=0),
 observed REAL, enforcement INTEGER NOT NULL DEFAULT 0 CHECK(enforcement IN (0,1)),
 PRIMARY KEY(filesystem_uuid,project_id), UNIQUE(operation_id,role),
 UNIQUE(filesystem_uuid,directory)
) STRICT;
CREATE TABLE storage_event (
 operation_id TEXT NOT NULL REFERENCES storage_allocation(operation_id),
 revision INTEGER NOT NULL CHECK(revision>=1), action TEXT NOT NULL,
 payload TEXT NOT NULL, identity TEXT NOT NULL, generation INTEGER NOT NULL,
 created REAL NOT NULL, PRIMARY KEY(operation_id,revision)
) STRICT;
CREATE TABLE storage_command (
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES storage_allocation(operation_id),
 request TEXT NOT NULL, result TEXT NOT NULL, identity TEXT NOT NULL,
 generation INTEGER NOT NULL, proof TEXT NOT NULL, created REAL NOT NULL
) STRICT;
CREATE TABLE storage_attempt (
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES storage_allocation(operation_id),
 request TEXT NOT NULL, identity TEXT NOT NULL, generation INTEGER NOT NULL, created REAL NOT NULL
) STRICT;
CREATE INDEX storage_attempt_operation ON storage_attempt(operation_id);
CREATE INDEX storage_command_operation ON storage_command(operation_id);
CREATE TRIGGER storage_attempt_immutable BEFORE UPDATE ON storage_attempt
 BEGIN SELECT RAISE(ABORT,'immutable storage attempt'); END;
CREATE TRIGGER storage_attempt_no_delete BEFORE DELETE ON storage_attempt
 BEGIN SELECT RAISE(ABORT,'retained storage attempt'); END;
CREATE TRIGGER storage_command_immutable BEFORE UPDATE ON storage_command
 BEGIN SELECT RAISE(ABORT,'immutable storage command'); END;
CREATE TRIGGER storage_command_no_delete BEFORE DELETE ON storage_command
 BEGIN SELECT RAISE(ABORT,'retained storage command'); END;
CREATE TRIGGER storage_profile_immutable BEFORE UPDATE ON storage_profile
 BEGIN SELECT RAISE(ABORT,'immutable storage profile'); END;
CREATE TRIGGER storage_profile_no_delete BEFORE DELETE ON storage_profile
 BEGIN SELECT RAISE(ABORT,'retained storage profile'); END;
CREATE TRIGGER storage_event_immutable BEFORE UPDATE ON storage_event
 BEGIN SELECT RAISE(ABORT,'immutable storage event'); END;
CREATE TRIGGER storage_event_no_delete BEFORE DELETE ON storage_event
 BEGIN SELECT RAISE(ABORT,'retained storage event'); END;
CREATE TRIGGER storage_project_no_delete BEFORE DELETE ON storage_project
 BEGIN SELECT RAISE(ABORT,'retained project identity'); END;
CREATE TRIGGER storage_project_identity BEFORE UPDATE ON storage_project
 WHEN NEW.filesystem_uuid!=OLD.filesystem_uuid OR NEW.project_id!=OLD.project_id
 OR NEW.operation_id!=OLD.operation_id OR NEW.role!=OLD.role OR NEW.directory!=OLD.directory
 OR NEW.hard_bytes!=OLD.hard_bytes OR NEW.hard_inodes!=OLD.hard_inodes
 BEGIN SELECT RAISE(ABORT,'immutable project reservation'); END;
CREATE TRIGGER storage_allocation_intent BEFORE UPDATE ON storage_allocation
 WHEN NEW.operation_id!=OLD.operation_id OR NEW.instance!=OLD.instance
 OR NEW.filesystem_uuid!=OLD.filesystem_uuid OR NEW.request!=OLD.request
 OR NEW.fingerprint!=OLD.fingerprint OR NEW.identity!=OLD.identity
 OR NEW.generation!=OLD.generation OR NEW.created!=OLD.created
 BEGIN SELECT RAISE(ABORT,'immutable allocation intent'); END;
CREATE TRIGGER storage_allocation_no_delete BEFORE DELETE ON storage_allocation
 BEGIN SELECT RAISE(ABORT,'retained allocation history'); END;
"""
