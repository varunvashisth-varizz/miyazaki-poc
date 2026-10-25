import os
os.environ['DATABASE_URL']=os.environ.get('TEST_DATABASE_URL','postgresql+psycopg://miyazaki@127.0.0.1:55432/miyazaki_security_demo')
os.environ['START_WORKERS']='false'
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.db import engine, SessionLocal
from app.migrations import migrate
from app.seed import seed,DEMO_PASSWORD

@pytest.fixture(scope='session',autouse=True)
def database():
    if 'security_demo' not in str(engine.url):raise RuntimeError('Tests require a separate database named *_security_demo.')
    migrate()
    with engine.begin() as c:
        tables=[r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename!='schema_version'"))]
        if tables:c.execute(text('TRUNCATE '+','.join('"'+t+'"' for t in tables)+' CASCADE'))
    seed()

@pytest.fixture
def client():
    with TestClient(app,raise_server_exceptions=False) as c:yield c

def sign_in(client,email='company@demo.local'):
    r=client.post('/api/v1/auth/login',json={'email':email,'password':DEMO_PASSWORD})
    assert r.status_code==200,r.text
    client.headers['X-CSRF-Token']=r.json()['csrf'];return r.json()

@pytest.fixture
def company(client):sign_in(client);return client

@pytest.fixture
def admin(client):sign_in(client,'admin@demo.local');return client

@pytest.fixture
def platform(client):sign_in(client,'platform@demo.local');return client
