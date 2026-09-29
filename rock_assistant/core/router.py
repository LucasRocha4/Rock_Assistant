"""Gerenciamento de roteamento entre intenção e ferramenta correta."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("rock.router")


class Router:
    """Encapsula a lógica de direcionar uma intenção para uma ferramenta."""

    def __init__(self) -> None:
        self.routes: Dict[str, Any] = {}

    def register(self, intent: str, handler: Any) -> None:
        """Registra uma função ou objeto responsável por uma intenção."""
        self.routes[intent] = handler
        logger.debug("Rota registrada para intent '%s'", intent)

    def route(self, intent: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        """Envia a ação para o manipulador correspondente."""
        handler = self.routes.get(intent)
        if handler is None:
            logger.error("Nenhum manipulador registrado para a intenção: '%s'", intent)
            raise ValueError(f"Nenhum manipulador registrado para a intenção: {intent}")

        if payload is None:
            payload = {}

        logger.info("Roteando intent '%s' com payload: %s", intent, payload)
        try:
            result = handler(payload)
            logger.debug("Execução da rota '%s' concluída com sucesso.", intent)
            return result
        except Exception as exc:
            logger.error("Erro ao executar rota para intent '%s': %s", intent, exc)
            raise
