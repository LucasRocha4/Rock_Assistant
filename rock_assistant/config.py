import os
from pathlib import Path


try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(dotenv_path: Path) -> None:
        if not dotenv_path.exists():
            return
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip("\"'"))

# ==========================================
# 1. DIRETÓRIOS E ESTRUTURA DO SISTEMA
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

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
GEMINI_MODEL_ROUTER = os.getenv("GEMINI_MODEL_ROUTER", "gemini-flash-lite-latest")

# Modelo Especialista/Operário (Análise densa, código, síntese e raciocínio complexo)
GEMINI_MODEL_SPECIALIST = os.getenv("GEMINI_MODEL_SPECIALIST", "gemini-3.1-flash-lite")

LLM_ROUTER_ENABLED = os.getenv("LLM_ROUTER_ENABLED", "False").lower() in {"true", "1", "yes"}

# Configurações de geração para respostas objetivas e rápidas
GEMINI_GENERATION_CONFIG = {
    "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
    "top_p": float(os.getenv("GEMINI_TOP_P", "0.95")),
}
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "512"))

GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "30"))

# ==========================================
# 2.1 CONFIGURAÇÃO DA WHATSAPP CLOUD API
# ==========================================
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_ACCESS_TOKEN = os.getenv(
    "PERMA_META_ACCESS_TOKEN",
    os.getenv("META_ACCESS_TOKEN", ""),
)
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")
META_GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v23.0")
META_GRAPH_API_URL = os.getenv(
    "META_GRAPH_API_URL",
    f"https://graph.facebook.com/{META_GRAPH_API_VERSION}",
).rstrip("/")
META_REQUEST_TIMEOUT = int(os.getenv("META_REQUEST_TIMEOUT", "15"))

# ==========================================
# 3. MAPEAMENTO DE ESTRUTURA DE PAYLOADS
# ==========================================
# Garante que o Router saiba quais chaves padrão esperar de cada intenção
PAYLOAD_SCHEMAS = {
    "search": ["query", "mode", "max_results"],
    "reminder": ["text", "when", "kind", "importance"],
    "command": ["command"],
    "message": ["target", "text"],
    "email": ["operation", "message_id", "to", "subject", "body", "query"],
    "general": ["text"],
}

# ==========================================
# 3.1 LIMITES DA BUSCA WEB
# ==========================================
SEARCH_INITIAL_TIMEOUT = float(os.getenv("SEARCH_INITIAL_TIMEOUT", "7"))
SEARCH_DEADLINE = float(os.getenv("SEARCH_DEADLINE", "200"))
SEARCH_SCALE_INTERVAL = float(os.getenv("SEARCH_SCALE_INTERVAL", "15"))
SEARCH_TARGET_INITIAL_WORKERS = int(os.getenv("SEARCH_TARGET_INITIAL_WORKERS", "5"))
SEARCH_MAX_WORKERS = int(os.getenv("SEARCH_MAX_WORKERS", "20"))
SEARCH_BULK_WORKERS = int(os.getenv("SEARCH_BULK_WORKERS", "10"))
SEARCH_HTTP_TIMEOUT = float(os.getenv("SEARCH_HTTP_TIMEOUT", "8"))
SEARCH_ENRICH_RESULTS = os.getenv("SEARCH_ENRICH_RESULTS", "False").lower() in {"true", "1", "yes"}
SEARCH_ALLOW_DYNAMIC = os.getenv("SEARCH_ALLOW_DYNAMIC", "False").lower() in {"true", "1", "yes"}

# ==========================================
# 4. PERSISTÊNCIA E INTEGRAÇÕES EXTERNAS
# ==========================================
DB_PATH = Path(os.getenv("DB_PATH", "rock_assistant/data/rock.db"))
if not DB_PATH.is_absolute():
    DB_PATH = PROJECT_ROOT / DB_PATH
MEMORY_FILE = DATA_DIR / "memory.json"
MAX_MEMORY_MESSAGES = int(os.getenv("MAX_MEMORY_MESSAGES", "7"))

GOOGLE_CREDENTIALS_FILE = DATA_DIR / "credentials.json"
GOOGLE_TOKEN_FILE = DATA_DIR / "token.json"
GMAIL_TOKEN_FILE = Path(os.getenv("GMAIL_TOKEN_FILE", str(DATA_DIR / "gmail_token.json")))
if not GMAIL_TOKEN_FILE.is_absolute():
    GMAIL_TOKEN_FILE = PROJECT_ROOT / GMAIL_TOKEN_FILE
GMAIL_SCOPES = [
    scope.strip()
    for scope in os.getenv(
        "GMAIL_SCOPES",
        "https://www.googleapis.com/auth/gmail.modify",
    ).split(",")
    if scope.strip()
]
GMAIL_MONITORING_ENABLED = os.getenv("GMAIL_MONITORING_ENABLED", "False").lower() in {
    "true",
    "1",
    "yes",
}
GMAIL_MAX_MESSAGES = int(os.getenv("GMAIL_MAX_MESSAGES", "10"))
GMAIL_USER_ID = os.getenv("GMAIL_USER_ID", "me")
GMAIL_DELEGATIONS_FILE = Path(
    os.getenv("GMAIL_DELEGATIONS_FILE", str(DATA_DIR / "gmail_delegations.json"))
)
if not GMAIL_DELEGATIONS_FILE.is_absolute():
    GMAIL_DELEGATIONS_FILE = PROJECT_ROOT / GMAIL_DELEGATIONS_FILE
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
TTS_BACKEND = os.getenv("TTS_BACKEND", "piper")
PIPER_COMMAND = os.getenv("PIPER_COMMAND", "piper")
PIPER_MODEL_PATH = Path(
    os.getenv("PIPER_MODEL_PATH", str(PROJECT_ROOT / "models" / "piper" / "pt_BR-faber-medium.onnx"))
)
TTS_PLAYER = os.getenv("TTS_PLAYER", "")
TTS_TEMP_DIR = Path(os.getenv("TTS_TEMP_DIR")) if os.getenv("TTS_TEMP_DIR") else None


def get_credentials_path() -> Path:
    """Retorna o caminho do credentials.json dentro da pasta data."""
    return GOOGLE_CREDENTIALS_FILE


def get_token_path() -> Path:
    """Retorna o caminho do token.json dentro da pasta data."""
    return GOOGLE_TOKEN_FILE