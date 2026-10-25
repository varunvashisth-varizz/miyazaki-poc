import json, re
from datetime import timedelta
from sqlalchemy import select, func
from fastapi import HTTPException
from .db import Record, Revision, Workspace, Chunk, User, Membership, Usage, now, uid
from .security import audit
from .config import settings

SECTIONS=['overview','products','markets','manufacturing','supply_chain','competitive','opportunities','questions']
REQUIRED={
 'overview':['employees','plants','industry'], 'products':['product','materials','function'],
 'markets':['customers','markets'], 'manufacturing':['process','shifts','certifications'],
 'supply_chain':['suppliers','partners'], 'competitive':['differentiators'],
 'opportunities':['opportunities'], 'questions':['open_questions']}
KINDS={'fact','product','source','chat','message','workflow','document','usecase','feedback','notification','consent','invitation','reset','outbox','pending','deletion','comment','template','assessment'}
PRIVATE={'chat','message','document','source','workflow','fact','product','usecase'}

def serial(obj):
    return {c.name: getattr(obj,c.name).isoformat() if hasattr(getattr(obj,c.name),'isoformat') else getattr(obj,c.name) for c in obj.__table__.columns if c.name not in ('password','mfa_secret','recovery','embedding')}

def record(db,wid,id,kind=None):
    q=select(Record).where(Record.workspace_id==wid,Record.id==id)
    if kind:q=q.where(Record.kind==kind)
    r=db.scalar(q)
    if not r:raise HTTPException(404,'Item not found.')
    return r

def records(db,wid,kind):
    return db.scalars(select(Record).where(Record.workspace_id==wid,Record.kind==kind).order_by(Record.updated.desc())).all()

def snapshot(db,r,actor):
    db.add(Revision(workspace_id=r.workspace_id,record_id=r.id,version=r.version,snapshot=serial(r),actor=actor))

def update(db,r,actor,data=None,title=None,status=None,version=None):
    # Callers obtain a row lock before mutations to make optimistic versions effective.
    if version is not None and r.version!=version: raise HTTPException(409,'This item changed; refresh and review again.')
    snapshot(db,r,actor)
    if data is not None:r.data={**r.data,**data}
    if title is not None:r.title=title
    if status is not None:r.status=status
    r.version+=1;r.updated=now();db.flush();return r

def invalidate(db,wid):
    ws=db.get(Workspace,wid);ws.revision+=1
    for ch in records(db,wid,'chat'):
        ch.data={**ch.data,'summary':'','summary_revision':ws.revision}

def propose_fact(db,wid,actor,data):
    if data.get('section') not in SECTIONS:raise HTTPException(422,'Unknown profile section.')
    if data.get('provenance') not in ('Stated','Sourced','Inferred'):raise HTTPException(422,'Invalid provenance.')
    if not 0<=float(data.get('confidence',0))<=1:raise HTTPException(422,'Confidence must be 0–1.')
    evidence=data.get('sources',[])
    for ref in evidence:record(db,wid,ref)
    same=[f for f in records(db,wid,'fact') if f.data.get('key')==data.get('key') and f.status!='Rejected']
    data={**data,'conflict':any(f.data.get('value')!=data.get('value') for f in same)}
    r=Record(workspace_id=wid,kind='fact',title=str(data.get('key','Fact'))[:300],status='Proposed',data=data,created_by=actor)
    db.add(r);db.flush();return r

def forbidden_values(db,wid):
    return [str(f.data.get('value','')) for f in records(db,wid,'fact') if f.status in ('Rejected','Disputed','Superseded') and f.data.get('value')]

def clean_context(text,banned):
    # Drop whole evidence blocks containing rejected values, including historic messages.
    return '' if any(v.casefold() in text.casefold() for v in banned) else text

def knowledge(db,wid,query,vector=None,selected=None):
    banned=forbidden_values(db,wid)
    q=select(Chunk).join(Record,(Record.id==Chunk.source_id)&(Record.workspace_id==Chunk.workspace_id)).where(Chunk.workspace_id==wid,Chunk.active==True,Record.status=='Ready')
    if selected is not None:q=q.where(Chunk.source_id.in_(selected))
    allowed=q
    ranked=[]
    if vector is not None:
        ranked=db.scalars(q.where(Chunk.embedding_model==settings.embedding_model,Chunk.embedding.is_not(None)).order_by(Chunk.embedding.cosine_distance(vector)).limit(15)).all()
    words=re.findall(r'[\w-]+',query)[:12]
    from sqlalchemy import or_
    keyword=db.scalars(allowed.where(or_(*[Chunk.content.ilike('%'+w.replace('%','\\%').replace('_','\\_')+'%',escape='\\') for w in words])).limit(15)).all() if words else []
    scores={};byid={}
    for items in (ranked,keyword):
        for i,c in enumerate(items): scores[c.id]=scores.get(c.id,0)+1/(60+i);byid[c.id]=c
    return [byid[id] for id in sorted(scores,key=scores.get,reverse=True) if clean_context(byid[id].content,banned)][:6]

def context(db,wid,chat=None,query='',vector=None,selection=None):
    selection=selection or {};banned=forbidden_values(db,wid);handles={};parts=[]
    ws=db.get(Workspace,wid)
    if selection.get('profile',True):
        parts.append('CONFIRMED WORKSPACE IDENTITY: '+json.dumps({'name_en':ws.name,'name_ja':ws.name_ja,'synthetic_demo':ws.data.get('synthetic',False)},ensure_ascii=False)+' Use these names exactly. Do not invent or add a legal company prefix.')
        facts=[f for f in records(db,wid,'fact') if f.status in (('Confirmed',) if selection.get('confirmed_only') else ('Confirmed','Proposed'))]
        facts.sort(key=lambda f:f.status!='Confirmed')
        for f in facts:
            if selection.get('sections') is not None and f.data.get('section') not in selection['sections']:continue
            handle='[F:'+f.id+']';value=clean_context(str(f.data.get('value','')),banned)
            if not value:continue
            parts.append(f'{handle} {f.status} {f.data.get("provenance")}: {f.title}: {value}');handles[handle]={'kind':'fact','id':f.id,'label':f.title}
    else:parts.append('PROFILE IS DISABLED. Explicitly state that you are answering without the company profile.')
    if selection.get('knowledge',True):
        for c in knowledge(db,wid,query,vector,selection.get('sources')):
            h='[S:'+c.id+']';parts.append(h+' SOURCE DATA '+c.location+'\n'+c.content);handles[h]={'kind':'source','id':c.source_id,'chunk_id':c.id,'label':c.location}
    if chat and selection.get('workflow',True) and chat.data.get('workflow_id'):
        w=record(db,wid,chat.data['workflow_id'],'workflow');parts.append('WORKFLOW DATA: '+json.dumps(w.data,ensure_ascii=False))
    # Profile-off excludes historic assistant replies and summaries derived from profile context.
    history=[]
    if chat and selection.get('profile',True):
        messages=[m for m in reversed(records(db,wid,'message')) if m.data.get('chat_id')==chat.id]
        for m in messages[-8:]:
            content=clean_context(m.data.get('content',''),banned)
            if content:history.append({'role':m.data.get('role','user'),'content':content[:2400]})
        if chat.data.get('summary') and chat.data.get('summary_revision')==ws.revision:parts.append('EARLIER HISTORY SUMMARY DATA: '+clean_context(chat.data['summary'],banned))
    return '\n\n'.join(parts)[:20000],handles,history

def completeness(db,wid):
    facts=records(db,wid,'fact');result={};gaps=[]
    for section,keys in REQUIRED.items():
        present={f.data.get('key') for f in facts if f.status=='Confirmed' and f.data.get('section')==section and str(f.data.get('value','')).strip()}
        missing=[k for k in keys if k not in present];result[section]=round(100*(len(keys)-len(missing))/len(keys))
        for k in missing:gaps.append({'section':section,'key':k,'workflow':'B1' if section=='overview' else 'B4' if section=='manufacturing' else 'B3','question':'Please describe '+k.replace('_',' ')})
    return {'sections':result,'overall':round(sum(result.values())/8),'gaps':gaps,'top_gaps':gaps[:3]}

def mail(db,wid,recipient,subject,body,language='ja'):
    r=Record(workspace_id=wid,kind='outbox',title=subject,status='Queued',data={'recipient':recipient,'body':body,'language':language,'backend':settings.mail_backend})
    db.add(r);return r

def notify(db,wid,user_id,event,title,target=''):
    db.add(Record(workspace_id=wid,kind='notification',title=title,status='Unread',data={'recipient':user_id,'event':event,'target':target}))

def enqueue(db,wid,kind,data,key=None):
    from .db import Job
    if key:
        existing=db.scalar(select(Job).where(Job.operation_key==key))
        if existing:return existing
    j=Job(workspace_id=wid,kind=kind,data=data,operation_key=key);db.add(j);db.flush();return j
