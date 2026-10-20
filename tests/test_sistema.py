import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sistema import Sistema, SistemaIndisponivel


@pytest.fixture
def servidor():
    """servidor falso do EMR: registra as requisições e responde com (status, corpo) da fila"""
    reqs, respostas = [], []

    class H(BaseHTTPRequestHandler):
        def _responde(self, corpo_req):
            reqs.append({"metodo": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                         "corpo": corpo_req})
            status, corpo = respostas.pop(0) if respostas else (200, {"estado": "running"})
            b = json.dumps(corpo).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self._responde(json.loads(self.rfile.read(n)))

        def do_GET(self):
            self._responde(None)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/api/robo/OS-1" % srv.server_address[1], reqs, respostas
    srv.shutdown()


def test_evento_envia_token_e_corpo(servidor):
    url, reqs, respostas = servidor
    respostas.append((200, {"estado": "paused", "separadas": 2}))
    assert Sistema(url, "tok").evento("unit", 2) == "paused"
    assert reqs[0] == {"metodo": "POST", "path": "/api/robo/OS-1/evento", "auth": "Bearer tok",
                       "corpo": {"tipo": "unit", "separadas": 2}}


def test_evento_com_extra(servidor):
    url, reqs, _ = servidor
    Sistema(url, "tok").evento("faltando", 1, faltando=[{"nome": "arpadol", "faltam": 1}])
    assert reqs[0]["corpo"]["faltando"] == [{"nome": "arpadol", "faltam": 1}]


def test_estado(servidor):
    url, reqs, respostas = servidor
    respostas.append((200, {"estado": "cancelled"}))
    assert Sistema(url, "tok").estado() == "cancelled"
    assert reqs[0]["path"] == "/api/robo/OS-1/estado"


def test_404_vira_cancelled(servidor):
    url, _, respostas = servidor
    respostas.append((404, {"detail": "x"}))
    assert Sistema(url, "tok").estado() == "cancelled"


def test_5xx_repete_e_levanta(servidor):
    url, reqs, respostas = servidor
    respostas.extend([(500, {}), (500, {})])
    with pytest.raises(SistemaIndisponivel):
        Sistema(url, "tok", tentativas=2, espera=0).estado()
    assert len(reqs) == 2


def test_401_levanta_sem_repetir(servidor):
    url, reqs, respostas = servidor
    respostas.append((401, {}))
    with pytest.raises(SistemaIndisponivel):
        Sistema(url, "tok", tentativas=3, espera=0).estado()
    assert len(reqs) == 1


def test_rede_fora_levanta():
    with pytest.raises(SistemaIndisponivel):
        Sistema("http://127.0.0.1:1/api/robo/OS-1", "tok", tentativas=2, espera=0).estado()
