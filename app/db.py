from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (create_engine, String, Text, DateTime, Integer, Float, Boolean,
                        ForeignKey, UniqueConstraint, ForeignKeyConstraint, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from .config import settings


def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid4())
class Base(DeclarativeBase): pass
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=8, max_overflow=4)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

class Workspace(Base):
    __tablename__ = 'workspaces'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    slug: Mapped[str] = mapped_column(String(90), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    name_ja: Mapped[str] = mapped_column(String(200), default='')
    status: Mapped[str] = mapped_column(String(30), default='Invited')
    language: Mapped[str] = mapped_column(String(5), default='ja')
    industry: Mapped[str] = mapped_column(String(100), default='Manufacturing')
    size_band: Mapped[str] = mapped_column(String(50), default='')
    token_budget: Mapped[int] = mapped_column(Integer, default=settings.token_budget)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default='Member')
    language: Mapped[str] = mapped_column(String(5), default='ja')
    mfa_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery: Mapped[list] = mapped_column(JSONB, default=list)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)

class Membership(Base):
    __tablename__ = 'memberships'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    role: Mapped[str] = mapped_column(String(30))

class Session(Base):
    __tablename__ = 'sessions'
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    csrf: Mapped[str] = mapped_column(String(64))
    touched: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    mfa_pending: Mapped[bool] = mapped_column(Boolean, default=False)

class Attempt(Base):
    __tablename__ = 'attempts'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Record(Base):
    """Versioned workspace resources; kind is a server-controlled closed enumeration."""
    __tablename__ = 'records'
    __table_args__ = (UniqueConstraint('workspace_id', 'id'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300), default='')
    status: Mapped[str] = mapped_column(String(40), default='Draft')
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(36), default='system')
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Revision(Base):
    __tablename__ = 'revisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    record_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    actor: Mapped[str] = mapped_column(String(36))
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Chunk(Base):
    __tablename__ = 'chunks'
    __table_args__ = (ForeignKeyConstraint(['workspace_id', 'source_id'], ['records.workspace_id', 'records.id']),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    content: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(400), default='')
    embedding: Mapped[list | None] = mapped_column(Vector(settings.embedding_dimension), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), default=settings.embedding_model)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Library(Base):
    __tablename__ = 'library'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(300))
    title_ja: Mapped[str] = mapped_column(String(300), default='')
    stage: Mapped[str] = mapped_column(String(100))
    horizon: Mapped[str] = mapped_column(String(5), default='H1')
    level: Mapped[str] = mapped_column(String(5), default='L1')
    entry: Mapped[str] = mapped_column(String(50), default='Software only')
    status: Mapped[str] = mapped_column(String(30), default='Draft')
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)

class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default='Queued')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(200), default='Queued')
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str] = mapped_column(Text, default='')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel: Mapped[bool] = mapped_column(Boolean, default=False)
    operation_key: Mapped[str | None] = mapped_column(String(150), unique=True, nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Usage(Base):
    __tablename__ = 'model_calls'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    feature: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    elapsed: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default='Reserved')
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
