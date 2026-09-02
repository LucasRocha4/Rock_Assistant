"""Ferramentas para execução segura de comandos locais e utilitários no Kali Linux."""

import re
import shutil
import socket
import subprocess
from typing import Any, Dict, List, Optional


# Padrões de comandos com alto risco de destruição de dados
BLOCKED_COMMANDS = [
    r"\brm\s+-[rf]*\s+/(?:\s|$)",
    r"\bmkfs\b",
    r"\bdd\s+if=.*\s+of=/dev/sd",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;",
    r">\s*/dev/sda",
]


def is_command_safe(command: str) -> bool:
    """Verifica se o comando contém instruções destrutivas críticas."""
    for pattern in BLOCKED_COMMANDS:
        if re.search(pattern, command):
            return False
    return True


def get_local_ip() -> str:
    """Identifica o endereço IP local da máquina usando socket e comandos de rede."""
    # 1. Tenta identificar via socket UDP (sem enviar tráfego real)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    # 2. Tenta obter através do comando 'ip -4 addr' ou 'ip a'
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            ips = re.findall(r"inet\s+(\d+\.\d+\.\d+\.\d+)/\d+", result.stdout)
            for found_ip in ips:
                if not found_ip.startswith("127."):
                    return found_ip
            if ips:
                return ips[0]
    except Exception:
        pass

    # 3. Fallback através do hostname do sistema
    try:
        hostname = socket.gethostname()
        resolved = socket.gethostbyname(hostname)
        if resolved:
            return resolved
    except Exception:
        pass

    return "127.0.0.1"


def launch_terminal() -> str:
    """Tenta abrir um emulador de terminal disponível no ambiente Kali Linux."""
    terminals = [
        "qterminal",
        "xfce4-terminal",
        "x-terminal-emulator",
        "gnome-terminal",
        "alacritty",
        "konsole",
        "kitty",
        "xterm",
    ]
    for term in terminals:
        if shutil.which(term):
            try:
                subprocess.Popen([term], start_new_session=True)
                return f"🖥️ Terminal '{term}' aberto com sucesso."
            except Exception as exc:
                return f"Falha ao iniciar terminal '{term}': {exc}"
    return "⚠️ Nenhum emulador de terminal gráfico compatível foi encontrado no sistema."


def run_system_command(command: str, timeout: Optional[int] = 30) -> str:
    """Executa um comando no shell do Kali Linux e retorna a saída formatada.

    Args:
        command: Comando a ser executado.
        timeout: Tempo máximo de execução em segundos (padrão: 30s).

    Returns:
        Saída padrão ou erro do comando em formato de texto.
    """
    cleaned_command = (command or "").strip()
    if not cleaned_command:
        return "Nenhum comando fornecido para execução."

    if not is_command_safe(cleaned_command):
        return f"❌ Comando bloqueado por segurança: '{cleaned_command}'."

    # Atalho para abertura de terminal
    if cleaned_command.lower() in {"abrir terminal", "open terminal", "terminal", "iniciar terminal"}:
        return launch_terminal()

    try:
        result = subprocess.run(
            cleaned_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode == 0:
            return stdout if stdout else "Comando executado com sucesso (sem saída)."

        # Em caso de código de erro
        err_msg = stderr if stderr else stdout
        if "not found" in err_msg.lower() or "não encontrado" in err_msg.lower():
            return f"⚠️ Utilitário não encontrado no sistema: {err_msg}"
        return f"❌ Erro na execução (código {result.returncode}):\n{err_msg}"

    except subprocess.TimeoutExpired:
        return f"⏱️ Comando excedeu o tempo limite de {timeout} segundos."
    except Exception as exc:
        return f"❌ Falha inesperada ao executar comando: {exc}"


def run_nmap_scan(target: str = "127.0.0.1", options: str = "-F", timeout: int = 60) -> str:
    """Executa um escaneamento nmap básico contra o alvo.

    Caso o binário nmap não esteja instalado, realiza um diagnóstico alternativo
    de portas comuns locais usando socket.
    """
    cleaned_target = target.strip() if target else "127.0.0.1"
    
    if shutil.which("nmap"):
        cmd = f"nmap {options} {cleaned_target}"
        return run_system_command(cmd, timeout=timeout)

    # Caso nmap não esteja presente no Kali Linux
    info_header = (
        f"⚠️ O utilitário 'nmap' não foi encontrado no PATH do sistema.\n"
        f"💡 Para instalar: sudo apt update && sudo apt install -y nmap\n\n"
        f"🔍 Executando diagnóstico alternativo de portas abertas em {cleaned_target}..."
    )

    common_ports = [21, 22, 53, 80, 443, 3000, 3306, 5432, 8000, 8080, 11434]
    open_ports = []

    for port in common_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex((cleaned_target, port)) == 0:
                    open_ports.append(port)
        except Exception:
            pass

    diag_lines = [info_header, f"\nAlvo: {cleaned_target}"]
    if open_ports:
        diag_lines.append(f"Portas locais ativas detectadas: {', '.join(map(str, open_ports))}")
    else:
        diag_lines.append("Nenhuma das portas comuns (21, 22, 80, 443, 8080, 11434, etc.) respondeu na checagem rápida.")

    return "\n".join(diag_lines)


class SystemCommandTool:
    """Wrapper orientado a objetos para comandos e diagnósticos do sistema operacional."""

    def __init__(self) -> None:
        self.name = "system_command"

    def execute(self, command: str, timeout: Optional[int] = 30) -> str:
        """Executa um comando de terminal."""
        return run_system_command(command=command, timeout=timeout)

    def get_ip(self) -> str:
        """Obtém o IP local da máquina."""
        return get_local_ip()

    def nmap(self, target: str = "127.0.0.1", options: str = "-F", timeout: int = 60) -> str:
        """Executa varredura de portas com nmap ou diagnóstico de portas."""
        return run_nmap_scan(target=target, options=options, timeout=timeout)

    def open_terminal(self) -> str:
        """Abre o terminal local."""
        return launch_terminal()

