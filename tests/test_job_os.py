import pytest

from job_os import CaixaInalcancavel, JobOS
from progresso import Progresso
from sistema import SistemaIndisponivel

ITENS = [{"nome": "micpure", "quantidade": 2}, {"nome": "arpadol", "quantidade": 1}]


def _cx(nome, y):
    return {"nome": nome, "centro": (100.0, float(y))}


class ExecutorFalso:
    def __init__(self, fotos, falhas=None):
        self.fotos = list(fotos)        # uma lista de caixas por chamada de preparar()
        self.falhas = falhas or {}      # y da caixa -> exceção levantada em pegar
        self.chamadas = []

    def preparar(self):
        self.chamadas.append("preparar")
        return self.fotos.pop(0) if len(self.fotos) > 1 else self.fotos[0]

    def pegar(self, caixa, i):
        self.chamadas.append(("pegar", caixa["nome"]))
        e = self.falhas.get(caixa["centro"][1])
        if e:
            raise e

    def estacionar(self):
        self.chamadas.append("estacionar")

    def parar(self):
        self.chamadas.append("parar")

    def fechar(self):
        self.chamadas.append("fechar")


class SistemaFalso:
    """respostas: estado (ou exceção) devolvido por cada chamada, na ordem; acabou a fila -> running"""

    def __init__(self, eventos=(), estados=()):
        self.r_eventos = list(eventos)
        self.r_estados = list(estados)
        self.eventos = []
        self.consultas = 0

    @staticmethod
    def _proxima(fila):
        r = fila.pop(0) if fila else "running"
        if isinstance(r, Exception):
            raise r
        return r

    def evento(self, tipo, separadas, **extra):
        self.eventos.append((tipo, separadas, extra))
        return self._proxima(self.r_eventos)

    def estado(self):
        self.consultas += 1
        return self._proxima(self.r_estados)


def _job(tmp_path, ex, sis, itens=ITENS, quantidade=3, separadas=0):
    pedido = {"os": "OS-1", "itens": itens, "quantidade": quantidade, "separadas": separadas}
    return JobOS(pedido, lambda: ex, sis, Progresso(tmp_path / "p.json"), espera_pausa=0, dormir=lambda s: None)


def _tipos(sis):
    return [(t, n) for t, n, _ in sis.eventos]


def test_pega_tudo_e_conclui(tmp_path):
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Arpadol", 2), _cx("Micpure", 3)]])
    sis = SistemaFalso()
    _job(tmp_path, ex, sis).rodar()
    assert _tipos(sis) == [("unit", 1), ("unit", 2), ("unit", 3), ("concluida", 3)]
    assert [c for c in ex.chamadas if c[0] == "pegar"] == [("pegar", "Micpure"), ("pegar", "Micpure"), ("pegar", "Arpadol")]
    assert ex.chamadas[-1] == "fechar"


def test_faltando_pausa_e_retoma(tmp_path):
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2)], [_cx("Arpadol", 5)]])
    sis = SistemaFalso(eventos=["running", "running", "paused"], estados=["running", "paused", "running"])
    _job(tmp_path, ex, sis).rodar()
    assert sis.eventos[2] == ("faltando", 2, {"faltando": [{"nome": "arpadol", "faltam": 1}]})
    assert ("unit", 3) in _tipos(sis) and _tipos(sis)[-1] == ("concluida", 3)
    assert ex.chamadas.count("preparar") == 2


def test_pausa_no_meio_estaciona(tmp_path):
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2), _cx("Arpadol", 3)], [_cx("Micpure", 2), _cx("Arpadol", 3)]])
    sis = SistemaFalso(eventos=["paused"], estados=["running", "paused", "running"])
    _job(tmp_path, ex, sis).rodar()
    i = ex.chamadas.index("estacionar")
    assert ex.chamadas[:i] == ["preparar", ("pegar", "Micpure")]
    assert ex.chamadas.count("preparar") == 2
    assert _tipos(sis)[-1] == ("concluida", 3)


def test_cancelado_encerra(tmp_path):
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2), _cx("Arpadol", 3)]])
    sis = SistemaFalso(eventos=["cancelled"])
    _job(tmp_path, ex, sis).rodar()
    assert _tipos(sis) == [("unit", 1)]
    assert ex.chamadas == ["preparar", ("pegar", "Micpure"), "estacionar", "fechar"]


def test_erro_manda_erro_e_fecha(tmp_path):
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2)]], falhas={2.0: RuntimeError("placa z: FIM")})
    sis = SistemaFalso()
    _job(tmp_path, ex, sis).rodar()
    assert sis.eventos[-1] == ("erro", 1, {"mensagem": "placa z: FIM"})
    assert ex.chamadas[-2:] == ["parar", "fechar"]


def test_caixa_inalcancavel_vira_faltando(tmp_path):
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2), _cx("Arpadol", 3)]],
                       falhas={3.0: CaixaInalcancavel("fora do alcance")})
    sis = SistemaFalso(eventos=["running", "running", "cancelled"])
    _job(tmp_path, ex, sis).rodar()
    assert sis.eventos[-1] == ("faltando", 2, {"faltando": [{"nome": "arpadol", "faltam": 1}]})
    assert "parar" not in ex.chamadas


def test_sistema_cai_e_volta(tmp_path):
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2), _cx("Arpadol", 3)], [_cx("Micpure", 2), _cx("Arpadol", 3)]])
    sis = SistemaFalso(eventos=[SistemaIndisponivel("fora")],
                       estados=["running", SistemaIndisponivel("fora"), "running"])
    _job(tmp_path, ex, sis).rodar()
    assert _tipos(sis)[:2] == [("unit", 1), ("unit", 1)]     # reenvia o total antes de pegar a próxima
    assert ex.chamadas.index("estacionar") < ex.chamadas.index("preparar", 1)
    assert _tipos(sis)[-1] == ("concluida", 3)


def test_retoma_do_progresso_salvo(tmp_path):
    Progresso(tmp_path / "p.json").salva("OS-1", {"micpure": 1})
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2), _cx("Arpadol", 3)]])
    sis = SistemaFalso()
    _job(tmp_path, ex, sis, separadas=1).rodar()
    assert [c for c in ex.chamadas if c[0] == "pegar"] == [("pegar", "Micpure"), ("pegar", "Arpadol")]
    assert _tipos(sis)[-1] == ("concluida", 3)
    assert Progresso(tmp_path / "p.json").carrega("OS-1") == {"micpure": 2, "arpadol": 1}


def test_os_sem_itens_pega_qualquer(tmp_path):
    ex = ExecutorFalso([[_cx("", 1), _cx("Arpadol", 2), _cx("Micpure", 3)]])
    sis = SistemaFalso()
    _job(tmp_path, ex, sis, itens=[], quantidade=2).rodar()
    assert _tipos(sis) == [("unit", 1), ("unit", 2), ("concluida", 2)]


def test_os(tmp_path):
    assert _job(tmp_path, ExecutorFalso([[]]), SistemaFalso()).os == "OS-1"


@pytest.mark.parametrize("final", ["cancelled", "completed"])
def test_ultima_unit_encerra_sem_concluida(tmp_path, final):
    ex = ExecutorFalso([[_cx("", 1)]])
    sis = SistemaFalso(eventos=[final])
    _job(tmp_path, ex, sis, itens=[], quantidade=1).rodar()
    assert _tipos(sis) == [("unit", 1)]


def test_falha_ao_abrir_hardware_manda_erro(tmp_path):
    def quebra():
        raise RuntimeError("placa braco não encontrada")
    sis = SistemaFalso()
    pedido = {"os": "OS-1", "itens": ITENS, "quantidade": 3, "separadas": 0}
    JobOS(pedido, quebra, sis, Progresso(tmp_path / "p.json"), espera_pausa=0, dormir=lambda s: None).rodar()
    assert sis.eventos == [("erro", 0, {"mensagem": "placa braco não encontrada"})]


def test_reenvio_falha_de_novo_nao_pega(tmp_path):
    """I1: voltou a rodar, mas o reenvio do total falha: espera de novo, não pega caixa sem registro"""
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2), _cx("Arpadol", 3)], [_cx("Micpure", 2), _cx("Arpadol", 3)]])
    sis = SistemaFalso(eventos=[SistemaIndisponivel("fora"), SistemaIndisponivel("fora")],
                       estados=["running", "running"])
    _job(tmp_path, ex, sis).rodar()
    pegas = [i for i, c in enumerate(ex.chamadas) if c[0] == "pegar"]
    assert sis.consultas >= 2 and ex.chamadas.count("preparar") == 2
    assert _tipos(sis)[:3] == [("unit", 1), ("unit", 1), ("unit", 1)]
    assert len(pegas) == 3


def test_reenvio_devolve_paused_espera(tmp_path):
    """I1: voltou a rodar, mas o reenvio diz que pausou de novo: não fotografa"""
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2), _cx("Arpadol", 3)]])
    sis = SistemaFalso(eventos=["paused", "paused", "cancelled"], estados=["running", "running"])
    _job(tmp_path, ex, sis).rodar()
    assert ex.chamadas.count("preparar") == 1


def test_cancelado_durante_a_foto_nao_pega(tmp_path):
    """I2: OS cancelada enquanto o braço fotografava/lia nomes: nenhuma caixa"""
    ex = ExecutorFalso([[_cx("Micpure", 1)]])
    sis = SistemaFalso(estados=["cancelled"])
    _job(tmp_path, ex, sis).rodar()
    assert not [c for c in ex.chamadas if c[0] == "pegar"] and sis.eventos == []


def test_inalcancavel_usa_outra_caixa_do_mesmo_remedio(tmp_path):
    """I3: a 1ª micpure está fora do alcance, a 2ª não: conclui"""
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2)]], falhas={1.0: CaixaInalcancavel("longe")})
    sis = SistemaFalso()
    _job(tmp_path, ex, sis, itens=[{"nome": "micpure", "quantidade": 1}], quantidade=1).rodar()
    assert _tipos(sis) == [("unit", 1), ("concluida", 1)]


def test_encerrando_marcado_ao_cancelar(tmp_path):
    """I6: o servidor precisa saber que o job está saindo"""
    ex = ExecutorFalso([[_cx("Micpure", 1), _cx("Micpure", 2)]])
    sis = SistemaFalso(eventos=["cancelled"])
    job = _job(tmp_path, ex, sis)
    assert job.encerrando is False
    job.rodar()
    assert job.encerrando is True
