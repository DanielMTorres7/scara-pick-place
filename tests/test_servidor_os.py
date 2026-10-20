import json
import threading
import urllib.error
import urllib.request

import pytest

from servidor_os import callback_de, cria_servidor, valida_pedido

PEDIDO = {"os": "OS-1", "cliente": "Fulano", "quantidade": 3, "separadas": 0,
          "itens": [{"remedio_id": "1", "remedio": "MICPURE 10MG", "nome": "micpure", "quantidade": 2},
                    {"remedio_id": "2", "remedio": "ARPADOL", "nome": "arpadol", "quantidade": 1}],
          "callback": "http://127.0.0.1:8765/api/robo/OS-1"}


class JobFalso:
    def __init__(self, pedido):
        self.pedido = pedido
        self.libera = threading.Event()
        self.rodou = threading.Event()

    @property
    def os(self):
        return self.pedido["os"]

    def rodar(self):
        self.rodou.set()
        self.libera.wait(5)


@pytest.fixture
def srv():
    jobs = []

    def novo_job(pedido):
        jobs.append(JobFalso(pedido))
        return jobs[-1]

    s = cria_servidor(0, "tok", novo_job)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % s.server_address[1], jobs
    for j in jobs:
        j.libera.set()
    s.shutdown()


def _req(url, corpo=None, token="tok", metodo="POST"):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=dados, method=metodo, headers=h), timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_sem_token_401(srv):
    url, jobs = srv
    assert _req(url + "/os", PEDIDO, token=None)[0] == 401
    assert _req(url + "/os", PEDIDO, token="errado")[0] == 401
    assert jobs == []


def test_payload_invalido_400(srv):
    url, _ = srv
    assert _req(url + "/os", {**PEDIDO, "itens": [{"nome": "x", "quantidade": 0}]})[0] == 400


def test_aceita_202_e_roda_job(srv):
    url, jobs = srv
    st, corpo = _req(url + "/os", PEDIDO)
    assert st == 202 and corpo["aceito"] is True
    assert jobs[0].rodou.wait(2)
    assert jobs[0].pedido["itens"] == [{"nome": "micpure", "quantidade": 2}, {"nome": "arpadol", "quantidade": 1}]


def test_outra_os_ocupado_409(srv):
    url, jobs = srv
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    assert _req(url + "/os", {**PEDIDO, "os": "OS-2"})[0] == 409


def test_mesma_os_reenviada_nao_duplica(srv):
    url, jobs = srv
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    st, corpo = _req(url + "/os", {**PEDIDO, "separadas": 2})
    assert st == 202 and corpo["retomada"] is True
    assert len(jobs) == 1


def test_job_terminado_aceita_nova(srv):
    url, jobs = srv
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    jobs[0].libera.set()
    for _ in range(50):
        if not _req(url + "/saude", metodo="GET")[1]["ocupado"]:
            break
        threading.Event().wait(0.02)
    assert _req(url + "/os", {**PEDIDO, "os": "OS-2"})[0] == 202


def test_saude(srv):
    url, jobs = srv
    assert _req(url + "/saude", metodo="GET") == (200, {"ocupado": False, "os": None})
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    assert _req(url + "/saude", metodo="GET") == (200, {"ocupado": True, "os": "OS-1"})


@pytest.mark.parametrize("ruim", [
    {"os": ""}, {"quantidade": -1}, {"separadas": "2"},
    {"itens": "micpure"}, {"itens": [{"nome": 3, "quantidade": 1}]}, {"itens": [{"nome": "x", "quantidade": True}]},
])
def test_valida_pedido_recusa(ruim):
    with pytest.raises(ValueError):
        valida_pedido({**PEDIDO, **ruim})


def test_valida_pedido_recusa_nao_dict():
    with pytest.raises(ValueError):
        valida_pedido([1])


def test_callback_vem_da_config_e_ignora_o_pedido():
    assert "callback" not in valida_pedido({**PEDIDO, "callback": "http://atacante/x"})
    assert callback_de("http://emr:8765/", "OS 1/2") == "http://emr:8765/api/robo/OS%201%2F2"
