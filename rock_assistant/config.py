import os
from pathlib import Path

# ==========================================
# 1. DIRETÓRIOS E ESTRUTURA DO SISTEMA
# ==========================================
BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

# Cria automaticamente os diretórios se não existirem
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

APP_NAME = "Rock Assistant"
VERSION = "0.1.0-alpha"

# ==========================================
# 2. CONFIGURAÇÃO DE LLMS (GOOGLE GEMINI API)
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Modelo Roteador/Decisor (Lê input, decide ação e extrai parâmetros em JSON)
GEMINI_MODEL_ROUTER = os.getenv("GEMINI_MODEL_ROUTER", "gemini-2.0-flash-lite")

# Modelo Especialista/Operário (Análise densa, código, síntese e raciocínio complexo)
GEMINI_MODEL_SPECIALIST = os.getenv("GEMINI_MODEL_SPECIALIST", "gemini-2.0-flash")

LLM_ROUTER_ENABLED = os.getenv("LLM_ROUTER_ENABLED", "False").lower() in {"true", "1", "yes"}

# Configurações de geração para respostas objetivas e rápidas
GEMINI_GENERATION_CONFIG = {
    "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
    "top_p": float(os.getenv("GEMINI_TOP_P", "0.95")),
}

GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "30"))

# ==========================================
# 3. MAPEAMENTO DE ESTRUTURA DE PAYLOADS
# ==========================================
# Garante que o Router saiba quais chaves padrão esperar de cada intenção
PAYLOAD_SCHEMAS = {
    "search": ["query"],
    "reminder": ["text", "when"],
    "command": ["command"],
    "message": ["target", "text"],
    "general": ["text"],
}

# ==========================================
# 4. PERSISTÊNCIA E INTEGRAÇÕES EXTERNAS
# ==========================================
DB_PATH = DATA_DIR / "rock.db"
MEMORY_FILE = DATA_DIR / "memory.json"
MAX_MEMORY_MESSAGES = int(os.getenv("MAX_MEMORY_MESSAGES", "10"))
PROJECT_ROOT = BASE_DIR.parent

GOOGLE_CREDENTIALS_FILE = BASE_DIR / "credentials.json"
GOOGLE_TOKEN_FILE = BASE_DIR / "token.json"
# ==========================================
# 5. CONFIGURAÇÃO DE ÁUDIO E VOZ (FASE 3)
# ==========================================
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "True").lower() in {"true", "1", "yes"}
STT_MODEL = os.getenv("STT_MODEL", "tiny")  # "tiny", "base", "small"
TTS_RATE = int(os.getenv("TTS_RATE", "175"))  # Palavras por minuto
TTS_VOLUME = float(os.getenv("TTS_VOLUME", "1.0"))  # 0.0 a 1.0
VOICE_LANGUAGE = os.getenv("VOICE_LANGUAGE", "pt-BR")
MICROPHONE_INDEX = os.getenv("MICROPHONE_INDEX", "0")
MICROPHONE_NAME = os.getenv("MICROPHONE_NAME", "")


def get_credentials_path() -> Path:
    """Retorna o caminho do credentials.json priorizando existência."""
    if GOOGLE_CREDENTIALS_FILE.exists():
        return GOOGLE_CREDENTIALS_FILE
    root_creds = PROJECT_ROOT / "credentials.json"
    if root_creds.exists():
        return root_creds
    return GOOGLE_CREDENTIALS_FILE


def get_token_path() -> Path:
    """Retorna o caminho do token.json priorizando existência."""
    if GOOGLE_TOKEN_FILE.exists():
        return GOOGLE_TOKEN_FILE
    root_token = PROJECT_ROOT / "token.json"
    if root_token.exists():
        return root_token
    return GOOGLE_TOKEN_FILE