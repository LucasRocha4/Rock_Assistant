"""Stub do futuro manipulador de chamadas via Asterisk (ARI). Sem lógica implementada ainda."""

from typing import Any, Dict, Optional


class CallHandler:
    """Vai receber eventos do Asterisk ARI e conduzir a ligação como assistente."""

    def __init__(self, ari_client: Optional[Any] = None) -> None:
        self.ari_client = ari_client
        # TODO: conectar ao WebSocket de eventos do Asterisk ARI quando a integração começar.

    def start_outbound_call(self, recipient: str, script: Optional[str] = None) -> Dict[str, Any]:
        """Vai originar uma chamada via ARI e conduzir o diálogo."""
        # TODO: implementar originação de chamada via Asterisk ARI (endpoint /channels).
        raise NotImplementedError("Integração com Asterisk ARI ainda não implementada.")

    def handle_incoming_call(self, channel_id: str) -> Dict[str, Any]:
        """Vai atender uma chamada recebida e conduzir o diálogo como assistente."""
        # TODO: implementar atendimento (answer) e streaming de áudio via Asterisk ARI.
        raise NotImplementedError("Integração com Asterisk ARI ainda não implementada.")
