import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
from src.services.site import get_state, lock_state
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        if get_state(db).locked_run_id:return  # 恢复封写期间不领取新计算
        j.status='running';j.claimed_epoch=get_state(db).epoch
        db.commit()
        epoch=j.claimed_epoch
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            error=None
        except Exception as e:
            logging.exception('Analysis failed')
            result,error=None,str(e)[:990]
    with Session() as db:
        row=db.get(Job,job_id)
        st=lock_state(db)
        # 纪元栅栏：恢复切换后，恢复前领取的计算即使晚到也不得写入新站
        if row is None or row.status!='running' or row.claimed_epoch!=epoch or st.epoch!=epoch or st.locked_run_id:
            record(db,'worker','job.fenced',{'id':job_id,'reason':'站点已恢复，恢复前领取的计算结果被丢弃'})
            db.commit();return
        if error is None:
            row.result=result;row.status='completed';row.finished_at=time.time()
            record(db,'worker','job.completed',{'id':row.id})
        else:
            row.status='failed';row.error=error;row.finished_at=time.time()
            record(db,'worker','job.failed',{'id':row.id,'error':row.error})
        st.write_seq=(st.write_seq or 0)+1
        db.commit()
def tick():
    with Session() as db:
        if get_state(db).locked_run_id:return
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        st=get_state(db)
        if st.locked_run_id:return
        epoch=st.epoch
        due=list(db.scalars(select(Report.id).where(Report.enabled==True,Report.next_run<=time.time())))
    for report_id in due:
        with Session() as db:
            st=lock_state(db)
            if st.locked_run_id or st.epoch!=epoch:return  # 恢复前领取的归档不得写入新站
            r=db.get(Report,report_id)
            if not r or not r.enabled or r.next_run>time.time():continue
            d=deliver(db,r)
            if d:
                st.write_seq=(st.write_seq or 0)+1
                record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
            db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';j.claimed_epoch=None;record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
