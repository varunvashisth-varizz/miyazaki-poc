"""Real-service smoke tests on synthetic demo data. No provider mocks."""
import json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from app.seed import DEMO_PASSWORD
results=[];base='http://127.0.0.1:8000/api/v1';start=time.monotonic()

def check(name,fn):
    t=time.monotonic()
    try:
        detail=fn();results.append({'name':name,'status':'Passed','seconds':round(time.monotonic()-t,3),'detail':detail});return detail
    except Exception as e:results.append({'name':name,'status':'Failed','seconds':round(time.monotonic()-t,3),'actual':str(e)[:500]});return None

with httpx.Client(base_url=base,timeout=240,trust_env=False) as c:
    r=c.post('/auth/login',json={'email':'company@demo.local','password':DEMO_PASSWORD});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf']
    w='/w/sample-a'
    def waitjob(id,timeout=300):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            jobs=c.get(w+'/jobs').json();j=next(x for x in jobs if x['id']==id)
            if j['status'] in ('Done','Failed','Cancelled'):
                if j['status']!='Done':raise AssertionError(j['error'] or j['status'])
                return j
            time.sleep(2)
        raise AssertionError('Job did not finish within smoke-test timeout')
    def ingestion():
        r=c.post(w+'/sources/crawl',json={'fixture':True});r.raise_for_status();j=waitjob(r.json()['job_id']);return j['result']
    source=check('Real offline ingestion pipeline',ingestion)
    def extraction():
        until=time.monotonic()+300
        while time.monotonic()<until:
            jobs=[j for j in c.get(w+'/jobs').json() if j['kind'] in ('index','analyse') and j['data'].get('source_id')==source['source_id']]
            if len(jobs)==2 and all(j['status']=='Done' for j in jobs):return [{'kind':j['kind'],'result':j['result']} for j in jobs]
            if any(j['status']=='Failed' for j in jobs):raise AssertionError([(j['kind'],j['error']) for j in jobs if j['status']=='Failed'])
            time.sleep(2)
        raise AssertionError('Index/extraction timed out')
    if source:check('Real multilingual embedding and structured extraction',extraction)
    def chat(language,prompt):
        r=c.post(w+'/records/chat',json={'title':'Real smoke '+language,'data':{}});r.raise_for_status();id=r.json()['id'];answer='';first=None;t=time.monotonic();events=[]
        with c.stream('POST',w+'/chats/'+id+'/messages',json={'message':prompt,'language':language,'context':{'profile':True,'knowledge':False}}) as stream:
            stream.raise_for_status();kind=''
            for line in stream.iter_lines():
                if line.startswith('event: '):kind=line[7:];events.append(kind)
                elif line.startswith('data: '):
                    data=json.loads(line[6:])
                    if kind=='delta':
                        if first is None:first=time.monotonic()-t
                        answer+=data['text']
                    if kind=='replace':answer=data['text']
                    if kind=='error':raise AssertionError(data['message'])
        if not answer.strip():raise AssertionError('Empty answer')
        if '999 million' in answer or 'PRIVATE-B' in answer:raise AssertionError('Rejected/foreign claim present')
        return {'answer':answer,'first_token_seconds':round(first or 0,3),'events':sorted(set(events))}
    check('Real Japanese grounded chat',lambda:chat('ja','当社の従業員数と製品を、根拠を付けて短く説明してください。'))
    check('Real English unknown-revenue answer',lambda:chat('en','What is our verified annual revenue? If it is not recorded, ask me instead of estimating.'))
    def document():
        r=c.post(w+'/records/document',json={'title':'Live verified company introduction','data':{'language':'ja','template':'Company introduction','content':''}});r.raise_for_status();id=r.json()['id']
        r=c.post(w+'/documents/'+id+'/generate',json={'language':'ja','prompt':'Write a short company introduction in Japanese, under 200 words. Only use confirmed evidence.','context':{'profile':True,'knowledge':False}});r.raise_for_status();waitjob(r.json()['job_id'])
        doc=next(d for d in c.get(w+'/records/document').json() if d['id']==id)
        if not doc['data'].get('content'):raise AssertionError('Empty document')
        if 'ISO 9001' in doc['data']['content'] or 'ISO9001' in doc['data']['content']:raise AssertionError('Unverified certification appeared in draft')
        if 'AIの仮定' not in doc['data']['content'] and '[F:' not in doc['data']['content']:raise AssertionError('Missing evidence or assumption markers')
        exported=c.get(w+'/export/document/'+id+'?format=pdf');exported.raise_for_status()
        if not exported.content.startswith(b'%PDF-'):raise AssertionError('Invalid PDF')
        Path('evidence/live-generated-sample.pdf').write_bytes(exported.content)
        return {'document_id':id,'content':doc['data']['content'],'pdf_bytes':len(exported.content)}
    check('Real Japanese document generation and PDF export',document)
Path('evidence/live-model-results.json').write_text(json.dumps({'date':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'results':results,'elapsed':time.monotonic()-start},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2));sys.exit(any(r['status']!='Passed' for r in results))
