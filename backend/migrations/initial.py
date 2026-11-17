from sqlalchemy import text
from src.config.database import Base, engine, Session
from src import models
def migrate():
    Base.metadata.create_all(engine)
    ensure_job_columns()
    ensure_site_state()
def ensure_job_columns():
    # create_all 不会为既有库补列；恢复隔离需要 jobs.claimed_epoch
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == 'mysql':
            n = conn.execute(text("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='jobs' AND column_name='claimed_epoch'")).scalar()
            if not n:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN claimed_epoch INT NULL"))
        elif dialect == 'postgresql':
            n = conn.execute(text("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='jobs' AND column_name='claimed_epoch'")).scalar()
            if not n:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN claimed_epoch INTEGER"))
        elif dialect == 'sqlite':
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(jobs)"))}
            if 'claimed_epoch' not in cols:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN claimed_epoch INTEGER"))
def ensure_site_state():
    with Session() as db:
        if not db.get(models.SiteState, 1):
            db.add(models.SiteState(id=1, epoch=1, write_seq=1, locked_run_id=None))
            db.commit()
if __name__=='__main__':migrate()
