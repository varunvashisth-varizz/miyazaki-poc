import hashlib, secrets, ipaddress, socket, re, zipfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import HTTPException
from sqlalchemy import select
from .db import Session as LoginSession, Membership, Workspace, User, Attempt, Audit, now
from .config import settings

ph = PasswordHasher()
DUMMY_HASH = ph.hash('constant-timing-dummy-password')
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def hash_password(password):
    if len(password) < 12 or len(password) > 256: raise HTTPException(422, 'Password must be 12–256 characters.')
    return ph.hash(password)
def verify(password, hashed):
    try: return ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError): return False

def audit(db, user, action, target, wid=None, detail=None):
    db.add(Audit(actor=user.id if hasattr(user, 'id') else str(user), action=action, target=str(target), workspace_id=wid, detail=detail or {}))

def identity(request, db, allow_pending=False):
    raw = request.cookies.get('session', '')
    sess = db.get(LoginSession, digest(raw))
    if not sess or now() - sess.touched > timedelta(hours=12): raise HTTPException(401, 'Sign in to continue.')
    user = db.get(User, sess.user_id)
    if not user or (sess.mfa_pending and not allow_pending): raise HTTPException(403, 'MFA verification required.')
    if user.role not in ('Super Admin','Platform Admin','Coordinator'):
        memberships = db.scalars(select(Membership).where(Membership.user_id==user.id)).all()
        if not any(db.get(Workspace,m.workspace_id).status != 'Deactivated' for m in memberships):
            raise HTTPException(403, 'Workspace deactivated or membership removed.')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), sess.csrf): raise HTTPException(403, 'Invalid CSRF token.')
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'): raise HTTPException(403, 'Untrusted origin.')
    sess.touched = now()
    return user, sess

def workspace_access(db, user, wid, write=False, admin=False):
    ws = db.scalar(select(Workspace).where((Workspace.id==wid) | (Workspace.slug==wid)))
    if not ws: raise HTTPException(404, 'Workspace not found.')
    m = db.get(Membership, (user.id, ws.id))
    if not m: raise HTTPException(404, 'Workspace not found.')
    if ws.status=='Deactivated': raise HTTPException(403, 'Workspace deactivated.')
    if admin and m.role!='Company Admin': raise HTTPException(403, 'Company Admin required.')
    if write and m.role.startswith('Coordinator'): raise HTTPException(403, 'Read/comment access only.')
    return ws, m

def require_admin(user, platform=False):
    if user.role not in (('Platform Admin',) if platform else ('Super Admin','Platform Admin')): raise HTTPException(403,'Administrator access required.')

def limited(db, key, limit=8, minutes=15):
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy import case
    key=digest(key);cutoff=now()-timedelta(minutes=minutes)
    statement=insert(Attempt).values(key=key,count=1,since=now())
    statement=statement.on_conflict_do_update(index_elements=[Attempt.key],set_={
        'count':case((Attempt.since<cutoff,1),else_=Attempt.count+1),
        'since':case((Attempt.since<cutoff,now()),else_=Attempt.since)
    }).returning(Attempt.count)
    count=db.scalar(statement)
    if count>limit:raise HTTPException(429,'Too many attempts. Please try again later.')

def safe_path(wid, name):
    if not re.fullmatch(r'[a-zA-Z0-9-]+',wid): raise HTTPException(400,'Invalid workspace.')
    base=(settings.storage()/wid).resolve()
    p=(base/name).resolve()
    if not p.is_relative_to(base): raise HTTPException(400,'Invalid path.')
    return p

def public_url(url):
    parts=urlsplit(url)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.port not in (None,80,443):
        raise ValueError('Only public HTTP/HTTPS URLs on standard ports are allowed.')
    addresses=socket.getaddrinfo(parts.hostname,parts.port or (443 if parts.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private, loopback, link-local and reserved destinations are blocked.')
    return url

def archive_safe(path):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist()
        if len(infos)>3000 or sum(i.file_size for i in infos)>100*1024*1024: raise ValueError('Archive expands beyond safe limits.')
        for i in infos:
            if i.file_size>30*1024*1024 or i.file_size/max(i.compress_size,1)>200: raise ValueError('Unsafe compression ratio.')
            if '..' in Path(i.filename).parts or i.filename.startswith('/'): raise ValueError('Unsafe archive path.')

def redact(text, names=()):
    text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]',text)
    text=re.sub(r'(?<!\w)\+?\d[\d ()-]{7,}\d', '[PHONE]',text)
    for name in names:
        if name and len(name)>1: text=re.sub(re.escape(name),'[NAME]',text,flags=re.I)
    return text
