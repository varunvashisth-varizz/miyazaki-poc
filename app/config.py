from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://miyazaki:miyazaki@localhost:5432/miyazaki_demo'
    host: str = '127.0.0.1'
    port: int = 8000
    ollama_base_url: str = 'http://127.0.0.1:11434'
    generation_model: str = 'qwen2.5:3b'
    embedding_model: str = 'bge-m3'
    embedding_dimension: int = 1024
    data_dir: str = 'data'
    mail_backend: str = 'outbox'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = ''
    smtp_sender: str = 'copilot@localhost'
    demo_mode: bool = True
    demo_skip_mfa: bool = True
    cookie_secure: bool = False
    token_budget: int = 1000000
    context_tokens: int = 8192
    model_timeout: int = 180
    fixture_mode: bool = True
    start_workers: bool = True
    upload_limit: int = 25 * 1024 * 1024
    workspace_quota: int = 1024 * 1024 * 1024
    allowed_hosts: str = 'localhost,127.0.0.1,testserver'
    def storage(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else ROOT / p
    def validate_runtime(self):
        if not self.demo_mode and (self.demo_skip_mfa or not self.cookie_secure or self.mail_backend == 'outbox'):
            raise ValueError('Production requires MFA, secure cookies and a configured delivery backend.')
        if self.host not in ('127.0.0.1', 'localhost', '::1') and self.demo_mode:
            raise ValueError('Demo mode binds to localhost only. Configure a secured production deployment for network access.')

settings = Settings()
