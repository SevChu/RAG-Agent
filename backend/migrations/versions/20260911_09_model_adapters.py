"""Immutable simulated adapters, lineage and logical archive.

Revision ID: 20260911_09
Revises: 20260911_08
Frozen SQLite DDL, independent of future application models.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_09"
down_revision: str | Sequence[str] | None = "20260911_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATEMENTS = (
    (
        "CREATE TABLE model_adapters (\n\tid CHAR(32) NOT NULL, \n\trun_id CHAR(3"
        "2) NOT NULL, \n\tpredecessor_id CHAR(32), \n\tmanifest JSON NOT NULL, \n\t"
        "manifest_sha256 VARCHAR(64) NOT NULL, \n\tartifact_kind VARCHAR(20) DE"
        "FAULT 'simulated' NOT NULL, \n\tdeployable BOOLEAN DEFAULT '0' NOT NUL"
        "L, \n\tevaluation_status VARCHAR(24) DEFAULT 'not_evaluated' NOT NULL,"
        " \n\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tarchive"
        "d_at DATETIME, \n\tCONSTRAINT pk_model_adapters PRIMARY KEY (id), \n\tCO"
        "NSTRAINT ck_model_adapters_simulated_only CHECK (artifact_kind='simu"
        "lated' AND deployable=0), \n\tCONSTRAINT ck_model_adapters_not_evaluat"
        "ed CHECK (evaluation_status='not_evaluated'), \n\tCONSTRAINT ck_model_"
        "adapters_manifest_hash CHECK (length(manifest_sha256)=64), \n\tCONSTRA"
        "INT ck_model_adapters_manifest CHECK (json_valid(manifest) AND json_"
        "type(manifest)='object'), \n\tCONSTRAINT uq_model_adapters_run_id UNIQ"
        "UE (run_id), \n\tCONSTRAINT fk_model_adapters_run_id_training_runs FOR"
        "EIGN KEY(run_id) REFERENCES training_runs (id) ON DELETE RESTRICT, \n"
        "\tCONSTRAINT fk_model_adapters_predecessor_id_model_adapters FOREIGN "
        "KEY(predecessor_id) REFERENCES model_adapters (id) ON DELETE RESTRIC"
        "T\n)"
    ),
    (
        "CREATE TRIGGER adapter_identity BEFORE UPDATE ON model_adapters WHEN"
        " NEW.id IS NOT OLD.id OR NEW.run_id IS NOT OLD.run_id OR NEW.predece"
        "ssor_id IS NOT OLD.predecessor_id OR NEW.manifest IS NOT OLD.manifes"
        "t OR NEW.manifest_sha256 IS NOT OLD.manifest_sha256 OR NEW.artifact_"
        "kind IS NOT OLD.artifact_kind OR NEW.deployable IS NOT OLD.deployabl"
        "e OR NEW.evaluation_status IS NOT OLD.evaluation_status OR NEW.creat"
        "ed_at IS NOT OLD.created_at OR OLD.archived_at IS NOT NULL OR NEW.ar"
        "chived_at IS NULL BEGIN SELECT RAISE(ABORT, 'adapter identity is imm"
        "utable'); END"
    ),
    (
        "CREATE TRIGGER adapter_no_replace BEFORE INSERT ON model_adapters WH"
        "EN EXISTS (SELECT 1 FROM model_adapters WHERE id=NEW.id OR run_id=NE"
        "W.run_id) BEGIN SELECT RAISE(ABORT, 'adapter already registered'); E"
        "ND"
    ),
    (
        "CREATE TRIGGER adapter_no_delete BEFORE DELETE ON model_adapters BEG"
        "IN SELECT RAISE(ABORT, 'adapters are retained'); END"
    ),
    (
        "CREATE TRIGGER adapter_success_only BEFORE INSERT ON model_adapters "
        "WHEN NOT EXISTS (SELECT 1 FROM training_runs WHERE id=NEW.run_id AND"
        " status='succeeded' AND json_extract(result,'$.artifact_kind')='simu"
        "lated' AND json_extract(result,'$.deployable')=0) BEGIN SELECT RAISE"
        "(ABORT, 'adapter requires successful simulated run'); END"
    ),
)

TRIGGER_NAMES = (
    "adapter_identity",
    "adapter_no_replace",
    "adapter_no_delete",
    "adapter_success_only",
)


def upgrade() -> None:
    for sql in STATEMENTS:
        op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    for name in TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER {name}")
    for table in ("model_adapters",):
        op.drop_table(table)
