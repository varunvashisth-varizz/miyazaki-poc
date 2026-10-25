#!/usr/bin/env python3
"""Cross-platform single entry point. No shell-specific commands are executed."""
import argparse, json, sys, time, webbrowser, threading
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from app.config import settings,ROOT

def setup(pull=True):
    url=make_url(settings.database_url)
    if url.get_backend_name()!='postgresql':raise ValueError('PostgreSQL with pgvector is required; SQLite is not supported.')
    try:
        with create_engine(settings.database_url).connect() as c:c.execute(text('SELECT 1'))
    except Exception:
        admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT')
        try:
            with admin.connect() as c:
                name=url.database
                if not name or not all(c.isalnum() or c=='_' for c in name):raise ValueError('Database name must contain only letters, numbers and underscores.')
                if not c.scalar(text('SELECT 1 FROM pg_database WHERE datname=:name'),{'name':name}):c.execute(text('CREATE DATABASE "'+name+'"'))
        except Exception:
            print('Cannot connect/create database. Check PostgreSQL and DATABASE_URL. An administrator may run:')
            print('CREATE DATABASE "'+str(url.database).replace('"','')+'" OWNER "'+str(url.username).replace('"','')+'";');return False
    from app.migrations import migrate
    try:migrate()
    except Exception:
        print('Migration failed. Install the pgvector package for your PostgreSQL major version, then ask a database administrator to run CREATE EXTENSION vector in this database.');return False
    settings.storage().mkdir(parents=True,exist_ok=True)
    from app.seed import seed,ACCOUNTS,DEMO_PASSWORD
    if settings.demo_mode:seed()
    if pull:
        import httpx
        with httpx.Client(timeout=None,trust_env=False) as client:
            try:
                names=[m['name'] for m in client.get(settings.ollama_base_url+'/api/tags').json().get('models',[])]
                for name in (settings.generation_model,settings.embedding_model):
                    if name not in names and name+':latest' not in names:
                        print('Downloading model:',name,flush=True)
                        with client.stream('POST',settings.ollama_base_url+'/api/pull',json={'name':name,'stream':True}) as response:
                            response.raise_for_status();last=''
                            for line in response.iter_lines():
                                if line:
                                    result=json.loads(line)
                                    if result.get('error'):raise ValueError(result['error'])
                                    status=result.get('status','')
                                    if result.get('total'):status+=' '+str(round(100*result.get('completed',0)/result['total']))+'%'
                                    if status!=last:print(status,flush=True);last=status
            except Exception:print('Models not ready. Start Ollama, then rerun setup. Database and seeds are ready.');return False
    print('Setup complete. URL: http://'+settings.host+':'+str(settings.port))
    if settings.demo_mode:
        print('LOCAL SYNTHETIC DEMO ONLY. Demo password:',DEMO_PASSWORD)
        for a in ACCOUNTS:print(a[0],a[2])
    return True

def check(smoke=True):
    from app.main import health
    result=health();result['storage_writable']=False
    try:
        settings.storage().mkdir(parents=True,exist_ok=True);p=settings.storage()/'.write-check';p.write_text('ok');p.unlink();result['storage_writable']=True
    except Exception:pass
    from app.db import SessionLocal,Workspace
    try:
        with SessionLocal() as db:result['seed_companies']=db.scalar(text('SELECT count(*) FROM workspaces'))
    except Exception:result['seed_companies']=0
    if smoke:
        from app.ai import provider
        result['generation']=[]
        for lang,prompt in [('ja','日本語で短く挨拶してください。'),('en','Say hello in English in one short sentence.')]:
            start=time.monotonic();first=None;tokens=0;output=''
            try:
                for part in provider.stream([{'role':'user','content':prompt}],maximum=30):
                    if part['text'] and first is None:first=time.monotonic()-start
                    output+=part['text'];tokens=part['tokens'] or tokens
                elapsed=time.monotonic()-start
                result['generation'].append({'language':lang,'first_token_seconds':round(first or elapsed,3),'elapsed_seconds':round(elapsed,3),'total_tokens':tokens,'output':output})
            except Exception:result['generation'].append({'language':lang,'status':'Blocked: model unavailable'})
        try:
            vector=provider.embed(['宮崎の精密加工会社'])[0];result['embedding_dimension']=len(vector)
            with SessionLocal() as db:
                result['vector_smoke_distance']=float(db.scalar(text('SELECT CAST(:v AS vector) <=> CAST(:v AS vector)'),{'v':str(vector)}))
        except Exception:result['embedding']='Blocked: unavailable or dimension mismatch'
    print(json.dumps(result,ensure_ascii=False,indent=2))
    (ROOT/'evidence').mkdir(exist_ok=True)
    (ROOT/'evidence/preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['setup','check','run','seed']);parser.add_argument('--reset',action='store_true');parser.add_argument('--no-pull',action='store_true');parser.add_argument('--no-smoke',action='store_true');args=parser.parse_args()
    try:
        if args.command=='setup':sys.exit(0 if setup(not args.no_pull) else 1)
        elif args.command=='check':check(not args.no_smoke)
        elif args.command=='seed':
            if not settings.demo_mode or 'demo' not in make_url(settings.database_url).database:raise ValueError('Reset requires DEMO_MODE=true and a database name containing demo.')
            from app.seed import seed
            seed(args.reset);print('Demo seeds restored.' if args.reset else 'Missing demo seeds loaded.')
        elif args.command=='run':
            settings.validate_runtime();import uvicorn
            threading.Timer(1.5,lambda:webbrowser.open('http://'+settings.host+':'+str(settings.port))).start()
            uvicorn.run('app.main:app',host=settings.host,port=settings.port,workers=1,log_level='warning',access_log=False)
    except Exception as e:
        print('Unable to continue:',str(e) if isinstance(e,ValueError) else 'Check PostgreSQL, pgvector and Ollama using the README setup steps.');sys.exit(1)
