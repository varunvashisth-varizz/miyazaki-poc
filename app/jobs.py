import json, threading, time, hashlib, difflib
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select, update, delete
from .db import SessionLocal, Job, Record, Chunk, User, Membership, Workspace, Session as LoginSession, Usage, now, uid
from .services import record, records, enqueue, propose_fact, context, invalidate, notify, mail, snapshot
from .config import settings
from . import ai
from .ingestion import crawl,parse_file,chunk_text,html_text,SUSPICIOUS
from .security import safe_path

STOP=threading.Event();scheduler=None
pools={};busy={'io':False,'ai':False}
AI_KINDS={'index','analyse','document','rewrite','summarize','recommend','charter','translate','capture','interview','workflow_plan','translate_output'}

def progress(id,percentage,stage):
    with SessionLocal.begin() as db:
        j=db.get(Job,id)
        if j.cancel:raise ValueError('Cancelled by user.')
        j.progress=percentage;j.stage=stage;j.lease=now()+timedelta(minutes=10)

def process(id):
    with SessionLocal() as db:
        j=db.get(Job,id);wid=j.workspace_id;d=j.data
        if j.cancel:raise ValueError('Cancelled by user.')
        if j.kind=='ingest':
            source=record(db,wid,d['source_id'],'source')
            if d.get('url') or d.get('fixture'):
                pages=crawl(d.get('url',''),limit=d.get('limit',20),fixture=d.get('fixture',False),injection=d.get('injection',False),progress=lambda n,s:progress(id,min(60,n*3),s))
                pieces=[(p['url'],p['text']) for p in pages];flagged=any(p['flagged'] for p in pages)
                source.data={**source.data,'snapshot':any(p['snapshot'] for p in pages),'pages':[p['url'] for p in pages]}
            else:
                pieces=parse_file(safe_path(wid,source.data['path']));flagged=any(SUSPICIOUS.search(t) for _,t in pieces)
            text='\n'.join(t for _,t in pieces)
            if source.data.get('previous_source_id'):
                previous=record(db,wid,source.data['previous_source_id'],'source')
                source.data={**source.data,'diff':'\n'.join(difflib.unified_diff(previous.data.get('text','').splitlines(),text.splitlines(),fromfile='Previous snapshot',tofile='New snapshot'))}
            source.data={**source.data,'text':text,'flagged':flagged,'hash':hashlib.sha256(text.encode()).hexdigest(),'summary':text[:600],'tags':['Japanese' if any('\u3040'<=c<='\u9fff' for c in text) else 'English']}
            db.execute(delete(Chunk).where(Chunk.workspace_id==wid,Chunk.source_id==source.id))
            if flagged:
                source.status='Quarantined';db.commit();return {'source_id':source.id,'warning':'Instruction-like source content quarantined and excluded from AI context.'}
            for location,text in pieces:
                for block in chunk_text(text):db.add(Chunk(workspace_id=wid,source_id=source.id,location=location,content=block))
            source.status='Ready';db.flush()
            enqueue(db,wid,'index',{'source_id':source.id},'index:'+source.id+':'+str(source.version))
            enqueue(db,wid,'analyse',{'source_id':source.id},'analyse:'+source.id+':'+str(source.version))
            db.commit();return {'source_id':source.id}
        if j.kind=='index':
            s=record(db,wid,d['source_id'],'source')
            if s.status!='Ready':return {'skipped':'Source is not eligible.'}
            chunks=db.scalars(select(Chunk).where(Chunk.workspace_id==wid,Chunk.source_id==s.id,Chunk.active==True)).all()
            for i,c in enumerate(chunks):
                vector=ai.provider.embed([c.content])[0];db.refresh(s)
                if s.status!='Ready':return {'skipped':'Source deleted.'}
                c.embedding=vector;c.embedding_model=settings.embedding_model
                progress(id,round(95*(i+1)/max(len(chunks),1)),'Embedding source chunks');db.commit()
            return {'chunks':len(chunks)}
        if j.kind=='analyse':
            s=record(db,wid,d['source_id'],'source')
            if s.status!='Ready':return {'skipped':'Source is not eligible.'}
            prompt='Extract company facts into JSON. section must be one of overview, products, markets, manufacturing, supply_chain, competitive, opportunities, questions. Use sourced facts only, never personal names. source_id is '+s.id+'. Product potential is Inferred. SOURCE DATA:\n'+s.data.get('text','')[:14000]
            raw=ai.generate(db,wid,'analysis',[{'role':'system','content':ai.POLICY},{'role':'user','content':prompt}],ai.Extraction.model_json_schema(),1500)
            result=ai.Extraction.model_validate_json(raw)
            progress(id,85,'Validating proposed facts');db.refresh(s)
            if s.status!='Ready':return {'skipped':'Source deleted.'}
            ids=[]
            for f in result.facts:
                if f.section not in ('overview','products','markets','manufacturing','supply_chain','competitive','opportunities','questions'):continue
                values=f.model_dump();values['sources']=[s.id];values['provenance']='Inferred' if f.provenance=='Inferred' else 'Sourced'
                existing=[x for x in records(db,wid,'fact') if x.data.get('value')==f.value and s.id in x.data.get('sources',[])]
                if not existing:ids.append(propose_fact(db,wid,'company_analyst',values).id)
            for p in result.products:
                name=str(p.get('name',p.get('title','Product')))[:300]
                if not any(x.title==name for x in records(db,wid,'product')):db.add(Record(workspace_id=wid,kind='product',title=name,data={**p,'source_id':s.id,'provenance':'Sourced'},created_by='company_analyst'))
            db.commit();return {'proposed_facts':ids}
        if j.kind in ('document','rewrite','translate','charter'):
            doc=record(db,wid,d['document_id'],'document');job_version=doc.version
            ctxt,handles,_=context(db,wid,query=d.get('prompt',doc.title),selection={**d.get('context',{}),'confirmed_only':True})
            lang=d.get('language',doc.data.get('language','ja'))
            prompt=f'Write in {lang}. Use the confirmed workspace name exactly; never invent or translate its proper name. Target length: '+str(d.get('length','600 words'))+'. Approved outline: '+str(d.get('outline',''))+'\n'+d.get('prompt',doc.title)+'\nEvery business statement needs a supplied evidence handle or an AI assumption, verify marker. Return Markdown only.\nEVIDENCE DATA:\n'+ctxt
            if d.get('selection'):prompt+='\nSELECTED TEXT DATA:\n'+d['selection'][:12000]
            out=ai.generate(db,wid,j.kind,[{'role':'system','content':ai.POLICY},{'role':'user','content':prompt}],maximum=1400)
            if not ai.valid_citations(out,handles):raise ValueError('Generated citation was not in the authorised context; regenerate the draft.')
            try:ai.reject_unverified_values(db,wid,out)
            except ValueError:
                excluded=[str(f.data.get('value','')) for f in records(db,wid,'fact') if f.status in ('Proposed','Rejected','Disputed','Superseded') and f.data.get('key') in ('certifications','certification','revenue','annual_revenue','turnover','market_share')]
                correction='Correct this draft using ONLY CONFIRMED EVIDENCE below. Remove every unsupported certification/revenue assertion. Do not mention these unresolved values: '+json.dumps(excluded,ensure_ascii=False)+'\nCONFIRMED EVIDENCE DATA:\n'+ctxt+'\nDRAFT TO CORRECT:\n'+out[:6000]
                out=ai.generate(db,wid,'document_correction',[{'role':'system','content':ai.POLICY},{'role':'user','content':correction}],maximum=1400)
                ai.reject_unverified_values(db,wid,out)
                if not ai.valid_citations(out,handles):raise ValueError('Invalid citation after draft correction; no draft published.')
            progress(id,90,'Saving draft with evidence markers');db.refresh(doc)
            if doc.version!=job_version:raise ValueError('Document changed during generation. Retry against the current version.')
            snapshot(db,doc,d.get('actor','ai'))
            doc.data={**doc.data,'content':ai.ground_output(out,handles,lang),'citations':handles,'language':lang,'request':d,'generated':True}
            doc.status='Draft';doc.version+=1
            if d.get('actor'):notify(db,wid,d['actor'],'document_ready','Document ready',doc.id)
            db.commit();return {'document_id':doc.id}
        if j.kind=='capture':
            origin=record(db,wid,d['origin_id']);content=str(origin.data.get('content',''))[:10000]
            if not content.strip():return {'facts':[]}
            prompt='Extract only explicit company facts from this input in its ORIGINAL language. Do not infer revenue, certification, customers, forecasts or names of people. section must use the provided schema sections. Return no facts when nothing new is explicitly stated. INPUT DATA:\n'+content
            raw=ai.generate(db,wid,'fact_capture',[{'role':'system','content':ai.POLICY},{'role':'user','content':prompt}],ai.Extraction.model_json_schema(),900)
            extracted=ai.Extraction.model_validate_json(raw);ids=[]
            for f in extracted.facts:
                if f.section not in ('overview','products','markets','manufacturing','supply_chain','competitive','opportunities','questions'):continue
                if any(x.data.get('key')==f.key and x.data.get('value')==f.value for x in records(db,wid,'fact')):continue
                data=f.model_dump();data['sources']=[origin.id];data['provenance']='Stated' if origin.kind=='message' and origin.data.get('role')=='user' and f.value.casefold() in content.casefold() else 'Inferred'
                ids.append(propose_fact(db,wid,origin.created_by,data).id)
            db.commit();return {'proposed_facts':ids}
        if j.kind=='interview':
            w=record(db,wid,d['workflow_id'],'workflow');steps=json.loads(json.dumps(w.data['steps']));step=next(x for x in steps if x['id']==d['step_id'])
            if len(step['questions'])>=10:return {'skipped':'Question set already has ten questions.'}
            schema={'type':'object','properties':{'questions':{'type':'array','items':{'type':'object','properties':{'key':{'type':'string'},'text':{'type':'string'},'text_ja':{'type':'string'}},'required':['key','text','text_ja']},'minItems':5,'maxItems':5}},'required':['questions']}
            raw=ai.generate(db,wid,'interview',[{'role':'system','content':ai.POLICY},{'role':'user','content':'Produce five useful bilingual follow-up questions that depend on the following answers. Return schema JSON. ANSWERS DATA:\n'+json.dumps(step['questions'],ensure_ascii=False)}],schema,1100)
            questions=json.loads(raw).get('questions',[])
            if len(questions)!=5 or any(not all(k in q for k in ['key','text','text_ja']) for q in questions):raise ValueError('Invalid adaptive question set.')
            db.refresh(w);steps=json.loads(json.dumps(w.data['steps']));step=next(x for x in steps if x['id']==d['step_id'])
            if len(step['questions'])==5:
                for i,q in enumerate(questions):step['questions'].append({'key':'followup_'+str(i+1),'text':q['text'],'text_ja':q['text_ja'],'answer':'','unknown':False,'assigned_to':step['owner']})
                snapshot(db,w,'interviewer');w.data={**w.data,'steps':steps};w.version+=1;db.commit()
            return {'questions':len(step['questions'])}
        if j.kind=='workflow_plan':
            ctxt,_,_=context(db,wid,selection={'knowledge':False})
            for w in records(db,wid,'workflow'):
                if w.status!='Proposed':continue
                explanation=ai.generate(db,wid,'workflow_planner',[{'role':'system','content':ai.POLICY},{'role':'user','content':'In two short sentences, explain in Japanese and English why this workflow closes a gap. Do not invent facts. WORKFLOW: '+w.title+'\nPROFILE DATA:\n'+ctxt}],maximum=200)
                w.data={**w.data,'rationale':explanation,'rationale_ja':explanation,'question_count':sum(len(s.get('questions',[])) for s in w.data['steps']),'upload_count':sum(s['type']=='upload' for s in w.data['steps'])};db.commit()
            return {'planned':True}
        if j.kind=='translate_output':
            target=record(db,wid,d['target_id']);lang=d['language'];original=str(target.data.get('value',target.data.get('content',target.title)))
            translated=ai.generate(db,wid,'translation',[{'role':'system','content':ai.POLICY},{'role':'user','content':'Translate into '+lang+'. Preserve numbers, product terms and citation handles. Final translation only. INPUT DATA:\n'+original}],maximum=1400)
            snapshot(db,target,d['actor']);target.data={**target.data,'translations':{**target.data.get('translations',{}),lang:translated},'translation_notice':'Translated by AI'};target.version+=1;db.commit();return {'target_id':target.id,'language':lang}
        if j.kind=='summarize':
            chat=record(db,wid,d['chat_id'],'chat');ws=db.get(Workspace,wid);rev=ws.revision
            ctxt,handles,history=context(db,wid,chat)
            from .services import forbidden_values,clean_context
            banned=forbidden_values(db,wid)
            older=[x for x in reversed(records(db,wid,'message')) if x.data.get('chat_id')==chat.id][:-8]
            history=[{'role':x.data.get('role','user'),'content':clean_context(x.data.get('content',''),banned)} for x in older]
            prior=clean_context(chat.data.get('summary',''),banned) if chat.data.get('summary_revision')==rev else ''
            history=[{'role':'user','content':'Prior summary: '+prior}]+history[-20:]
            out=ai.generate(db,wid,'summary',[{'role':'system','content':ai.POLICY},{'role':'user','content':'Summarize the following history without adding facts.\n'+json.dumps(history,ensure_ascii=False)}],maximum=300)
            db.refresh(ws)
            if rev==ws.revision:chat.data={**chat.data,'summary':out,'summary_revision':rev};db.commit()
            return {'chat_id':chat.id}
        raise ValueError('Unsupported job type.')

def run_job(id,lane):
    try:
        result=process(id)
        with SessionLocal.begin() as db:
            j=db.get(Job,id);j.status='Cancelled' if j.cancel else 'Done';j.result=result;j.progress=100;j.stage=j.status;j.lease=None
    except Exception as e:
        # Only safe user-facing errors. Never expose provider request bodies, DSNs or credentials.
        retry=isinstance(e,(__import__('httpx').TransportError,__import__('httpx').HTTPStatusError))
        with SessionLocal.begin() as db:
            j=db.get(Job,id);j.status='Cancelled' if j.cancel else 'Queued' if retry and j.attempts<3 else 'Failed'
            j.error=str(e)[:300] if isinstance(e,ValueError) else 'Processing failed. Check Ollama availability and retry; no output was published.'
            j.stage=j.status;j.lease=now()+timedelta(seconds=20*j.attempts) if j.status=='Queued' else None
            if j.kind=='ingest' and j.status=='Failed':
                s=record(db,j.workspace_id,j.data['source_id'],'source');s.status='Failed';s.data={**s.data,'error':j.error}
    finally:busy[lane]=False

def dispatch():
    for lane in ('io','ai'):
        if busy[lane]:continue
        with SessionLocal.begin() as db:
            q=select(Job).join(Workspace,Workspace.id==Job.workspace_id).where(Job.status=='Queued',Job.cancel==False,Workspace.status!='Deactivated',((Job.lease==None)|(Job.lease<now())))
            q=q.where(Job.kind.in_(AI_KINDS)) if lane=='ai' else q.where(~Job.kind.in_(AI_KINDS))
            j=db.scalar(q.order_by(Job.created).with_for_update(skip_locked=True).limit(1))
            if j:
                j.status='Running';j.attempts+=1;j.lease=now()+timedelta(minutes=10);busy[lane]=True;id=j.id
            else:id=None
        if id:pools[lane].submit(run_job,id,lane)

def maintenance():
    with SessionLocal.begin() as db:
        for j in db.scalars(select(Job).where(Job.status=='Running',Job.lease<now()).with_for_update(skip_locked=True)):
            j.status='Queued' if j.attempts<3 else 'Failed';j.stage='Recovered stale lease';j.lease=None
        db.execute(delete(LoginSession).where(LoginSession.touched<now()-timedelta(hours=12)))
        for r in db.scalars(select(Record).where(Record.kind.in_(['invitation','reset']),Record.status=='Pending')):
            if r.data.get('expires','')<now().isoformat():r.status='Expired'

def digests():
    with SessionLocal.begin() as db:
        for member in db.scalars(select(Membership)):
            user=db.get(User,member.user_id);freq=user.preferences.get('digest','daily')
            if freq=='off':continue
            span=7 if freq=='weekly' else 1;period=int(now().timestamp()//(86400*span));key=f'digest:{member.workspace_id}:{user.id}:{period}'
            if any(x.data.get('delivery_key')==key for x in records(db,member.workspace_id,'outbox')):continue
            ns=[n for n in records(db,member.workspace_id,'notification') if n.data.get('recipient')==user.id and n.status=='Unread']
            if ns:
                m=mail(db,member.workspace_id,user.email,'通知ダイジェスト' if user.language=='ja' else 'Notification digest','\n'.join(n.title for n in ns),user.language);m.data={**m.data,'delivery_key':key}

def start():
    global scheduler,pools
    if scheduler:return
    pools={lane:ThreadPoolExecutor(max_workers=1,thread_name_prefix='miyazaki-'+lane) for lane in ('io','ai')}
    scheduler=BackgroundScheduler(timezone='Asia/Tokyo')
    scheduler.add_job(dispatch,'interval',seconds=2,max_instances=1,coalesce=True)
    scheduler.add_job(maintenance,'interval',minutes=1,max_instances=1,coalesce=True)
    scheduler.add_job(digests,'interval',minutes=10,max_instances=1,coalesce=True)
    scheduler.start()

def stop():
    global scheduler
    if scheduler:scheduler.shutdown(wait=False);scheduler=None
    for p in pools.values():p.shutdown(wait=False,cancel_futures=True)
