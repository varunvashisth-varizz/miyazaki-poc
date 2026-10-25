"""Deterministic, visibly synthetic demo records. No invented source attribution."""
from uuid import UUID
from sqlalchemy import select, delete
from .db import SessionLocal, Workspace, User, Membership, Record, Library, Chunk, Job, Revision, Usage
from .security import hash_password
from .services import SECTIONS

W1='11111111-1111-4111-8111-111111111111';W2='22222222-2222-4222-8222-222222222222'
DEMO_PASSWORD='MiyazakiDemo2026!'
ACCOUNTS=[('admin@demo.local','Operator Admin','Super Admin',None),('company@demo.local','田中 管理者','Company Admin',W1),('member@demo.local','山本 メンバー','Member',W1),('other@demo.local','Second Company Admin','Company Admin',W2),('platform@demo.local','Platform Editor','Platform Admin',None),('advisor@demo.local','Coordinator','Coordinator',None)]
LIBRARY_ROWS=[
('All','Factory intelligence dashboard','工場インテリジェンスダッシュボード','Software only','H1','L1','ERP records and spreadsheets'),
('Inward','Document reading at the gate','入荷書類の読み取り','Software only','H1','L1','Purchase orders and scanned documents'),
('Inward','Material test certificate check','材料試験証明書の照合','Software only','H1','L1','Certificates and specifications'),
('Inward','Gate-to-receipt cycle time tracking','入門から入荷までの時間管理','Software only','H1','L1','Arrival timestamps'),
('Inward','Supplier risk scoring','サプライヤーリスク評価','Software only','H2','L2','Delivery and quality history'),
('Warehouse','Part identification from a photo','写真による部品識別','Camera based','H2','L2','Master product images'),
('Warehouse','Put-away bin recommendation','保管場所の推奨','Software only','H2','L2','Dimensions, bins and usage'),
('Warehouse','FIFO exception alerts','先入先出の例外検知','Software only','H1','L1','Lots and stock movements'),
('Warehouse','Demand-driven replenishment','需要に基づく補充','Software only','H2','L3','Schedule and consumption'),
('Kitting','Kit completeness check','キット構成品の確認','Camera based','H2','L2','Bill of kit and images'),
('Kitting','Shortage prediction','欠品予測','Software only','H2','L2','Stock and open orders'),
('Kitting','Lot-to-kit traceability','ロットとキットの追跡','Software only','H1','L1','Lot and kit numbers'),
('Assembly','Digital in-process inspection records','工程内検査記録のデジタル化','Software only','H1','L1','Job, machine and inspection results'),
('Assembly','Cycle-time monitoring against takt','タクトに対するサイクルタイム監視','Camera based / Machine IoT','H2','L2','Cycle start and end'),
('Assembly','Pick-and-place assembly verification','組立作業の検証','Camera based','H2','L2','Images and work instructions'),
('Assembly','OEE and bottleneck finder','設備総合効率とボトルネック分析','Machine IoT','H2','L2','Machine states and downtime'),
('Assembly','Andon root-cause suggestions','アンドンの原因候補提示','Software only','H2','L2','Andon event history'),
('Assembly','Predictive maintenance on critical machines','重要設備の予知保全','Machine IoT','H3','L3','Vibration and temperature'),
('Assembly','Visual defect inspection','外観不良検査','Camera based','H2','L2','Labelled defect images'),
('Final inspection','Mobile inspection with photo evidence','写真付きモバイル検査','Software only','H1','L1','Checklists and serials'),
('Final inspection','Automatic inspection report generation','検査報告書の自動作成','Software only','H1','L1','Inspection results'),
('Final inspection','Non-conformance pattern analysis','不適合パターンの分析','Software only','H2','L2','NCR and CAPA history'),
('Final inspection','Dispatch hold linked to inspection','検査結果に基づく出荷保留','Software only','H1','L1','Inspection and delivery orders'),
('Packaging','Label verification','ラベル照合','Software only','H1','L1','Label fields and master data'),
('Packaging','Wrong-pack detection','誤梱包の検知','Camera based','H2','L2','Pack specifications and images'),
('Packaging','Serialised traceability','シリアル単位の追跡','Software only','H1','L1','Lots, cartons and orders'),
('Logistics','Load plan optimisation','積載計画の最適化','Software only','H2','L2','Dimensions and departures'),
('Logistics','On-time delivery prediction','納期遵守の予測','Software only','H2','L2','Routes and delivery windows'),
('Logistics','Proof-of-delivery reading','配送完了書類の読み取り','Software only','H1','L1','Delivery notes and photos'),
('Planning','Daily production plan digitised','日次生産計画のデジタル化','Software only','H1','L1','Plan spreadsheets'),
('Planning','Finite-capacity scheduling','有限能力生産計画','Software only','H2','L3','Routings and capacities'),
('Planning','Demand forecasting','需要予測','Software only','H2','L2','Sales and distributor data'),
('Planning','Self-scheduling lines','自律的なライン計画','Software only','H3','L4','Mature scheduling data'),
('Quality','Quality Pareto and first-pass yield','品質パレートと直行率','Software only','H1','L1','Rejection records'),
('Quality','Quality-drift warnings','品質変動の警告','Software only','H2','L2','Inspection and batch history'),
('Quality','Closed-loop quality correction','閉ループ品質制御','Machine IoT','H3','L4','Parameters and outcomes'),
('Maintenance','Breakdown notification linked to loss','生産損失に連動する故障通知','Software only','H1','L1','Breakdown and output records'),
('Maintenance','Self-tuning machine parameters','設備パラメータの自動調整','Machine IoT','H3','L4','Parameters and outcome history'),
('R&D','Market signals as product triggers','市場情報に基づく製品開発','Software only','H2','L2','Sales, complaints and market sources'),
('R&D','BOM and cell-change simulation','部品表とセル変更の影響分析','Software only','H2','L2','BOM and routings'),
('R&D','Product-market fit hypotheses','製品市場適合の仮説検証','Software only','H1','L1','Profile and workflow answers'),
('Sales','Must-sell recommendations','販売推奨','Software only','H2','L2','Sales by customer'),
('Sales','Sales pitch role-play training','営業提案のロールプレイ','Software only','H1','L1','Product documents'),
('Sales','Competitor and review intelligence','競合とレビューの分析','Software only','H2','L2','Public sources')]
QUESTIONS={
'B1':[('employees','How many people work here?','従業員は何人ですか？'),('plants','Which plants do you operate?','どの工場を運営していますか？'),('certifications','Which certifications do you hold?','どの認証を取得していますか？'),('customers','Who are your typical customers?','主な顧客は誰ですか？'),('open_questions','What changed most in three years?','過去3年間で最も変わったことは何ですか？')],
'B2':[('function','What does this product do?','製品の機能は何ですか？'),('materials','What materials do you use?','どの材料を使いますか？'),('process','How is it manufactured?','どのように製造しますか？'),('customers','Who buys it and why?','誰がなぜ購入しますか？'),('differentiators','What makes it different?','差別化要因は何ですか？')],
'B3':[('customers','Which customer segments do you serve?','どの顧客層に提供していますか？'),('markets','Which markets do you serve?','どの市場に提供していますか？'),('differentiators','Why do customers choose you?','顧客に選ばれる理由は何ですか？'),('opportunities','Which new markets interest you?','どの新市場に関心がありますか？'),('open_questions','What evidence do you need?','どのような根拠が必要ですか？')],
'B4':[('process','Which stages exist in your plant?','工場にある工程は何ですか？'),('shifts','How many shifts do you run?','何交代制ですか？'),('systems','How are results recorded?','結果はどのように記録しますか？'),('pain_points','Which decision takes longest?','最も時間がかかる判断は何ですか？'),('data','What is counted by hand?','手作業で数えているものは何ですか？')]}
TITLES={'B1':('Company discovery','企業ディスカバリー'),'B2':('Product deep-dive','製品の深掘り'),'B3':('Market and product-market fit','市場と製品市場適合'),'B4':('Manufacturing and AI readiness','製造とAIの準備状況')}

def workflow_data(code,owner):
    qs=[{'key':k,'text':e,'text_ja':j,'answer':'','unknown':False,'assigned_to':owner} for k,e,j in QUESTIONS[code]]
    steps=[]
    types=['review','questions','upload','analysis','review','output'] if code=='B1' else ['questions','upload','analysis','review','output']
    for i,typ in enumerate(types):steps.append({'id':f'step-{i+1}','type':typ,'title':typ.title(),'status':'Not started','owner':owner,'due_date':'','questions':qs if typ=='questions' else [],'feeds':['profile'] if typ!='output' else ['profile','document'],'depends_on':[f'step-{i}'] if i else []})
    return {'template':code,'template_version':1,'steps':steps,'rationale':'Closes gaps in the verified company profile.','rationale_ja':'確認済み企業プロフィールの不足情報を補います。','outputs':[]}

def seed(reset=False):
    with SessionLocal.begin() as db:
        for wid,name,ja,slug in [(W1,'Sample Co. A','サンプル精密工業','sample-a'),(W2,'Sample Co. B','サンプル食品工業','sample-b')]:
            ws=db.get(Workspace,wid)
            if not ws:
                ws=Workspace(id=wid,name=name,name_ja=ja,slug=slug,status='Active',industry='Precision machining' if wid==W1 else 'Food manufacturing',data={'synthetic':True,'sharing':['overview','products'],'retention_months':24,'instructions':'','feedback_consent':False});db.add(ws);db.flush()
            if reset:
                for model in (Chunk,Revision,Job,Usage,Record):db.execute(delete(model).where(model.workspace_id==wid))
                ws.status='Active';ws.data={**ws.data,'sharing':['overview','products'],'feedback_consent':False};ws.revision+=1
        for i,(email,name,role,wid) in enumerate(ACCOUNTS):
            u=db.scalar(select(User).where(User.email==email))
            if not u:
                u=User(id=f'00000000-0000-4000-8000-{i+1:012d}',email=email,name=name,role=role,password=hash_password(DEMO_PASSWORD),language='en' if role in ('Super Admin','Platform Admin') else 'ja');db.add(u);db.flush()
            if wid and not db.get(Membership,(u.id,wid)):db.add(Membership(user_id=u.id,workspace_id=wid,role=role))
        if not db.scalar(select(Record.id).where(Record.workspace_id==W1,Record.kind=='fact')):
            facts=[('overview','employees','48','Stated','Confirmed'),('overview','industry','Precision machining','Stated','Confirmed'),('overview','plants','One plant in Miyazaki','Stated','Confirmed'),('products','product','Hydraulic valve bodies and manifolds','Stated','Confirmed'),('products','materials','Aluminium and steel','Stated','Confirmed'),('markets','customers','Construction-equipment OEMs','Stated','Confirmed'),('manufacturing','process','CNC machining and inspection','Stated','Confirmed'),('manufacturing','certifications','ISO 9001','Inferred','Proposed'),('opportunities','opportunities','Overseas hydraulic component applications','Inferred','Proposed'),('overview','revenue','Unsupported demo revenue claim 999 million yen','Inferred','Rejected')]
            for i,(section,key,value,prov,status) in enumerate(facts):db.add(Record(id=f'10000000-0000-4000-8000-{i+1:012d}',workspace_id=W1,kind='fact',title=key,status=status,data={'section':section,'key':key,'value':value,'provenance':prov,'confidence':0.95 if prov=='Stated' else 0.45,'why':'Synthetic demonstration record, not independently verified.','sources':[],'synthetic':True}))
            db.add(Record(workspace_id=W2,kind='fact',title='Private company B product',status='Confirmed',data={'section':'products','key':'product','value':'PRIVATE-B-SENTINEL specialty citrus paste','provenance':'Stated','confidence':1,'sources':[],'synthetic':True}))
            db.add(Record(id='30000000-0000-4000-8000-000000000001',workspace_id=W1,kind='workflow',title=TITLES['B1'][0],status='Proposed',data=workflow_data('B1',ACCOUNTS[1][0])))
            for t in ['Company introduction','Business plan','Product one-pager','Market analysis','Product-market fit report','Export readiness memo','Competitor comparison','Programme application narrative','AI use-case charter','Factory AI road map','Customer proposal','Meeting preparation brief']:
                db.add(Record(workspace_id=W1,kind='template',title=t,status='Published',data={'version':1,'language_fields':{'en':t,'ja':{'Company introduction':'会社紹介','Business plan':'事業計画','AI use-case charter':'AI活用企画書','Factory AI road map':'工場AIロードマップ'}.get(t,t)},'draft_translation':True}))
        template_names=[('Company introduction','会社紹介'),('Business plan','事業計画'),('Product one-pager','製品概要書'),('Market analysis','市場分析'),('Product-market fit report','製品市場適合レポート'),('Export readiness memo','輸出準備メモ'),('Competitor comparison','競合比較'),('Programme application narrative','支援制度申請の説明文'),('AI use-case charter','AI活用企画書'),('Factory AI road map','工場AIロードマップ'),('Customer proposal','顧客提案書'),('Meeting preparation brief','面談準備資料')]
        for wid in (W1,W2):
            existing={x.title for x in db.scalars(select(Record).where(Record.workspace_id==wid,Record.kind=='template'))}
            for en,ja in template_names:
                if en not in existing:db.add(Record(workspace_id=wid,kind='template',title=en,status='Published',data={'version':1,'language_fields':{'en':en,'ja':ja},'draft_translation':True}))
        if not db.scalar(select(Library.id)):
            for i,(stage,title,ja,entry,horizon,level,data) in enumerate(LIBRARY_ROWS):
                db.add(Library(id=f'40000000-0000-4000-8000-{i+1:012d}',title=title,title_ja=ja,stage=stage,entry=entry,horizon=horizon,level=level,status='Draft',data={'data_needed':data,'data_needed_ja':'必要データは原文を参照してください。','problem':f'Manual effort or limited visibility in {stage}.','problem_ja':f'{stage}工程の手作業と可視性の課題。','how':'Use reviewed plant records to assist human decisions.','how_ja':'確認済みの工場記録を用いて人の判断を支援します。','systems':'Existing records; no integration in this copilot.','systems_ja':'既存記録。このコパイロットでは設備連携しません。','prerequisites':'Reliable source records and a responsible owner.','prerequisites_ja':'信頼できる記録と責任者。','success':'Measure an agreed KPI before and after a pilot.','success_ja':'実証前後に合意したKPIを測定します。','content_notice':'Draft pending Atomic Loops and Japanese review','history':[]}))
