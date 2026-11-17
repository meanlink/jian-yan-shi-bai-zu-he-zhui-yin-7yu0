from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import RestorePoint, RestoreRun
from src.schemas.restore import RestorePointInput
from src.middlewares.auth import admin_only
from src.services import restore
router=APIRouter()
@router.get('/restore-points')
def list_points(db=Depends(get_db),u=Depends(admin_only)):
    return [restore.point_dict(p) for p in db.scalars(select(RestorePoint).order_by(RestorePoint.id.desc()))]
@router.post('/restore-points',status_code=201)
def create_point(data:RestorePointInput,db=Depends(get_db),u=Depends(admin_only)):
    return restore.point_dict(restore.create_point(db,data.name.strip(),u))
@router.get('/restore-points/{id}')
def get_point(id:int,db=Depends(get_db),u=Depends(admin_only)):
    p=db.get(RestorePoint,id)
    if not p:raise HTTPException(404,'恢复点不存在')
    return restore.point_dict(p)
@router.post('/restore-points/{id}/preview',status_code=201)
def preview(id:int,db=Depends(get_db),u=Depends(admin_only)):
    return restore.run_dict(restore.preview(db,id,u))
@router.post('/restore-points/{id}/drill',status_code=201)
def drill(id:int,db=Depends(get_db),u=Depends(admin_only)):
    return restore.run_dict(restore.drill(db,id,u))
@router.get('/restore-runs')
def list_runs(db=Depends(get_db),u=Depends(admin_only)):
    return [restore.run_dict(r) for r in db.scalars(select(RestoreRun).order_by(RestoreRun.id.desc()).limit(50))]
@router.get('/restore-runs/{id}')
def get_run(id:int,db=Depends(get_db),u=Depends(admin_only)):
    r=db.get(RestoreRun,id)
    if not r:raise HTTPException(404,'恢复操作不存在')
    return restore.run_dict(r)
@router.post('/restore-runs/{id}/confirm')
def confirm(id:int,db=Depends(get_db),u=Depends(admin_only)):
    return restore.confirm(db,id,u)
@router.post('/restore-runs/{id}/resume')
def resume(id:int,db=Depends(get_db),u=Depends(admin_only)):
    return restore.resume(db,id,u)
