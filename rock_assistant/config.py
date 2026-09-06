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
GEMINI_MODEL_SPECIALIST = os.getenv("GEMINI_MODEL_SPECIALIST", "gemini-2.5-pro")

LLM_ROUTER_ENABLED = os.getenv("LLM_ROUTER_ENABLED", "False").lower() in {"true", "1", "yes"}

# Configurações de geração para respostas objetivas e rápidas
GEMINI_GENERATION_CONFIG = {
    "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
    "top_p": float(os.getenv("GEMINI_TOP_P", "0.95")),
}

GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "10"))

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
MAX_MEMORY_MESSAGES = int(os.getenv("MAX_MEMORY_MESSAGES", "7"))
PROJECT_ROOT = BASE_DIR.parent

GOOGLE_CREDENTIALS_FILE = DATA_DIR / "credentials.json"
GOOGLE_TOKEN_FILE = DATA_DIR / "token.json"
# ==========================================
# 5. CONFIGURAÇÃO DE ÁUDIO E VOZ (FASE 3)
# ==========================================
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "True").lower() in {"true", "1", "yes"}
STT_MODEL = os.getenv("STT_MODEL", "base")  # "tiny", "base", "small"
TTS_RATE = int(os.getenv("TTS_RATE", "175"))  # Palavras por minuto
TTS_VOLUME = float(os.getenv("TTS_VOLUME", "0.75"))  # 0.0 a 1.0
VOICE_LANGUAGE = os.getenv("VOICE_LANGUAGE", "pt-BR")
MICROPHONE_INDEX = os.getenv("MICROPHONE_INDEX", "0")
MICROPHONE_NAME = os.getenv("MICROPHONE_NAME", "")


def get_credentials_path() -> Path:
    """Retorna o caminho do credentials.json dentro da pasta data."""
    return GOOGLE_CREDENTIALS_FILE


def get_token_path() -> Path:
    """Retorna o caminho do token.json dentro da pasta data."""
    return GOOGLE_TOKEN_FILE