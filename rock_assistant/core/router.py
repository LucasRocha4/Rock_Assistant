"""Gerenciamento de roteamento entre intenção e ferramenta correta."""

from typing import Any, Dict, Optional


class Router:
    """Encapsula a lógica de direcionar uma intenção para uma ferramenta."""

    def __init__(self) -> None:
        self.routes: Dict[str, Any] = {}

    def register(self, intent: str, handler: Any) -> None:
        """Registra uma função ou objeto responsável por uma intenção."""
        self.routes[intent] = handler

    def route(self, intent: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        """Envia a ação para o manipulador correspondente."""
        handler = self.routes.get(intent)
        if handler is None:
            raise ValueError(f"Nenhum manipulador registrado para a intenção: {intent}")

        if payload is None:
            payload = {}

        return handler(payload)
