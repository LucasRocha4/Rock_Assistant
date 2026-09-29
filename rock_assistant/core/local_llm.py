"""Agente de IA local (Llama via Ollama) — cérebro padrão do Rock, com tool calling (base MCP)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Garante acesso a configurações do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from setup import config
    from core.memory import ConversationMemory
    from core.tool_schemas import get_tool_schemas
except ImportError:
    from rock_assistant.setup import config
    from rock_assistant.core.memory import ConversationMemory
    from rock_assistant.core.tool_schemas import get_tool_schemas

logger = logging.getLogger("rock.local_llm")

SYSTEM_PROMPT_DEFAULT = (
    "Você é Rock, o assistente pessoal do usuário, rodando localmente via Llama.\n"
    "Quando fizer sentido, use uma das ferramentas disponíveis (busca, lembrete, mensagem, "
    "e-mail, contato, comando ou objetivo); caso contrário, apenas responda diretamente.\n"
    "Responda em português do Brasil, com clareza, naturalidade e objetividade.\n"
    "Nunca invente fatos sobre o usuário, suas preferências ou ações já realizadas.\n"
)


@dataclass
class WarmupResult:
    """Resultado do processo de validação e pré-aquecimento do Llama."""

    ok: bool
    mode: str  # "gpu" | "cpu" | "unavailable"
    model: str
    detail: str  # Mensagem explicativa humana
    log_lines: List[str] = field(default_factory=list)
    error: Optional[str] = None
    latency_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "model": self.model,
            "detail": self.detail,
            "log_lines": self.log_lines,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


def is_gpu_error(error_text: str) -> bool:
    """Detecta se a falha de execução/inferência decorre de GPU, Vulkan ou DeviceLost."""
    if not error_text:
        return False
    lower = error_text.lower()
    patterns = [
        "errordevicelost",
        "devicelost",
        "vk::",
        "vulkan",
        "vk_error",
        "model runner has unexpectedly stopped",
        "llama-server process has terminated",
        "cuda",
        "out of memory",
        "gpu",
        "device memory",
        "driver",
    ]
    return any(p in lower for p in patterns)


class LocalLLMAgent:
    """Agente padrão do Rock: conversa com um modelo Llama local servido pelo Ollama."""

    def __init__(
        self,
        model: Optional[str] = None,
        host: Optional[str] = None,
        system_prompt: Optional[str] = None,
        memory: Optional[ConversationMemory] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.model = model or getattr(config, "OLLAMA_MODEL", "llama3.2")
        self.host = host or getattr(config, "OLLAMA_HOST", "http://localhost:11434")
        self.system_prompt = system_prompt or SYSTEM_PROMPT_DEFAULT
        self.memory = memory
        self.timeout = timeout or getattr(config, "OLLAMA_TIMEOUT", 60)
        self.warmup_timeout = getattr(config, "OLLAMA_WARMUP_TIMEOUT", 30)

        self._client = None
        self._server_confirmed = False
        self._ready = False
        self._mode = "unavailable"
        self._process: Optional[subprocess.Popen] = None
        self._started_by_app = False
        self._last_warmup: Optional[WarmupResult] = None

    def _get_client(self):
        if self._client is None:
            from ollama import Client

            self._client = Client(host=self.host, timeout=self.timeout)
        return self._client

    def is_ready(self) -> bool:
        """Indica se o Llama passou no warmup e está pronto para inferência nesta sessão."""
        return self._ready

    def set_ready(self, ready: bool, mode: str = "gpu") -> None:
        """Define explicitamente o estado de prontidão e modo do agente."""
        self._ready = ready
        self._mode = mode if ready else "unavailable"

    def get_mode(self) -> str:
        return self._mode

    def get_last_warmup(self) -> Optional[WarmupResult]:
        return self._last_warmup

    def _start_daemon(self, force_cpu: bool = False) -> bool:
        """Inicia `ollama serve` como subprocesso caso configurado."""
        if not getattr(config, "OLLAMA_AUTOSTART", True):
            return False

        env = os.environ.copy()
        if force_cpu:
            env["OLLAMA_NUM_GPU"] = "0"
            env["CUDA_VISIBLE_DEVICES"] = ""
        elif getattr(config, "OLLAMA_NUM_GPU", ""):
            env["OLLAMA_NUM_GPU"] = str(config.OLLAMA_NUM_GPU)

        try:
            self._process = subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._started_by_app = True
            logger.info("Subprocesso 'ollama serve' iniciado pelo Rock (force_cpu=%s).", force_cpu)
            return True
        except (FileNotFoundError, OSError) as exc:
            logger.warning("Não foi possível iniciar 'ollama serve' automaticamente: %s", exc)
            return False

    def restart_ollama(self, force_cpu: bool = True) -> bool:
        """Reinicia o servidor Ollama (se iniciado pelo app ou via comando do sistema)."""
        import requests

        logger.info("Reiniciando Ollama com force_cpu=%s...", force_cpu)

        # 1. Tenta parar o modelo carregado
        try:
            subprocess.run(["ollama", "stop", self.model], capture_output=True, timeout=5)
        except Exception:
            pass

        # 2. Se foi iniciado pelo Rock, encerra o subprocesso
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        # 3. Inicia novo processo com force_cpu
        self._start_daemon(force_cpu=force_cpu)

        # 4. Aguarda o daemon voltar
        for _ in range(12):
            time.sleep(1)
            try:
                r = requests.get(f"{self.host}/api/tags", timeout=2)
                if r.status_code == 200:
                    self._client = None
                    return True
            except requests.RequestException:
                continue

        return False

    def _ensure_server_running(self, force_cpu: bool = False) -> bool:
        """Verifica se o Ollama está no ar; tenta iniciar `ollama serve` se necessário."""
        import requests

        try:
            requests.get(f"{self.host}/api/tags", timeout=2)
            return True
        except requests.RequestException:
            pass

        if not self._start_daemon(force_cpu=force_cpu):
            return False

        for _ in range(10):
            time.sleep(1)
            try:
                requests.get(f"{self.host}/api/tags", timeout=2)
                return True
            except requests.RequestException:
                continue
        return False

    def is_available(self) -> bool:
        """Confirma apenas se o daemon Ollama responde na porta (sem validação de carga)."""
        if not self._server_confirmed:
            self._server_confirmed = self._ensure_server_running()
        return self._server_confirmed

    def warmup(
        self,
        force_cpu: bool = False,
        chat_timeout: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> WarmupResult:
        """Executa validação completa em 3 etapas: daemon, modelo e inferência real."""
        import requests

        logs: List[str] = []

        def log_step(msg: str) -> None:
            ts = time.strftime("%H:%M:%S")
            line = f"[{ts}] {msg}"
            logs.append(line)
            logger.info("Warmup: %s", msg)
            if progress_callback:
                try:
                    progress_callback(msg)
                except Exception:
                    pass

        timeout_sec = chat_timeout or self.warmup_timeout
        mode_str = "cpu" if force_cpu else "gpu"

        log_step(f"Iniciando pré-aquecimento do Llama (modelo: '{self.model}', modo: {mode_str})...")

        # ETAPA 1: Validar daemon Ollama
        log_step(f"Etapa 1/3: Conectando ao daemon Ollama em {self.host}...")
        server_ok = self._ensure_server_running(force_cpu=force_cpu)
        if not server_ok:
            err_msg = f"Servidor Ollama não está acessível em {self.host}."
            log_step(f"❌ Falha: {err_msg}")
            result = WarmupResult(
                ok=False,
                mode="unavailable",
                model=self.model,
                detail="Ollama offline. Verifique se o daemon está em execução.",
                log_lines=logs,
                error=err_msg,
            )
            self._last_warmup = result
            self.set_ready(False)
            return result

        log_step("✅ Daemon Ollama respondendo com sucesso.")

        # ETAPA 2: Validar presença do modelo
        log_step(f"Etapa 2/3: Verificando disponibilidade do modelo '{self.model}'...")
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3)
            tags_data = resp.json()
            available_models = [m.get("name", "") for m in tags_data.get("models", [])]
            log_step(f"Modelos encontrados no Ollama: {available_models}")

            model_found = any(
                m == self.model
                or m == f"{self.model}:latest"
                or m.startswith(f"{self.model}:")
                or self.model in m
                for m in available_models
            )
            if not model_found:
                err_msg = f"Modelo '{self.model}' não foi encontrado. Baixe com 'ollama pull {self.model}'."
                log_step(f"❌ Falha: {err_msg}")
                result = WarmupResult(
                    ok=False,
                    mode="unavailable",
                    model=self.model,
                    detail=f"Modelo '{self.model}' não baixado.",
                    log_lines=logs,
                    error=err_msg,
                )
                self._last_warmup = result
                self.set_ready(False)
                return result

            log_step(f"✅ Modelo '{self.model}' verificado localmente.")
        except Exception as exc:
            err_msg = f"Erro ao consultar lista de modelos: {exc}"
            log_step(f"❌ Falha: {err_msg}")
            result = WarmupResult(
                ok=False,
                mode="unavailable",
                model=self.model,
                detail="Falha ao listar modelos do Ollama.",
                log_lines=logs,
                error=err_msg,
            )
            self._last_warmup = result
            self.set_ready(False)
            return result

        # ETAPA 3: Teste de inferência real
        log_step(f"Etapa 3/3: Executando inferência de teste (timeout: {timeout_sec}s)...")
        start_time = time.perf_counter()
        try:
            client = self._get_client()
            client.timeout = timeout_sec
            response = client.chat(
                model=self.model,
                messages=[{"role": "user", "content": "ok"}],
                options={"num_predict": 5, "temperature": 0.0},
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            content = (response.get("message", {}).get("content") or "").strip()

            log_step(f"✅ Inferência concluída com sucesso em {elapsed_ms:.1f}ms. Resposta: '{content}'")
            result = WarmupResult(
                ok=True,
                mode=mode_str,
                model=self.model,
                detail=f"Llama {self.model} pronto ({mode_str.upper()}). Latência: {elapsed_ms:.0f}ms.",
                log_lines=logs,
                latency_ms=elapsed_ms,
            )
            self._last_warmup = result
            self.set_ready(True, mode=mode_str)
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            err_str = str(exc)
            log_step(f"❌ Falha na inferência após {elapsed_ms:.1f}ms: {err_str}")

            detail_msg = "Falha ao carregar ou executar inferência no Llama."
            if is_gpu_error(err_str):
                detail_msg = "Erro de GPU/Vulkan (DeviceLost ou modelo interrompido inesperadamente)."

            result = WarmupResult(
                ok=False,
                mode="unavailable",
                model=self.model,
                detail=detail_msg,
                log_lines=logs,
                error=err_str,
                latency_ms=elapsed_ms,
            )
            self._last_warmup = result
            self.set_ready(False)
            return result

    def _build_messages(
        self,
        user_input: str,
        memory: Optional[ConversationMemory],
        extra_system_prompt: Optional[str],
    ) -> List[Dict[str, Any]]:
        system = self.system_prompt
        if extra_system_prompt:
            system = f"{system}\n{extra_system_prompt}"
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]

        active_memory = memory or self.memory
        if active_memory:
            for entry in active_memory.get_history():
                role = "assistant" if entry.get("role") == "assistant" else "user"
                messages.append({"role": role, "content": entry.get("content", "")})

        messages.append({"role": "user", "content": user_input})
        return messages

    def chat(
        self,
        user_input: str,
        memory: Optional[ConversationMemory] = None,
        extra_system_prompt: Optional[str] = None,
    ) -> str:
        """Conversa simples e direta com short-circuit imediato se não estiver pronto."""
        cleaned = (user_input or "").strip()
        if not cleaned:
            return "Nenhuma entrada fornecida para o Rock."

        # Short-circuit imediato no modo degradado para não travar o usuário
        if not self.is_ready():
            return (
                "⚠️ [Modo Degradado] O Llama local não está ativo nesta sessão.\n"
                "💡 Lembretes, contatos, comandos e buscas continuam operando normalmente."
            )

        try:
            client = self._get_client()
            messages = self._build_messages(cleaned, memory, extra_system_prompt)
            response = client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": getattr(config, "OLLAMA_TEMPERATURE", 0.2)},
            )
            return (response["message"]["content"] or "").strip()
        except Exception as exc:
            logger.error("Erro ao conversar com Llama local: %s", exc)
            return f"❌ [Rock Local] Erro ao consultar o modelo local: {exc}"

    def converse_with_tools(
        self,
        user_input: str,
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        memory: Optional[ConversationMemory] = None,
        extra_system_prompt: Optional[str] = None,
    ) -> str:
        """Fluxo estilo MCP com short-circuit se o modelo não estiver pronto."""
        cleaned = (user_input or "").strip()
        if not cleaned:
            return "Nenhuma entrada fornecida para o Rock."

        if not self.is_ready():
            return self.chat(cleaned, memory=memory, extra_system_prompt=extra_system_prompt)

        try:
            client = self._get_client()
            messages = self._build_messages(cleaned, memory, extra_system_prompt)
            response = client.chat(
                model=self.model,
                messages=messages,
                tools=get_tool_schemas(),
                options={"temperature": getattr(config, "OLLAMA_TEMPERATURE", 0.2)},
            )
            message = response["message"]
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return (message.get("content") or "").strip()

            call = tool_calls[0]
            function = call.get("function", {})
            tool_name = function.get("name", "")
            raw_arguments = function.get("arguments", {})
            arguments = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments or "{}")

            tool_result = tool_executor(tool_name, arguments)

            messages.append({"role": "assistant", "content": message.get("content", ""), "tool_calls": tool_calls})
            messages.append({"role": "tool", "content": json.dumps(tool_result, ensure_ascii=False, default=str)})

            follow_up = client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": getattr(config, "OLLAMA_TEMPERATURE", 0.2)},
            )
            return (follow_up["message"]["content"] or "").strip()
        except Exception as exc:
            logger.error("Erro no fluxo de tool calling com Llama local: %s", exc)
            return f"❌ [Rock Local] Erro ao processar a solicitação com ferramentas: {exc}"
