"""Persistent fake training runs, event audit, lease fencing and dependency cancellation.

Revision ID: 20260911_08
Revises: 20260911_07
Frozen SQLite DDL, independent of future application models.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260911_08"
down_revision: str | Sequence[str] | None = "20260911_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = (
    (
        'CREATE TABLE training_worker_leases (\n\tid INTEGER NOT NULL, \n\towner_'
        "token VARCHAR(64), \n\texpires_at FLOAT DEFAULT '0' NOT NULL, \n\tCONSTR"
        'AINT pk_training_worker_leases PRIMARY KEY (id), \n\tCONSTRAINT ck_tra'
        'ining_worker_leases_singleton CHECK (id=1)\n)'
    ),
    (
        'CREATE TABLE training_runs (\n\tid CHAR(32) NOT NULL, \n\tagent_profile_'
        'id CHAR(32) NOT NULL, \n\tagent_revision_id CHAR(32) NOT NULL, \n\tdatas'
        'et_revision_id CHAR(32) NOT NULL, \n\tretry_of CHAR(32), \n\tidempotency'
        '_key VARCHAR(100) NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n'
        '\tsnapshot JSON NOT NULL, \n\tsnapshot_sha256 VARCHAR(64) NOT NULL, \n\ts'
        "tatus VARCHAR(20) DEFAULT 'queued' NOT NULL, \n\tcompleted_steps INTEG"
        "ER DEFAULT '0' NOT NULL, \n\ttotal_steps INTEGER NOT NULL, \n\tlast_code"
        " VARCHAR(64) DEFAULT 'QUEUED' NOT NULL, \n\towner_token VARCHAR(64), \n"
        '\tstarted_at FLOAT, \n\tfinished_at FLOAT, \n\tresult JSON, \n\tcreated_at '
        'DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_trainin'
        'g_runs PRIMARY KEY (id), \n\tCONSTRAINT fk_training_runs_agent_profile'
        '_id_agent_profile_revisions FOREIGN KEY(agent_profile_id, agent_revi'
        'sion_id) REFERENCES agent_profile_revisions (agent_profile_id, id) O'
        'N DELETE RESTRICT, \n\tCONSTRAINT ck_training_runs_status CHECK (statu'
        "s IN ('queued','running','cancelling','succeeded','failed','cancelle"
        "d','interrupted')), \n\tCONSTRAINT ck_training_runs_total_steps CHECK "
        '(total_steps BETWEEN 1 AND 100), \n\tCONSTRAINT ck_training_runs_compl'
        'eted_steps CHECK (completed_steps BETWEEN 0 AND total_steps), \n\tCONS'
        'TRAINT ck_training_runs_snapshot_hash CHECK (length(snapshot_sha256)'
        '=64), \n\tCONSTRAINT ck_training_runs_request_hash CHECK (length(reque'
        'st_sha256)=64), \n\tCONSTRAINT ck_training_runs_snapshot CHECK (json_v'
        "alid(snapshot) AND json_type(snapshot)='object'), \n\tCONSTRAINT fk_tr"
        'aining_runs_dataset_revision_id_training_dataset_revisions FOREIGN K'
        'EY(dataset_revision_id) REFERENCES training_dataset_revisions (id) O'
        'N DELETE RESTRICT, \n\tCONSTRAINT fk_training_runs_retry_of_training_r'
        'uns FOREIGN KEY(retry_of) REFERENCES training_runs (id) ON DELETE RE'
        'STRICT, \n\tCONSTRAINT uq_training_runs_idempotency_key UNIQUE (idempo'
        'tency_key)\n)'
    ),
    (
        'CREATE INDEX ix_training_runs_agent_profile_id ON training_runs (age'
        'nt_profile_id)'
    ),
    (
        'CREATE INDEX ix_training_runs_dataset_revision_id ON training_runs ('
        'dataset_revision_id)'
    ),
    (
        'CREATE INDEX ix_training_runs_status ON training_runs (status)'
    ),
    (
        'CREATE TABLE training_events (\n\trun_id CHAR(32) NOT NULL, \n\tsequence'
        ' INTEGER NOT NULL, \n\tphase VARCHAR(20) NOT NULL, \n\tcode VARCHAR(64) '
        'NOT NULL, \n\tcompleted_steps INTEGER NOT NULL, \n\ttotal_steps INTEGER '
        'NOT NULL, \n\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, '
        '\n\tCONSTRAINT pk_training_events PRIMARY KEY (run_id, sequence), \n\tCO'
        'NSTRAINT fk_training_events_run_id_training_runs FOREIGN KEY(run_id)'
        ' REFERENCES training_runs (id) ON DELETE RESTRICT\n)'
    ),
    (
        'CREATE TRIGGER training_run_identity BEFORE UPDATE ON training_runs '
        'WHEN NEW.id IS NOT OLD.id OR NEW.agent_profile_id IS NOT OLD.agent_p'
        'rofile_id OR NEW.agent_revision_id IS NOT OLD.agent_revision_id OR N'
        'EW.dataset_revision_id IS NOT OLD.dataset_revision_id OR NEW.retry_o'
        'f IS NOT OLD.retry_of OR NEW.idempotency_key IS NOT OLD.idempotency_'
        'key OR NEW.request_sha256 IS NOT OLD.request_sha256 OR NEW.snapshot '
        'IS NOT OLD.snapshot OR NEW.snapshot_sha256 IS NOT OLD.snapshot_sha25'
        '6 OR NEW.total_steps IS NOT OLD.total_steps OR NEW.created_at IS NOT'
        " OLD.created_at BEGIN SELECT RAISE(ABORT, 'training run identity is "
        "immutable'); END"
    ),
    (
        'CREATE TRIGGER training_run_state BEFORE UPDATE ON training_runs WHE'
        "N OLD.status IN ('succeeded','failed','cancelled','interrupted') OR "
        "NEW.completed_steps < OLD.completed_steps OR (NEW.status='succeeded'"
        ' AND NEW.completed_steps<>NEW.total_steps) OR (NEW.status<>OLD.statu'
        "s AND NOT ((OLD.status='queued' AND NEW.status IN ('running','cancel"
        "led')) OR (OLD.status='running' AND NEW.status IN ('cancelling','suc"
        "ceeded','failed','interrupted')) OR (OLD.status='cancelling' AND NEW"
        ".status='cancelled'))) BEGIN SELECT RAISE(ABORT, 'invalid training s"
        "tate transition'); END"
    ),
    (
        'CREATE TRIGGER training_run_no_replace BEFORE INSERT ON training_run'
        's WHEN EXISTS (SELECT 1 FROM training_runs WHERE id=NEW.id OR idempo'
        "tency_key=NEW.idempotency_key) BEGIN SELECT RAISE(ABORT, 'training r"
        "uns cannot be replaced'); END"
    ),
    (
        'CREATE TRIGGER training_run_no_delete BEFORE DELETE ON training_runs'
        " BEGIN SELECT RAISE(ABORT, 'training runs are retained'); END"
    ),
    (
        'CREATE TRIGGER training_run_created AFTER INSERT ON training_runs BE'
        'GIN INSERT INTO training_events (run_id,sequence,phase,code,complete'
        'd_steps,total_steps) SELECT NEW.id,COALESCE(MAX(sequence),0)+1,NEW.s'
        'tatus,NEW.last_code,NEW.completed_steps,NEW.total_steps FROM trainin'
        'g_events WHERE run_id=NEW.id; END'
    ),
    (
        'CREATE TRIGGER training_run_changed AFTER UPDATE ON training_runs WH'
        'EN NEW.status<>OLD.status OR NEW.completed_steps<>OLD.completed_step'
        's BEGIN INSERT INTO training_events (run_id,sequence,phase,code,comp'
        'leted_steps,total_steps) SELECT NEW.id,COALESCE(MAX(sequence),0)+1,N'
        'EW.status,NEW.last_code,NEW.completed_steps,NEW.total_steps FROM tra'
        'ining_events WHERE run_id=NEW.id; END'
    ),
    (
        'CREATE TRIGGER training_event_no_update BEFORE UPDATE ON training_ev'
        "ents BEGIN SELECT RAISE(ABORT, 'training events are immutable'); END"
    ),
    (
        'CREATE TRIGGER training_event_no_delete BEFORE DELETE ON training_ev'
        "ents BEGIN SELECT RAISE(ABORT, 'training events are immutable'); END"
    ),
    (
        'CREATE TRIGGER training_event_no_replace BEFORE INSERT ON training_e'
        'vents WHEN EXISTS (SELECT 1 FROM training_events WHERE run_id=NEW.ru'
        "n_id AND sequence=NEW.sequence) BEGIN SELECT RAISE(ABORT, 'training "
        "events are immutable'); END"
    ),
    (
        'CREATE TRIGGER training_review_revoked AFTER INSERT ON training_data'
        "set_reviews WHEN NEW.status<>'approved' BEGIN UPDATE training_runs S"
        "ET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancellin"
        "g' END, last_code='DATASET_REVOKED', finished_at=CASE WHEN status='q"
        "ueued' THEN unixepoch() ELSE NULL END WHERE status IN ('queued','run"
        "ning') AND (dataset_revision_id=NEW.revision_id); END"
    ),
    (
        'CREATE TRIGGER training_agent_unavailable AFTER UPDATE OF enabled,de'
        'leted_at ON agent_profiles WHEN NEW.enabled=0 OR NEW.deleted_at IS N'
        "OT NULL BEGIN UPDATE training_runs SET status=CASE WHEN status='queu"
        "ed' THEN 'cancelled' ELSE 'cancelling' END, last_code='AGENT_UNAVAIL"
        "ABLE', finished_at=CASE WHEN status='queued' THEN unixepoch() ELSE N"
        "ULL END WHERE status IN ('queued','running') AND (agent_profile_id=N"
        'EW.id); END'
    ),
    (
        'CREATE TRIGGER training_agent_scope_changed AFTER INSERT ON agent_pr'
        'ofile_revisions BEGIN UPDATE training_runs SET status=CASE WHEN stat'
        "us='queued' THEN 'cancelled' ELSE 'cancelling' END, last_code='SOURC"
        "E_SCOPE_REVOKED', finished_at=CASE WHEN status='queued' THEN unixepo"
        "ch() ELSE NULL END WHERE status IN ('queued','running') AND (agent_p"
        'rofile_id=NEW.agent_profile_id AND EXISTS (SELECT 1 FROM json_each(t'
        "raining_runs.snapshot,'$.source_course_ids') AS source WHERE source."
        "value NOT IN (SELECT value FROM json_each(NEW.config,'$.allowed_cour"
        "se_ids')))); END"
    ),
    (
        'CREATE TRIGGER training_course_deleted AFTER DELETE ON courses BEGIN'
        " UPDATE training_runs SET status=CASE WHEN status='queued' THEN 'can"
        "celled' ELSE 'cancelling' END, last_code='SOURCE_DELETED', finished_"
        "at=CASE WHEN status='queued' THEN unixepoch() ELSE NULL END WHERE st"
        "atus IN ('queued','running') AND (EXISTS (SELECT 1 FROM json_each(tr"
        "aining_runs.snapshot,'$.source_course_ids') WHERE replace(value,'-',"
        "'')=OLD.id)); END"
    ),
)

TRIGGER_NAMES = (
    'training_run_identity',
    'training_run_state',
    'training_run_no_replace',
    'training_run_no_delete',
    'training_run_created',
    'training_run_changed',
    'training_event_no_update',
    'training_event_no_delete',
    'training_event_no_replace',
    'training_review_revoked',
    'training_agent_unavailable',
    'training_agent_scope_changed',
    'training_course_deleted',
)


def upgrade() -> None:
    for sql in STATEMENTS:
        op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    for name in TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER {name}")
    for table in ("training_events", "training_runs", "training_worker_leases"):
        op.drop_table(table)
