"""Real PostgreSQL/pgvector tests. Provider-dependent tests identify their mock explicitly."""
import io,json,secrets,zipfile,socket
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest,pyotp
from sqlalchemy import select,text
from fastapi import HTTPException
from app.db import SessionLocal,Workspace,User,Membership,Record,Chunk,Usage,Audit,Session as LoginSession,now,uid
from app.seed import W1,W2,DEMO_PASSWORD
from app.config import settings
from app.security import public_url,safe_path,archive_safe,redact,hash_password,digest
from app.services import context,knowledge,propose_fact,records
from app import ai
from conftest import sign_in

A='/api/v1/w/'+W1;B='/api/v1/w/'+W2

def test_postgres_pgvector_extension(client):
    with SessionLocal() as db:assert db.scalar(text("SELECT extname FROM pg_extension WHERE extname='vector'"))=='vector'

def test_auth_required(client):assert client.get(A+'/records/fact').status_code==401

def test_bad_password_generic(client):
    a=client.post('/api/v1/auth/login',json={'email':'company@demo.local','password':'wrong'})
    b=client.post('/api/v1/auth/login',json={'email':'unknown@demo.local','password':'wrong'})
    assert a.status_code==b.status_code==401;assert a.json()==b.json()

def test_csrf_required(company):
    saved=company.headers.pop('X-CSRF-Token')
    assert company.post(A+'/records/chat',json={'title':'blocked'}).status_code==403
    company.headers['X-CSRF-Token']=saved

def test_cross_origin_rejected(company):
    assert company.post(A+'/records/chat',json={'title':'blocked'},headers={'Origin':'https://evil.example'}).status_code==403

def test_host_header_rejected(client):assert client.get('/api/v1/health',headers={'Host':'evil.example'}).status_code==400

def test_session_cookie_flags(client):
    r=client.post('/api/v1/auth/login',json={'email':'member@demo.local','password':DEMO_PASSWORD})
    cookie=r.headers['set-cookie'].lower();assert 'httponly' in cookie and 'samesite=strict' in cookie

def test_logout_revokes_session(company):
    assert company.post('/api/v1/auth/logout',json={}).status_code==200
    assert company.get('/api/v1/auth/me').status_code==401

def test_session_idle_expiry(company):
    with SessionLocal.begin() as db:
        s=db.get(LoginSession,digest(company.cookies.get('session')));s.touched=now()-timedelta(hours=13)
    assert company.get(A+'/home').status_code==401

@pytest.mark.parametrize('path',['home','records/fact','records/source','records/document','records/chat','records/message','records/workflow','records/usecase','jobs','settings','export-all','recommendations'])
def test_cross_workspace_endpoints(company,path):assert company.get(B+'/'+path).status_code in (403,404)

def test_company_cannot_admin(company):
    for path in ['companies','audit','feedback','outbox','dashboard']:assert company.get('/api/v1/admin/'+path).status_code==403

def test_member_cannot_settings(client):
    sign_in(client,'member@demo.local');assert client.patch(A+'/settings',json={'data':{'sharing':[]}}).status_code==403

def test_cannot_create_privileged_record_kind(company):
    for kind in ['invitation','outbox','fact','pending','source','workflow','reset']:assert company.post(A+'/records/'+kind,json={'title':'bypass','data':{}}).status_code==403

def test_cross_workspace_reference_blocked(company):
    with SessionLocal.begin() as db:
        r=Record(workspace_id=W2,kind='document',title='Private');db.add(r);db.flush();id=r.id
    assert company.post(A+'/records/chat',json={'title':'bad link','data':{'document_id':id}}).status_code==404

def test_fact_review_history_and_rejection(company):
    r=company.post(A+'/facts',json={'data':{'section':'overview','key':'test_fact','value':'REJECT-ME-UNIQUE','provenance':'Stated','confidence':1,'sources':[]}});assert r.status_code==200;r=r.json()
    assert company.post(A+'/facts/'+r['id']+'/confirm',json={'version':r['version']}).status_code==200
    current=next(f for f in company.get(A+'/records/fact').json() if f['id']==r['id'])
    assert company.post(A+'/facts/'+r['id']+'/reject',json={'version':current['version']}).status_code==200
    assert len(company.get(A+'/history/'+r['id']).json())==2
    with SessionLocal() as db:assert 'REJECT-ME-UNIQUE' not in context(db,W1)[0]

def test_rejected_claim_not_in_historical_context(company):
    with SessionLocal.begin() as db:
        chat=Record(workspace_id=W1,kind='chat',title='Historic context',data={'summary':'Unsupported demo revenue claim 999 million yen','summary_revision':db.get(Workspace,W1).revision});db.add(chat);db.flush()
        db.add(Record(workspace_id=W1,kind='message',title='Old answer',data={'chat_id':chat.id,'role':'assistant','content':'Unsupported demo revenue claim 999 million yen'}));cid=chat.id
    with SessionLocal() as db:
        c=db.get(Record,cid);ct,_,history=context(db,W1,c)
        # A stale summary must also respect rejected-value suppression.
        assert all('999 million' not in h['content'] for h in history)
        assert '999 million' not in ct

def test_context_profile_off_excludes_history(company):
    with SessionLocal() as db:
        ct,handles,hist=context(db,W1,selection={'profile':False,'knowledge':False});assert not handles and not hist;assert 'PROFILE IS DISABLED' in ct

def test_fact_conflict_not_silent(company):
    r=company.post(A+'/facts',json={'data':{'section':'overview','key':'employees','value':'49','provenance':'Stated','confidence':1,'sources':[]}})
    assert r.status_code==200 and r.json()['data']['conflict'] and r.json()['status']=='Proposed'

def test_stale_fact_version_rejected(company):
    f=company.get(A+'/records/fact').json()[0]
    assert company.post(A+'/facts/'+f['id']+'/confirm',json={'version':999999}).status_code==409

def test_operator_only_shared_content(admin):
    r=admin.get('/api/v1/admin/companies/'+W1);assert r.status_code==200
    assert all(f['data']['section'] in ['overview','products'] for f in r.json()['facts'])
    assert admin.get(A+'/records/chat').status_code==404

def test_coordinator_read_comment_scope(company,client):
    assert company.post(A+'/members',json={'email':'advisor@demo.local','role':'Coordinator read'}).status_code==200
    sign_in(client,'advisor@demo.local')
    assert client.get(A+'/records/fact').status_code==200
    assert client.get(A+'/records/document').status_code==403
    assert client.post(A+'/facts',json={'data':{}}).status_code==403

def test_tenant_vector_retrieval(company):
    vector=[1.0]+[0.0]*1023
    with SessionLocal.begin() as db:
        for wid,value in [(W1,'SAFE-A-VECTOR'),(W2,'PRIVATE-B-VECTOR')]:
            s=Record(workspace_id=wid,kind='source',title=value,status='Ready');db.add(s);db.flush();db.add(Chunk(workspace_id=wid,source_id=s.id,content=value,embedding=vector,location='Test'))
    with SessionLocal() as db:
        result=knowledge(db,W1,'VECTOR',vector);assert result;assert all(c.workspace_id==W1 for c in result);assert not any('PRIVATE-B' in c.content for c in result)

def test_source_delete_excludes_vector_and_reopens_fact(company):
    with SessionLocal.begin() as db:
        s=Record(workspace_id=W1,kind='source',title='Delete source',status='Ready');db.add(s);db.flush();sid=s.id
        db.add(Chunk(workspace_id=W1,source_id=sid,content='DELETED-SOURCE-SENTINEL',embedding=[1.0]+[0.0]*1023))
        f=propose_fact(db,W1,'test',{'section':'overview','key':'sole_source','value':'Only here','provenance':'Sourced','confidence':1,'sources':[sid]});f.status='Confirmed';fid=f.id
    assert company.request('DELETE',A+'/sources/'+sid,json={}).status_code==200
    with SessionLocal() as db:
        assert all(c.source_id!=sid for c in knowledge(db,W1,'DELETED-SOURCE-SENTINEL',[1.0]+[0.0]*1023))
        assert db.get(Record,fid).status=='Proposed'

def test_upload_traversal_filename_never_controls_path(company):
    r=company.post(A+'/sources/upload',files={'file':('../../outside.txt',b'normal source','text/plain')});assert r.status_code==200
    with SessionLocal() as db:
        s=db.get(Record,r.json()['source']['id']);assert '..' not in s.data['path'] and s.data['path'].startswith('uploads/')

def test_misleading_pdf_rejected(company):assert company.post(A+'/sources/upload',files={'file':('fake.pdf',b'<script>evil</script>','application/pdf')}).status_code==422

def test_cross_tenant_download_rejected(company):assert company.get(B+'/sources/00000000-0000-4000-8000-000000000001/file').status_code==404

@pytest.mark.parametrize('url',['http://127.0.0.1','http://169.254.169.254','http://[::1]','http://10.0.0.1','file:///etc/passwd','http://user:pass@example.com','http://example.com:8080'])
def test_ssrf_blocked(url):
    with pytest.raises((ValueError,socket.gaierror)):public_url(url)

def test_archive_bomb_and_path_rejected(tmp_path):
    p=tmp_path/'bad.docx'
    with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('../escape',b'0'*200000)
    with pytest.raises(ValueError):archive_safe(p)

def test_safe_path_blocks_traversal():
    with pytest.raises(HTTPException):safe_path(W1,'../../etc/passwd')

def test_prompt_injection_fixture_quarantined(company):
    from app.ingestion import crawl
    pages=crawl('',fixture=True,injection=True);assert pages[0]['flagged']

def test_invalid_citation_detected():assert not ai.valid_citations('Claim [F:stolen-id]',{})

def test_pending_action_requires_confirmation_and_is_idempotent(company):
    c=company.post(A+'/records/chat',json={'title':'Action test','data':{}}).json()
    before=len(company.get(A+'/records/workflow').json())
    p=company.post(A+'/pending',json={'title':'Draft workflow','data':{'action':'chat_to_workflow','target_id':c['id']}}).json()
    assert len(company.get(A+'/records/workflow').json())==before
    one=company.post(A+'/pending/'+p['id']+'/confirm',json={});two=company.post(A+'/pending/'+p['id']+'/confirm',json={})
    assert one.status_code==two.status_code==200;assert two.json()['already_applied'];assert len(company.get(A+'/records/workflow').json())==before+1

def test_audit_append_only():
    with SessionLocal.begin() as db:
        a=Audit(actor='test',action='test',target='test');db.add(a);db.flush();id=a.id
    with pytest.raises(Exception):
        with SessionLocal.begin() as db:db.execute(text('DELETE FROM audit WHERE id=:id'),{'id':id})

def test_eval_export_requires_consent(platform):assert platform.get(A+'/evaluation-preview').status_code==403

def test_redaction():
    r=redact('Contact Test Person at test@example.com or +81 90 1234 5678',['Test Person']);assert 'test@example.com' not in r and 'Test Person' not in r and '1234' not in r

def test_editor_stored_xss_removed(company):
    d=company.post(A+'/records/document',json={'title':'XSS','data':{'content':'Safe'}}).json()
    r=company.patch(A+'/records/'+d['id'],json={'data':{'content':'<script>alert(1)</script>Safe','rich_html':'<p onclick="evil()">Safe<script>evil()</script></p>'}})
    assert r.status_code==200;data=r.json()['data'];assert '<script' not in data['content'] and 'onclick' not in data['rich_html'] and '<script' not in data['rich_html']

def test_sql_injection_identifier_is_data(company):assert company.get('/api/v1/w/'+"x' OR '1'='1"+'/records/fact').status_code==404

def test_security_headers(company):
    r=company.get(A+'/home');assert r.headers['x-content-type-options']=='nosniff';assert "frame-ancestors 'none'" in r.headers['content-security-policy']

def test_production_unsafe_defaults_blocked():
    from app.config import Settings
    with pytest.raises(ValueError):Settings(demo_mode=False,demo_skip_mfa=True).validate_runtime()

def test_networked_demo_binding_blocked():
    from app.config import Settings
    with pytest.raises(ValueError):Settings(host='0.0.0.0',demo_mode=True).validate_runtime()

def test_budget_reservation_concurrency():
    wid=uid()
    with SessionLocal.begin() as db:db.add(Workspace(id=wid,slug='budget-'+secrets.token_hex(4),name='Budget test',token_budget=100))
    def reserve():
        try:
            with SessionLocal.begin() as db:ai.reserve(db,wid,'test',80)
            return True
        except HTTPException:return False
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(lambda _:reserve(),range(2)))==[False,True]

def test_model_dimension_mismatch_mock(monkeypatch):
    class R:
        def raise_for_status(self):pass
        def json(self):return {'embeddings':[[1,2,3]]}
    monkeypatch.setattr('httpx.Client.post',lambda *a,**k:R())
    with pytest.raises(ValueError):ai.provider.embed(['test'])

def test_bilingual_publish_gate(platform):
    r=platform.post('/api/v1/library',json={'title':'Test card','data':{'stage':'Assembly'}}).json()
    assert platform.patch('/api/v1/library/'+r['id'],json={'status':'Published','data':{}}).status_code==422

def test_known_proposed_certification_cannot_be_published():
    with SessionLocal() as db:
        # Seeded ISO 9001 is proposed, not verified company knowledge.
        with pytest.raises(ValueError):ai.reject_unverified_values(db,W1,'The company holds ISO 9001 certification.')

def test_uncited_prose_after_heading_is_marked():
    out=ai.ground_output('# Title\nUnsupported forecast is 12%.',{},'en')
    assert 'AI assumption, verify' in out

def test_upload_limit_enforced(company,monkeypatch):
    monkeypatch.setattr(settings,'upload_limit',64)
    assert company.post(A+'/sources/upload',files={'file':('large.txt',b'x'*100,'text/plain')}).status_code==413

def test_member_cannot_confirm_fact(client):
    sign_in(client,'member@demo.local')
    with SessionLocal() as db:f=db.scalar(select(Record).where(Record.workspace_id==W1,Record.kind=='fact'))
    assert client.post(A+'/facts/'+f.id+'/confirm',json={}).status_code==403

def test_cross_tenant_pending_action(company):
    with SessionLocal.begin() as db:
        p=Record(workspace_id=W2,kind='pending',title='Foreign action',status='Pending',data={'action':'chat_to_workflow','expires':(now()+timedelta(minutes=10)).isoformat()},created_by='someone');db.add(p);db.flush();id=p.id
    assert company.post(A+'/pending/'+id+'/confirm',json={}).status_code==404

def test_platform_cannot_forge_operator_approval(platform):
    r=platform.post('/api/v1/library',json={'title':'Forged approval test','data':{'stage':'Assembly'}}).json()
    assert platform.patch('/api/v1/library/'+r['id'],json={'data':{'reviews':[{'japanese_approved':True,'review_version':2}]}}).status_code==422

def test_context_budget_is_bounded_and_policy_preserved():
    messages=[{'role':'system','content':ai.POLICY},{'role':'user','content':'SOURCE DATA '+('あ'*20000)},{'role':'user','content':'Give a short answer'}]
    fitted=ai.fit_messages(messages,700)
    assert fitted[0]['content']==ai.POLICY
    assert sum(len(m['content'].encode()) for m in fitted)<=settings.context_tokens-700-128
    assert fitted[-1]['content']=='Give a short answer'
