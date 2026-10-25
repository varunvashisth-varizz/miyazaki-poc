import io,json,secrets,zipfile
from datetime import timedelta
from sqlalchemy import select,text
from app.db import SessionLocal,User,Record,Job,Workspace,Membership,now,uid
from app.seed import W1,W2
from app.services import records,enqueue
from app.security import digest
from app.config import settings
from app import jobs
from conftest import sign_in
A='/api/v1/w/'+W1

def test_setup_migration_idempotence():
    from app.migrations import migrate
    migrate();migrate()
    with SessionLocal() as db:assert db.scalar(text('SELECT MAX(version) FROM schema_version'))==1

def test_library_seed_44(client):
    from app.seed import LIBRARY_ROWS
    assert len(LIBRARY_ROWS)==44

def test_invitation_accept_replay_and_language(company,client):
    email='invite-'+secrets.token_hex(4)+'@example.test'
    r=company.post(A+'/invitations',json={'email':email});assert r.status_code==200
    outbox=company.get(A+'/records/outbox').json();msg=next(x for x in outbox if x['data']['recipient']==email);token=msg['data']['body'].split('/invite/')[1]
    body={'token':token,'password':'SafeNewPassword2026!','name':'Test Invitee','language':'en','terms':True}
    assert client.post('/api/v1/auth/accept',json=body).status_code==200
    assert client.post('/api/v1/auth/accept',json=body).status_code==400
    with SessionLocal() as db:assert db.scalar(select(User).where(User.email==email)).language=='en'

def test_invitation_expiry_and_revoke(company):
    r=company.post(A+'/invitations',json={'email':'expired-'+secrets.token_hex(4)+'@example.test'}).json()
    assert company.post(A+'/invitations/'+r['id']+'/revoke',json={}).status_code==200
    with SessionLocal() as db:assert db.get(Record,r['id']).status=='Revoked'

def test_reset_generic_and_one_use(company,client):
    assert client.post('/api/v1/auth/reset-request',json={'email':'nobody@example.test'}).json()==client.post('/api/v1/auth/reset-request',json={'email':'other@demo.local'}).json()
    with SessionLocal() as db:
        msg=next(x for x in records(db,W2,'outbox') if x.data.get('recipient')=='other@demo.local');token=msg.data['body'].split('token=')[1]
    data={'token':token,'password':'NewOtherPassword2026!','terms':True}
    assert client.post('/api/v1/auth/reset',json=data).status_code==200
    assert client.post('/api/v1/auth/reset',json=data).status_code==400
    # Restore the deterministic seed password after the test.
    from app.security import hash_password
    from app.seed import DEMO_PASSWORD
    with SessionLocal.begin() as db:db.scalar(select(User).where(User.email=='other@demo.local')).password=hash_password(DEMO_PASSWORD)

def test_failed_login_rate_limit(client):
    email='rate-'+secrets.token_hex(4)+'@example.test'
    for _ in range(8):assert client.post('/api/v1/auth/login',json={'email':email,'password':'wrong'}).status_code==401
    assert client.post('/api/v1/auth/login',json={'email':email,'password':'wrong'}).status_code==429

def test_mfa_enrollment_recovery_and_reuse(client):
    import pyotp
    sign_in(client,'member@demo.local')
    result=client.post('/api/v1/auth/mfa/enroll',json={});assert result.status_code==200
    secret=result.json()['secret'];r=client.post('/api/v1/auth/mfa/verify',json={'code':pyotp.TOTP(secret).now()});assert r.status_code==200
    codes=r.json()['recovery_codes'];assert len(codes)==8
    assert client.post('/api/v1/auth/mfa/verify',json={'code':codes[0]}).status_code==200
    assert client.post('/api/v1/auth/mfa/verify',json={'code':codes[0]}).status_code==401
    with SessionLocal.begin() as db:
        u=db.scalar(select(User).where(User.email=='member@demo.local'));u.mfa_enabled=False;u.mfa_secret=None;u.recovery=[];u.preferences={}

def test_member_outbox_denied(client):
    sign_in(client,'member@demo.local');assert client.get(A+'/records/outbox').status_code==403

def test_document_versions_restore(company):
    doc=company.post(A+'/records/document',json={'title':'Version test','data':{'content':'Version one','language':'en'}}).json()
    assert company.patch(A+'/records/'+doc['id'],json={'version':1,'data':{'content':'Version two'}}).status_code==200
    history=company.get(A+'/history/'+doc['id']).json();assert history[0]['snapshot']['data']['content']=='Version one'
    assert company.post(A+'/documents/'+doc['id']+'/restore/'+history[0]['id'],json={}).json()['data']['content']=='Version one'

def test_export_formats_and_japanese_font(company):
    doc=company.post(A+'/records/document',json={'title':'会社紹介','data':{'content':'日本語の会社紹介\n従業員48名。AIの仮定・要確認','language':'ja'}}).json()
    for fmt,magic in [('pdf',b'%PDF-'),('docx',b'PK'),('md','#'.encode())]:
        response=company.get(A+'/export/document/'+doc['id']+'?format='+fmt)
        assert response.status_code==200,response.text[:300];assert response.content.startswith(magic)
        if fmt=='pdf':
            from pypdf import PdfReader
            text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages);assert '会社紹介' in text

def test_workspace_zip_export(company):
    r=company.get(A+'/export-all');assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert 'workspace.json' in z.namelist();assert 'fact.json' in z.namelist();assert 'password' not in z.read('workspace.json').decode()

def test_plain_pdf_docx_xlsx_pptx_extraction(tmp_path):
    from app.ingestion import parse_file
    from app.exports import export_text
    p=tmp_path/'sample.pdf';p.write_bytes(export_text('会社紹介','精密加工の企業です。','pdf')[0]);assert '精密加工' in str(parse_file(p))
    p=tmp_path/'sample.docx';p.write_bytes(export_text('Title','Document content','docx')[0]);assert 'Document content' in str(parse_file(p))
    from openpyxl import Workbook
    p=tmp_path/'sample.xlsx';w=Workbook();w.active.append(['Product','Price']);w.active.append(['Valve',100]);w.save(p);assert 'Valve' in str(parse_file(p))
    from pptx import Presentation
    p=tmp_path/'sample.pptx';pr=Presentation();sl=pr.slides.add_slide(pr.slide_layouts[1]);sl.shapes.title.text='Presentation content';pr.save(p);assert 'Presentation content' in str(parse_file(p))

def test_scanned_pdf_explicit_limitation(tmp_path):
    import pytest
    from pypdf import PdfWriter
    from app.ingestion import parse_file
    p=tmp_path/'scan.pdf';w=PdfWriter();w.add_blank_page(100,100);w.write(p)
    with pytest.raises(ValueError,match='OCR is deferred'):parse_file(p)

def test_offline_ingestion_and_injection_jobs(company):
    r=company.post(A+'/sources/crawl',json={'fixture':True}).json()
    with SessionLocal.begin() as db:
        j=db.get(Job,r['job_id']);j.status='Running';j.attempts=1
    result=jobs.process(r['job_id']);assert result['source_id']==r['source']['id']
    r=company.post(A+'/sources/crawl',json={'fixture':True,'injection':True}).json();result=jobs.process(r['job_id']);assert 'warning' in result
    with SessionLocal() as db:assert db.get(Record,r['source']['id']).status=='Quarantined'

def test_workflow_b1_b3_answers_and_confirmation(company):
    company.post(A+'/workflows/propose',json={})
    for code in ('B1','B3'):
        workflow=next(x for x in company.get(A+'/records/workflow').json() if x['data']['template']==code)
        p=company.post(A+'/pending',json={'data':{'action':'workflow_status','target_id':workflow['id'],'status':'Active'}}).json()
        assert company.post(A+'/pending/'+p['id']+'/confirm',json={}).status_code==200
        question_step=next(s for s in workflow['data']['steps'] if s['type']=='questions')
        for q in question_step['questions']:
            response=company.post(A+'/workflows/'+workflow['id']+'/answer',json={'step_id':question_step['id'],'key':q['key'],'value':'Test answer for '+q['key']})
            assert response.status_code==200;factid=response.json()['proposed_fact_id']
            assert company.post(A+'/facts/'+factid+'/confirm',json={}).status_code==200
        current=next(x for x in company.get(A+'/records/workflow').json() if x['id']==workflow['id'])
        for step in current['data']['steps']:
            p=company.post(A+'/pending',json={'data':{'action':'step_status','target_id':workflow['id'],'step_id':step['id'],'status':'Done'}}).json()
            r=company.post(A+'/pending/'+p['id']+'/confirm',json={});assert r.status_code==200,r.text
        finished=next(x for x in company.get(A+'/records/workflow').json() if x['id']==workflow['id']);assert finished['status']=='Done';assert finished['data']['outputs']

def test_job_dedup_and_cancel(company):
    with SessionLocal.begin() as db:
        one=enqueue(db,W1,'index',{'source_id':'test'},'dedup-test');two=enqueue(db,W1,'index',{'source_id':'test'},'dedup-test');assert one.id==two.id;id=one.id
    assert company.post(A+'/jobs/'+id+'/cancel',json={}).status_code==200
    with SessionLocal() as db:assert db.get(Job,id).status=='Cancelled'

def test_stale_job_recovery():
    with SessionLocal.begin() as db:
        j=Job(workspace_id=W1,kind='index',status='Running',attempts=1,lease=now()-timedelta(minutes=1));db.add(j);db.flush();id=j.id
    jobs.maintenance()
    with SessionLocal() as db:assert db.get(Job,id).status=='Queued'

def test_digest_deduplication():
    from app.services import notify
    with SessionLocal.begin() as db:
        u=db.scalar(select(User).where(User.email=='company@demo.local'));notify(db,W1,u.id,'document_ready','Test digest notification')
    jobs.digests();jobs.digests()
    with SessionLocal() as db:
        keys=[x.data['delivery_key'] for x in records(db,W1,'outbox') if 'delivery_key' in x.data];assert len(keys)==len(set(keys))

def test_feedback_and_admin_reply(company,client):
    f=company.post(A+'/records/feedback',json={'title':'Demo feedback','data':{'rating':'up','text':'Useful','category':'praise'}}).json()
    sign_in(client,'admin@demo.local');assert client.patch('/api/v1/admin/feedback/'+f['id'],json={'status':'Addressed','data':{'reply':'Thank you'}}).status_code==200

def test_source_saved_from_document(company):
    doc=company.post(A+'/records/document',json={'title':'Reusable','data':{'content':'Verified document text'}}).json()
    r=company.post(A+'/documents/'+doc['id']+'/save-source',json={});assert r.status_code==200
    source=next(s for s in company.get(A+'/records/source').json() if s['id']==r.json()['source_id']);assert source['data']['origin_document']==doc['id']

def test_usecase_add_and_dependencies(company):
    lib=company.get('/api/v1/library').json()[0]
    r=company.post(A+'/usecases/add/'+lib['id'],json={});assert r.status_code==200
    id=r.json()['id'];assert company.post(A+'/usecases/add/'+lib['id'],json={}).json()['id']==id
    assert company.patch(A+'/records/'+id,json={'data':{'dependencies':[id]}}).status_code==422

def test_deactivation_blocks_access(admin,client):
    r=admin.post('/api/v1/admin/companies',json={'title':'Deactivation test','data':{'slug':'deactivate-'+secrets.token_hex(4)}});assert r.status_code==200
    assert admin.patch('/api/v1/admin/companies/'+r.json()['id'],json={'status':'Deactivated'}).status_code==200

def test_i18n_keys_and_ime_guard_present():
    from pathlib import Path
    text=Path('frontend/src/main.tsx').read_text();assert 'isComposing' in text
    source=Path('frontend/src/i18n.ts').read_text();assert "[string,string]" in source and "Object.fromEntries" in source

def test_automatic_capture_creates_proposals_without_confirming_mock(monkeypatch):
    from app import ai
    with SessionLocal.begin() as db:
        m=Record(workspace_id=W1,kind='message',title='Capture input',data={'role':'user','content':'We employ 53 engineers.'},created_by='test');db.add(m);db.flush();j=enqueue(db,W1,'capture',{'origin_id':m.id});id=j.id
    monkeypatch.setattr(ai,'generate',lambda *a,**k:json.dumps({'facts':[{'section':'overview','key':'engineers','value':'53','provenance':'Stated','confidence':1,'source_id':'','why':''}],'products':[]}))
    out=jobs.process(id);assert out['proposed_facts']
    with SessionLocal() as db:
        f=db.get(Record,out['proposed_facts'][0]);assert f.status=='Proposed' and f.data['provenance']=='Stated'

def test_adaptive_question_set_mock(monkeypatch):
    from app import ai
    from app.seed import workflow_data
    with SessionLocal.begin() as db:
        w=Record(workspace_id=W1,kind='workflow',title='Adaptive test',data=workflow_data('B1','test'));db.add(w);db.flush();step=next(x for x in w.data['steps'] if x['type']=='questions');j=enqueue(db,W1,'interview',{'workflow_id':w.id,'step_id':step['id']});id=j.id;wid=w.id
    monkeypatch.setattr(ai,'generate',lambda *a,**k:json.dumps({'questions':[{'key':'followup'+str(i),'text':'What evidence supports the previous answer?','text_ja':'前の回答を裏付ける資料はありますか？'} for i in range(5)]}))
    assert jobs.process(id)['questions']==10
    assert jobs.process(id)['skipped']

def test_product_merge_delete_and_cross_tenant(company):
    a=company.post(A+'/records/product',json={'title':'One','data':{'function':'Machining'}}).json();b=company.post(A+'/records/product',json={'title':'Two','data':{'materials':'Steel'}}).json()
    r=company.post(A+'/products/'+a['id']+'/merge',json={'other_id':b['id']});assert r.status_code==200;assert b['id'] in r.json()['data']['merged_from']
    assert company.request('DELETE',A+'/products/'+a['id'],json={}).status_code==200

def test_library_approval_bound_to_version(platform,client):
    data={k:'Draft bilingual field' for k in ['problem','how','systems','prerequisites','success','data_needed','problem_ja','how_ja','systems_ja','prerequisites_ja','success_ja','data_needed_ja']};data.update({'title_ja':'テスト','stage':'Assembly'})
    r=platform.post('/api/v1/library',json={'title':'Review version test','data':data}).json();id=r['id']
    sign_in(client,'admin@demo.local');assert client.patch('/api/v1/library/'+id,json={'data':{'comment':'Approved test only','japanese_approved':True}}).status_code==200
    sign_in(client,'platform@demo.local');assert client.patch('/api/v1/library/'+id,json={'title':'Changed after approval','data':{}}).status_code==200
    assert client.patch('/api/v1/library/'+id,json={'status':'Published','data':{}}).status_code==422

def test_translation_preserves_original_mock(company,monkeypatch):
    from app import ai
    f=company.post(A+'/facts',json={'data':{'section':'products','key':'translate_test','value':'Valve body','provenance':'Stated','confidence':1,'sources':[]}}).json()
    j=company.post(A+'/translate/'+f['id'],json={'language':'ja'}).json()
    monkeypatch.setattr(ai,'generate',lambda *a,**k:'バルブボディ')
    jobs.process(j['job_id'])
    with SessionLocal() as db:
        r=db.get(Record,f['id']);assert r.data['value']=='Valve body';assert r.data['translations']['ja']=='バルブボディ'
