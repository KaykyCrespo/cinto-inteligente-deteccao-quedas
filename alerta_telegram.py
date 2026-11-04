"""
alerta_telegram.py - Envio de alerta de queda via bot do Telegram.

Configuração (variáveis de ambiente, nunca no código/git):
    OQPNB_TG_TOKEN  token do bot (BotFather)
    OQPNB_TG_CHAT   chat_id do destinatário (pessoa: positivo; grupo: negativo)

    PowerShell:  $env:OQPNB_TG_TOKEN="123:ABC..."; $env:OQPNB_TG_CHAT="123456789"

Uso:
    from alerta_telegram import configurado, enviar, mensagem_queda
    if configurado():
        enviar(mensagem_queda(...), callback=lambda ok, erro: ...)
"""
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

TOKEN = os.environ.get("OQPNB_TG_TOKEN", "").strip()
CHAT_ID = os.environ.get("OQPNB_TG_CHAT", "").strip()
TIMEOUT_S = 5
TENTATIVAS = 2


def configurado() -> bool:
    return bool(TOKEN and CHAT_ID)


def _post(texto: str) -> bool:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dados = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": texto}).encode()
    with urllib.request.urlopen(url, data=dados, timeout=TIMEOUT_S) as r:
        return bool(json.loads(r.read().decode("utf-8")).get("ok"))


def enviar_sincrono(texto: str):
    """Retorna (ok, erro). Faz até TENTATIVAS tentativas."""
    erro = None
    for _ in range(TENTATIVAS):
        try:
            if _post(texto):
                return True, None
            erro = "Telegram respondeu ok=false"
        except urllib.error.HTTPError as e:
            descricao = str(e.reason)
            try:
                resposta = json.loads(e.read().decode("utf-8"))
                if isinstance(resposta, dict) and isinstance(resposta.get("description"), str):
                    descricao = resposta["description"]
            except (ValueError, OSError):
                pass
            if TOKEN:
                descricao = descricao.replace(TOKEN, "[token oculto]")
            erro = f"Telegram HTTP {e.code}: {descricao}"
            if e.code in (400, 401, 403, 404):
                return False, erro
        except Exception as e:  # rede fora, token/chat inválidos, timeout
            # não inclui a URL (que carrega o token) na mensagem de erro
            erro = e.__class__.__name__ + (f": {e.reason}" if hasattr(e, "reason") else "")
    return False, erro


def enviar(texto: str, callback=None):
    """Envia em segundo plano para não travar o callback MQTT. callback(ok, erro) opcional."""
    def _run():
        ok, erro = enviar_sincrono(texto)
        if callback:
            callback(ok, erro)
    threading.Thread(target=_run, daemon=True).start()


def mensagem_queda(cinto, quando: datetime, anchor, rssi, prob, amax, tilt, quadrante=None) -> str:
    local = f"mais perto da Anchor {anchor}" if anchor is not None else "localização indisponível"
    if rssi is not None:
        local += f" ({rssi:.0f} dBm)"
    if quadrante:
        local = f"quadrante {quadrante}, " + local
    return ("🚨 QUEDA DETECTADA\n"
            f"Cinto: {cinto}\n"
            f"Hora: {quando:%d/%m/%Y %H:%M:%S}\n"
            f"Local: {local}\n"
            f"Confiança: {prob:.1%}  |  pico {amax:.1f} g, inclinação {tilt:.0f}°")


def mensagem_teste() -> str:
    return f"✅ Teste do monitor OQPNB — {datetime.now():%d/%m/%Y %H:%M:%S}"
