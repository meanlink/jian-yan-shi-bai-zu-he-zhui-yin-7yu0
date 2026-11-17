"""整站恢复点：一致性快照、预览核对、封写切换、断点续作与演练对比。"""
import hashlib, json, logging, os, re, shutil, time
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select, delete, update
from src.config.database import Session, engine
from src.config.settings import BACKUP_DIR, ARTIFACT_DIR
from src.models import Dataset, Job, Report, Delivery, SiteState, RestorePoint, RestoreRun
from src.services.audit import record
from src.services.site import get_state, lock_state

TABLES = [('datasets', Dataset), ('jobs', Job), ('reports', Report), ('deliveries', Delivery)]
TABLE_LABELS = {'datasets': '数据批次', 'jobs': '分析任务', 'reports': '分发计划', 'deliveries': '归档记录'}
STEPS = ['verify', 'files', 'switch', 'cleanup']
ARTIFACT_NAME = re.compile(r'^report-\d+-delivery-\d+\.csv(\.json)?$')
DISCARD_LIMIT = 50

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()
def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str).encode()).hexdigest()
def row_dict(model, row):
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}
def point_dict(p):
    return {'id': p.id, 'name': p.name, 'status': p.status, 'created_by': p.created_by, 'created_at': p.created_at, 'captured_seq': p.captured_seq, 'counts': p.counts or {}, 'checksum': p.checksum, 'error': p.error}
def run_dict(r):
    return {'id': r.id, 'point_id': r.point_id, 'mode': r.mode, 'status': r.status, 'step': r.step, 'base_seq': r.base_seq, 'summary': r.summary or {}, 'error': r.error, 'created_by': r.created_by, 'created_at': r.created_at, 'updated_at': r.updated_at}

# ---------- 备份：与在线写入并行的一致性快照 ----------
def create_point(db, name, user):
    if db.scalar(select(RestorePoint).where(RestorePoint.name == name)):
        raise HTTPException(409, '该恢复点名称已存在，请修改名称')
    if get_state(db).locked_run_id:
        raise HTTPException(409, '站点恢复进行中，请完成后再备份')
    p = RestorePoint(name=name, status='capturing', created_by=user.email, created_at=time.time())
    db.add(p); db.flush()
    p.storage_dir = os.path.join(BACKUP_DIR, f'point-{p.id}')
    record(db, user.email, 'restore.point.create', {'id': p.id, 'name': name})
    db.commit()
    capture(p.id)
    db.refresh(p)
    return p

def read_consistent_snapshot():
    # 单事务读取：数据批次、分析、计划与归档对应同一时点，期间接入与计算不被阻塞。
    snap, seq = {}, 0
    with engine.connect() as conn:
        seq = conn.execute(select(SiteState.write_seq).where(SiteState.id == 1)).scalar() or 0
        for name, model in TABLES:
            snap[name] = [row_dict(model, r) for r in conn.scalars(select(model))]
    return snap, seq

def capture(point_id):
    with Session() as db:
        p = db.get(RestorePoint, point_id)
        try:
            snap, seq = read_consistent_snapshot()
            pdir = Path(p.storage_dir)
            shutil.rmtree(pdir, ignore_errors=True)
            (pdir / 'tables').mkdir(parents=True, exist_ok=True)
            (pdir / 'artifacts').mkdir(parents=True, exist_ok=True)
            manifest = {'id': p.id, 'name': p.name, 'created_at': p.created_at, 'captured_seq': seq, 'tables': {}, 'artifacts': []}
            for name, _ in TABLES:
                payload = json.dumps(snap[name], ensure_ascii=False, allow_nan=False).encode()
                (pdir / 'tables' / f'{name}.json').write_bytes(payload)
                manifest['tables'][name] = {'count': len(snap[name]), 'sha256': hashlib.sha256(payload).hexdigest()}
            for d in snap['deliveries']:
                for suffix in ('', '.json'):
                    fname = d['filename'] + suffix
                    src = Path(ARTIFACT_DIR) / fname
                    if not src.exists():
                        raise ValueError(f'归档附件 {fname} 缺失，无法形成一致恢复点')
                    dst = pdir / 'artifacts' / fname
                    shutil.copyfile(src, dst)
                    digest = sha256_file(dst)
                    if suffix == '' and digest != d['checksum']:
                        raise ValueError(f'归档附件 {fname} 校验不一致，备份已中止')
                    manifest['artifacts'].append({'name': fname, 'sha256': digest})
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
            (pdir / 'manifest.json').write_bytes(manifest_bytes)
            p.counts = {name: m['count'] for name, m in manifest['tables'].items()}
            p.captured_seq = seq
            p.checksum = hashlib.sha256(manifest_bytes).hexdigest()
            p.status = 'ready'
            record(db, 'system', 'restore.point.ready', {'id': p.id, 'counts': p.counts})
        except Exception as e:
            logging.exception('Restore point capture failed')
            p.status = 'failed'
            p.error = str(e)[:990]
            record(db, 'system', 'restore.point.failed', {'id': p.id, 'error': p.error})
        db.commit()

# ---------- 快照校验：附件与关联 ----------
def verify_snapshot(p):
    problems, snap = [], {}
    pdir = Path(p.storage_dir)
    try:
        manifest = json.loads((pdir / 'manifest.json').read_text())
    except Exception:
        return {'ok': False, 'problems': ['恢复点清单缺失或损坏'], 'attachments': {'total': 0, 'ok': 0}}
    for name, _ in TABLES:
        f = pdir / 'tables' / f'{name}.json'
        if not f.exists():
            problems.append(f'快照表 {TABLE_LABELS[name]} 缺失'); continue
        raw = f.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest.get('tables', {}).get(name, {}).get('sha256'):
            problems.append(f'快照表 {TABLE_LABELS[name]} 校验不一致')
        try:
            snap[name] = json.loads(raw)
        except Exception:
            problems.append(f'快照表 {TABLE_LABELS[name]} 无法解析')
    total = ok = 0
    for a in manifest.get('artifacts', []):
        total += 1
        f = pdir / 'artifacts' / a['name']
        if not f.exists():
            problems.append(f'附件 {a["name"]} 缺失')
        elif sha256_file(f) != a['sha256']:
            problems.append(f'附件 {a["name"]} 校验不一致')
        else:
            ok += 1
    if all(name in snap for name, _ in TABLES):
        ds = {r['id'] for r in snap['datasets']}
        js = {r['id'] for r in snap['jobs']}
        rs = {r['id'] for r in snap['reports']}
        for j in snap['jobs']:
            if j['dataset_id'] not in ds: problems.append(f'分析任务 #{j["id"]} 引用的数据批次不在快照中')
        for r in snap['reports']:
            if r['job_id'] not in js: problems.append(f'分发计划 #{r["id"]} 引用的分析任务不在快照中')
        for d in snap['deliveries']:
            if d['report_id'] not in rs: problems.append(f'归档记录 #{d["id"]} 引用的分发计划不在快照中')
    return {'ok': not problems, 'problems': problems[:20], 'attachments': {'total': total, 'ok': ok}}

def load_snapshot(p):
    pdir = Path(p.storage_dir)
    return {name: json.loads((pdir / 'tables' / f'{name}.json').read_text()) for name, _ in TABLES}

# ---------- 前后对比：将丢弃的后续变更 ----------
def label_for(name, row):
    if name == 'datasets': return f"#{row['id']} {row['name']}（{len(row.get('records') or [])}行）"
    if name == 'jobs': return f"#{row['id']} {row['name']}（{row['status']}）"
    if name == 'reports': return f"#{row['id']} {row['name']}（{'启用' if row['enabled'] else '暂停'}）"
    return f"#{row['id']} {row['filename']}"

def diff_snapshot(db, p):
    snap = load_snapshot(p)
    diff = {'tables': {}, 'discard': {}, 'restore_counts': {name: len(snap[name]) for name, _ in TABLES}}
    for name, model in TABLES:
        current = {r['id']: r for r in (row_dict(model, x) for x in db.scalars(select(model)))}
        before = {r['id']: r for r in snap[name]}
        # claimed_epoch 是隔离栅栏的内部状态，不计入业务差异
        for row in list(current.values()) + list(before.values()):
            row.pop('claimed_epoch', None)
        new_ids = [i for i in current if i not in before]
        gone_ids = [i for i in before if i not in current]
        changed_ids = [i for i in current if i in before and canonical(current[i]) != canonical(before[i])]
        diff['tables'][name] = {'current': len(current), 'snapshot': len(before), 'new': len(new_ids), 'missing': len(gone_ids), 'changed': len(changed_ids)}
        items = [{'id': i, 'kind': '新增', 'label': label_for(name, current[i])} for i in new_ids]
        items += [{'id': i, 'kind': '已修改', 'label': label_for(name, current[i])} for i in changed_ids]
        diff['discard'][name] = {'total': len(items), 'items': items[:DISCARD_LIMIT]}
    return diff

# ---------- 预览与确认 ----------
def preview(db, point_id, user):
    p = db.get(RestorePoint, point_id)
    if not p or p.status != 'ready': raise HTTPException(404, '恢复点不存在或尚未就绪')
    st = get_state(db)
    if st.locked_run_id: raise HTTPException(409, '已有恢复操作进行中，请稍后再预览')
    run = RestoreRun(point_id=p.id, mode='restore', status='preview', step='', base_seq=st.write_seq, created_by=user.email, created_at=time.time(), updated_at=time.time())
    run.summary = {'point': point_dict(p), 'diff': diff_snapshot(db, p)}
    db.add(run); db.flush()
    record(db, user.email, 'restore.preview', {'run': run.id, 'point': p.id, 'base_seq': st.write_seq})
    db.commit()
    return run

def confirm(db, run_id, user):
    run = db.get(RestoreRun, run_id)
    if not run or run.mode != 'restore': raise HTTPException(404, '恢复操作不存在')
    if run.status != 'preview': raise HTTPException(409, '该预览已确认或已结束，请重新预览')
    st = lock_state(db)
    if st.locked_run_id: raise HTTPException(409, '已有恢复操作进行中')
    if st.write_seq != run.base_seq:
        raise HTTPException(409, '预览生成后站点又有新写入，旧预览已作废，请重新预览')
    st.locked_run_id = run.id
    run.status = 'restoring'; run.step = 'verify'; run.updated_at = time.time()
    record(db, user.email, 'restore.confirm', {'run': run.id, 'point': run.point_id})
    db.commit()
    execute_restore(run.id)
    return fresh_run(run.id)

def resume(db, run_id, user):
    run = db.get(RestoreRun, run_id)
    if not run or run.mode != 'restore': raise HTTPException(404, '恢复操作不存在')
    if run.status not in ('restoring', 'failed'): raise HTTPException(409, '仅中断或失败的恢复可以继续')
    st = lock_state(db)
    if st.locked_run_id and st.locked_run_id != run.id: raise HTTPException(409, '已有恢复操作进行中')
    if run.status == 'failed' and st.write_seq != run.base_seq:
        raise HTTPException(409, '失败后站点已有新写入，请重新预览确认')
    st.locked_run_id = run.id
    run.status = 'restoring'
    if run.step not in STEPS: run.step = 'verify'
    run.updated_at = time.time()
    record(db, user.email, 'restore.resume', {'run': run.id, 'step': run.step})
    db.commit()
    execute_restore(run.id)
    return fresh_run(run.id)

def fresh_run(run_id):
    with Session() as db:
        return run_dict(db.get(RestoreRun, run_id))

# ---------- 切换执行：分步、可续作、幂等 ----------
def execute_restore(run_id):
    with Session() as db:
        run = db.get(RestoreRun, run_id)
        p = db.get(RestorePoint, run.point_id)
        try:
            while run.step in STEPS:
                if run.step == 'verify':
                    rep = verify_snapshot(p)
                    if not rep['ok']:
                        raise ValueError('快照校验未通过：' + '；'.join(rep['problems'][:3]))
                    run.summary = {**(run.summary or {}), 'verification': rep}
                    run.step = 'files'
                elif run.step == 'files':
                    restore_files(p, run)
                    run.step = 'switch'
                elif run.step == 'switch':
                    switch(db, p, run)  # 单事务原子切换，内部提交
                    continue
                elif run.step == 'cleanup':
                    trash_extra_files(p, run)
                    st = lock_state(db)
                    if st.locked_run_id == run.id: st.locked_run_id = None
                    run.status = 'completed'; run.step = 'done'
                    record(db, 'system', 'restore.completed', {'run': run.id, 'point': p.id})
                run.updated_at = time.time()
                db.commit()
        except Exception as e:
            logging.exception('Restore run %s failed', run_id)
            db.rollback()
            fail_run(db, run_id, str(e)[:990])

def fail_run(db, run_id, error):
    run = db.get(RestoreRun, run_id)
    st = lock_state(db)
    if st.locked_run_id == run_id: st.locked_run_id = None
    # 切换未提交即失败：原站不变，仅释放封写并回收被挡下的在途计算
    db.execute(update(Job).where(Job.status == 'running').values(status='queued', claimed_epoch=None))
    run.status = 'failed'; run.error = error; run.updated_at = time.time()
    record(db, 'system', 'restore.failed', {'run': run_id, 'point': run.point_id, 'error': error})
    db.commit()

def switch(db, p, run):
    snap = load_snapshot(p)
    st = lock_state(db)
    db.execute(delete(Delivery)); db.execute(delete(Report))
    db.execute(delete(Job)); db.execute(delete(Dataset))
    cols = {name: {c.name for c in model.__table__.columns} for name, model in TABLES}
    for r in snap['datasets']:
        db.add(Dataset(**{k: v for k, v in r.items() if k in cols['datasets']}))
    for r in snap['jobs']:
        row = {k: v for k, v in r.items() if k in cols['jobs']}
        row['claimed_epoch'] = None
        if row.get('status') == 'running': row['status'] = 'queued'
        db.add(Job(**row))
    for r in snap['reports']:
        row = {k: v for k, v in r.items() if k in cols['reports']}
        row['enabled'] = False  # 恢复的计划先暂停，重新启用后才继续
        db.add(Report(**row))
    for r in snap['deliveries']:
        db.add(Delivery(**{k: v for k, v in r.items() if k in cols['deliveries']}))
    st.epoch = (st.epoch or 1) + 1  # 新纪元：恢复前领取的计算与归档即使晚到也被隔离
    st.write_seq = (st.write_seq or 0) + 1
    run.step = 'cleanup'; run.updated_at = time.time()
    record(db, 'system', 'restore.switched', {'run': run.id, 'point': p.id, 'epoch': st.epoch})
    db.commit()

def restore_files(p, run):
    # 只补不删：缺失或被篡改的附件从备份原子落位，重试不重复替换
    pdir = Path(p.storage_dir)
    manifest = json.loads((pdir / 'manifest.json').read_text())
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    for a in manifest.get('artifacts', []):
        src = pdir / 'artifacts' / a['name']
        dst = Path(ARTIFACT_DIR) / a['name']
        if dst.exists() and sha256_file(dst) == a['sha256']:
            continue
        tmp = Path(ARTIFACT_DIR) / f'.restore-{run.id}-{a["name"]}'
        shutil.copyfile(src, tmp)
        if sha256_file(tmp) != a['sha256']:
            tmp.unlink(missing_ok=True)
            raise ValueError(f'备份附件 {a["name"]} 校验不一致，恢复中止')
        os.replace(tmp, dst)

def trash_extra_files(p, run):
    # 切换完成后移走快照之后的归档文件；失败不阻断，仅留孤立文件
    try:
        manifest = json.loads((Path(p.storage_dir) / 'manifest.json').read_text())
        keep = {a['name'] for a in manifest.get('artifacts', [])}
        trash = Path(ARTIFACT_DIR) / f'.trash-run-{run.id}'
        for f in Path(ARTIFACT_DIR).iterdir():
            if f.is_file() and ARTIFACT_NAME.match(f.name) and f.name not in keep:
                trash.mkdir(exist_ok=True)
                os.replace(f, trash / f.name)
    except Exception:
        logging.exception('Post-restore artifact cleanup failed; orphaned files remain')

# ---------- 演练：不动线上，核对前后数据 ----------
def drill(db, point_id, user):
    p = db.get(RestorePoint, point_id)
    if not p or p.status != 'ready': raise HTTPException(404, '恢复点不存在或尚未就绪')
    st = get_state(db)
    if st.locked_run_id: raise HTTPException(409, '站点恢复进行中，请完成后再演练')
    run = RestoreRun(point_id=p.id, mode='drill', status='restoring', step='verify', base_seq=st.write_seq, created_by=user.email, created_at=time.time(), updated_at=time.time())
    db.add(run); db.flush()
    record(db, user.email, 'restore.drill', {'run': run.id, 'point': p.id})
    db.commit()
    try:
        rep = verify_snapshot(p)
        run.summary = {'point': point_dict(p), 'verification': rep, 'diff': diff_snapshot(db, p)}
        run.status = 'completed' if rep['ok'] else 'failed'
        run.error = '' if rep['ok'] else '；'.join(rep['problems'][:3])
    except Exception as e:
        logging.exception('Drill failed')
        run.status = 'failed'; run.error = str(e)[:990]
    run.step = 'done'; run.updated_at = time.time()
    record(db, user.email, 'restore.drill.done', {'run': run.id, 'status': run.status})
    db.commit()
    return run

def resume_interrupted():
    with Session() as db:
        ids = list(db.scalars(select(RestoreRun.id).where(RestoreRun.mode == 'restore', RestoreRun.status == 'restoring')))
    for run_id in ids:
        try:
            execute_restore(run_id)
        except Exception:
            logging.exception('Failed to resume restore run %s', run_id)
