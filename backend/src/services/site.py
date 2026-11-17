from fastapi import HTTPException
from sqlalchemy import select
from src.models import SiteState
def get_state(db):
    st = db.get(SiteState, 1)
    if not st:
        st = SiteState(id=1, epoch=1, write_seq=1, locked_run_id=None)
        db.add(st); db.flush()
    return st
def lock_state(db):
    # Row-lock the singleton so every business write serializes with a running restore.
    st = db.execute(select(SiteState).where(SiteState.id == 1).with_for_update()).scalar_one_or_none()
    if not st:
        st = get_state(db)
    return st
def begin_write(db):
    # Called by every business write path: fenced while a restore holds the site.
    st = lock_state(db)
    if st.locked_run_id:
        raise HTTPException(409, '站点恢复进行中，写入暂时封闭，请稍后重试')
    st.write_seq = (st.write_seq or 0) + 1
    return st
