"""Cliente do sistema EMR: o braço avisa cada caixa separada (e faltas, conclusão, erro) e recebe de volta o estado
da OS ("running", "paused", "cancelled", "completed"), que diz se ele continua, estaciona ou encerra."""
import json
import time
import urllib.error
import urllib.request

TIMEOUT = 5.0


class SistemaIndisponivel(RuntimeError):
    """o EMR não respondeu (rede, 5xx) ou recusou o token"""


class Sistema:
    def __init__(self, callback, token, tentativas=3, espera=1.0):
        self.base = callback.rstrip("/")
        self.token = token
        self.tentativas = tentativas
        self.espera = espera

    def evento(self, tipo, separadas, **extra):
        return self._chama("POST", "/evento", {"tipo": tipo, "separadas": separadas, **extra})

    def estado(self):
        return self._chama("GET", "/estado", None)

    def _chama(self, metodo, sufixo, corpo):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        ultimo = None
        for i in range(self.tentativas):
            req = urllib.request.Request(self.base + sufixo, data=dados, method=metodo, headers={
                "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    return json.loads(r.read())["estado"]
            except urllib.error.HTTPError as ex:
                if ex.code == 404:
                    return "cancelled"      # a OS não existe mais no sistema: encerra
                if ex.code in (401, 403, 503):
                    raise SistemaIndisponivel("EMR recusou (%d): confira EMR_ROBO_TOKEN" % ex.code) from ex
                ultimo = ex
            except (urllib.error.URLError, OSError, ValueError, KeyError) as ex:
                ultimo = ex
            if i + 1 < self.tentativas:
                time.sleep(self.espera)
        raise SistemaIndisponivel("EMR não respondeu: %s" % ultimo)
