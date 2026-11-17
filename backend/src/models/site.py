from sqlalchemy import String, JSON, Double, Integer, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class SiteState(Base):
    __tablename__ = 'site_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    write_seq: Mapped[int] = mapped_column(BigInteger, default=1)
    locked_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
class RestorePoint(Base):
    __tablename__ = 'restore_points'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default='capturing')
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[float] = mapped_column(Double)
    captured_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), default='')
    storage_dir: Mapped[str] = mapped_column(String(300), default='')
    error: Mapped[str] = mapped_column(String(1000), default='')
class RestoreRun(Base):
    __tablename__ = 'restore_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    point_id: Mapped[int] = mapped_column(ForeignKey('restore_points.id'))
    mode: Mapped[str] = mapped_column(String(20), default='restore')
    status: Mapped[str] = mapped_column(String(20), default='preview')
    step: Mapped[str] = mapped_column(String(20), default='')
    base_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
