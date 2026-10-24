import json
import threading
import urllib.error
import urllib.request

import pytest

from conexao import Conexao
from servidor_os import callback_de, cria_servidor, eh_local, valida_pedido

TOKEN = "t" * 20

PEDIDO = {"os": "OS-1", "cliente": "Fulano", "quantidade": 3, "separadas": 0,
          "itens": [{"remedio_id": "1", "remedio": "MICPURE 10MG", "nome": "micpure", "quantidade": 2},
                    {"remedio_id": "2", "remedio": "ARPADOL", "nome": "arpadol", "quantidade": 1}],
          "callback": "http://127.0.0.1:8765/api/robo/OS-1"}


class JobFalso:
    def __init__(self, pedido):
        self.pedido = pedido
        self.libera = threading.Event()
        self.rodou = threading.Event()
        self.encerrando = False

    @property
    def os(self):
        return self.pedido["os"]

    def rodar(self):
        self.rodou.set()
        self.libera.wait(5)


@pytest.fixture
def conexao(tmp_path):
    c = Conexao(tmp_path / "conexao.json")
    c.salva(TOKEN, "http://127.0.0.1:8765")
    return c


@pytest.fixture
def srv(conexao):
    jobs = []

    def novo_job(pedido):
        jobs.append(JobFalso(pedido))
        return jobs[-1]

    s = cria_servidor(0, conexao, novo_job)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % s.server_address[1], jobs
    for j in jobs:
        j.libera.set()
    s.shutdown()


def _req(url, corpo=None, token=TOKEN, metodo="POST"):
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
    # spec 03-calibracao: /saude ganhou tarefa e calibracao; os campos antigos seguem iguais
    assert _req(url + "/saude", metodo="GET") == (200, {"ocupado": False, "os": None, "conectado": True,
                                                        "tarefa": None, "calibracao": None})
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    assert _req(url + "/saude", metodo="GET") == (200, {"ocupado": True, "os": "OS-1", "conectado": True,
                                                        "tarefa": "os", "calibracao": None})


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


def test_valida_pedido_soma_mesmo_nome():
    """I4: MICPURE 10MG e MICPURE 20MG viram um item só para o braço (a visão não distingue a dosagem)"""
    p = valida_pedido({**PEDIDO, "quantidade": 3, "itens": [
        {"nome": "micpure", "quantidade": 2}, {"nome": "arpadol", "quantidade": 1}, {"nome": "Micpure", "quantidade": 1}]})
    assert p["itens"] == [{"nome": "micpure", "quantidade": 3}, {"nome": "arpadol", "quantidade": 1}]


def test_job_encerrando_libera_para_nova_os(srv):
    """I6: job saindo (cancelado) + OS nova: espera ele terminar em vez de 409"""
    url, jobs = srv
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    jobs[0].encerrando = True
    threading.Timer(0.3, jobs[0].libera.set).start()
    assert _req(url + "/os", {**PEDIDO, "os": "OS-2"})[0] == 202
    assert len(jobs) == 2


def test_mesma_os_com_job_encerrando_cria_job_novo(srv):
    url, jobs = srv
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    jobs[0].encerrando = True
    threading.Timer(0.3, jobs[0].libera.set).start()
    st, corpo = _req(url + "/os", PEDIDO)
    assert st == 202 and corpo["retomada"] is False and len(jobs) == 2


@pytest.mark.parametrize("n", ["abc", "-1"])
def test_content_length_ruim_400(srv, n):
    url, _ = srv
    import http.client
    host, port = url.replace("http://", "").split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=3)
    c.putrequest("POST", "/os")
    c.putheader("Authorization", "Bearer " + TOKEN)
    c.putheader("Content-Length", n)
    c.endheaders()
    assert c.getresponse().status == 400


def test_saude_nao_espera_job_encerrando(srv):
    """/saude (sem token) nunca bloqueia, nem com um job encerrando"""
    import time
    url, jobs = srv
    _req(url + "/os", PEDIDO)
    jobs[0].rodou.wait(2)
    jobs[0].encerrando = True
    t = time.monotonic()
    assert _req(url + "/saude", metodo="GET")[1]["ocupado"] is True
    assert time.monotonic() - t < 1.0


def test_conectar_grava_e_vale_para_a_proxima_os(srv, conexao, tmp_path):
    url, jobs = srv
    novo = "n" * 24
    st, corpo = _req(url + "/conectar", {"token": novo, "emr_url": "http://127.0.0.1:9999/"}, token=None)
    assert (st, corpo) == (200, {"conectado": True})
    assert Conexao(conexao.caminho).token == novo and conexao.emr_url == "http://127.0.0.1:9999"
    assert _req(url + "/os", PEDIDO)[0] == 401              # token antigo não vale mais
    assert _req(url + "/os", PEDIDO, token=novo)[0] == 202


def test_conectar_invalido_400(srv):
    url, _ = srv
    assert _req(url + "/conectar", {"token": "curto", "emr_url": "http://x"}, token=None)[0] == 400


def test_sem_conexao_503(tmp_path):
    s = cria_servidor(0, Conexao(tmp_path / "nada.json"), lambda p: None)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % s.server_address[1]
    try:
        assert _req(url + "/os", PEDIDO)[0] == 503
        assert _req(url + "/saude", metodo="GET")[1]["conectado"] is False
    finally:
        s.shutdown()


@pytest.mark.parametrize("ip,local", [("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
                                      ("192.168.0.5", False), ("10.0.0.1", False)])
def test_eh_local(ip, local):
    assert eh_local(ip) is local


def _conectar_cru(url, headers, corpo=b'{"token": "nnnnnnnnnnnnnnnnnnnnnnnn", "emr_url": "http://127.0.0.1:8765"}'):
    import http.client
    host, port = url.replace("http://", "").split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=3)
    c.request("POST", "/conectar", body=corpo, headers=headers)
    return c.getresponse().status


def test_conectar_recusa_pedido_de_navegador(srv, conexao):
    """página maliciosa no navegador local: tem Origin, ou não manda JSON, ou chega por DNS rebinding"""
    url, _ = srv
    porta = url.rsplit(":", 1)[1]
    assert _conectar_cru(url, {"Content-Type": "application/json", "Origin": "http://evil.com"}) == 403
    assert _conectar_cru(url, {"Content-Type": "text/plain"}) == 415
    assert _conectar_cru(url, {"Content-Type": "application/json", "Host": "evil.com:" + porta}) == 403
    assert conexao.token == TOKEN
    assert _conectar_cru(url, {"Content-Type": "application/json"}) == 200


def test_sigterm_e_sigint_encerram_limpo(monkeypatch):
    """23/10: subido em segundo plano o processo herda o SIGINT ignorado e o SIGTERM o matava sem o finally:
    o braço ficava energizado. Os dois viram KeyboardInterrupt (o main fecha o braço e corta a energia)."""
    import signal

    import pytest

    import servidor_os
    instalados = {}
    monkeypatch.setattr(servidor_os.signal, "signal", lambda s, h: instalados.__setitem__(s, h))
    servidor_os.instala_sinais()
    for s in (signal.SIGTERM, signal.SIGINT):
        with pytest.raises(KeyboardInterrupt):
            instalados[s](s, None)


class CalibFalsa:
    os = None

    def __init__(self, tipo):
        if tipo not in ("soltar", "braco", "cameras"):
            raise ValueError("tipo")
        self.tarefa, self.encerrando, self.resultado = tipo, False, None
        self.libera = threading.Event()

    def rodar(self):
        self.libera.wait(5)
        self.resultado = {"tipo": self.tarefa, "ok": True, "msg": "braço referenciado", "fim": "2026-10-23T17:00:00"}
        self.encerrando = True


@pytest.fixture
def srv_calib(conexao):
    jobs, calibs = [], []

    def novo_job(pedido):
        jobs.append(JobFalso(pedido))
        return jobs[-1]

    def nova_calibracao(tipo):
        calibs.append(CalibFalsa(tipo))
        return calibs[-1]

    s = cria_servidor(0, conexao, novo_job, nova_calibracao)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % s.server_address[1], jobs, calibs
    for j in jobs + calibs:
        j.libera.set()
    s.shutdown()


def _saude(url):
    with urllib.request.urlopen(url + "/saude", timeout=5) as r:
        return json.loads(r.read())


def test_calibrar_roda_e_aparece_no_saude(srv_calib):
    """botões do sistema (spec 03-calibracao): POST /calibrar {tipo} com o token; /saude mostra a tarefa e o resultado"""
    import time
    url, _, calibs = srv_calib
    assert _req(url + "/calibrar", {"tipo": "braco"}) == (202, {"aceito": True, "tipo": "braco"})
    s = _saude(url)
    assert s["ocupado"] and s["tarefa"] == "braco" and s["os"] is None and s["calibracao"] is None
    calibs[0].libera.set()
    for _ in range(50):
        s = _saude(url)
        if not s["ocupado"]:
            break
        time.sleep(0.02)
    assert s["tarefa"] is None and s["calibracao"]["ok"] and s["calibracao"]["msg"] == "braço referenciado"


def test_calibrar_exige_token_e_tipo_valido(srv_calib):
    url, _, calibs = srv_calib
    assert _req(url + "/calibrar", {"tipo": "braco"}, token=None)[0] == 401
    assert _req(url + "/calibrar", {"tipo": "tudo"})[0] == 400
    assert _req(url + "/calibrar", ["braco"])[0] == 400
    assert calibs == []


def test_calibrar_com_os_rodando_409_e_os_com_calibracao_409(srv_calib):
    url, jobs, calibs = srv_calib
    assert _req(url + "/os", PEDIDO)[0] == 202
    jobs[0].rodou.wait(2)
    assert _req(url + "/calibrar", {"tipo": "braco"})[0] == 409
    assert _saude(url)["tarefa"] == "os"
    jobs[0].libera.set()
    import time
    for _ in range(50):
        if not _saude(url)["ocupado"]:
            break
        time.sleep(0.02)
    assert _req(url + "/calibrar", {"tipo": "cameras"})[0] == 202
    assert _req(url + "/os", {**PEDIDO, "os": "OS-2"})[0] == 409


def test_pedido_todas_ignora_lista_e_quantidade():
    """modo "separar tudo" do sistema: {"todas": true} pega o que detectar; a lista (se vier) não vale e não lê nomes"""
    p = valida_pedido({**PEDIDO, "todas": True})
    assert p["todas"] is True and p["itens"] == [] and p["quantidade"] == 0
    assert valida_pedido(PEDIDO)["todas"] is False
    with pytest.raises(ValueError):
        valida_pedido({**PEDIDO, "todas": "sim"})
