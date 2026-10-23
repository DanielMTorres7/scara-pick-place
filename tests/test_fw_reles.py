"""Firmware do módulo de 8 relés (roda no MicroPython): carregado aqui com um `machine` falso."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parent.parent / "firmware_reles"


class PinoFalso:
    OUT, IN = "out", "in"
    log = []
    niveis = {}

    def __init__(self, n, modo=None, value=None):
        self.n = n
        if value is not None:
            self.value(value)

    def value(self, v=None):
        if v is None:
            return PinoFalso.niveis.get(self.n, 0)
        PinoFalso.niveis[self.n] = v
        PinoFalso.log.append((self.n, v))
        return None


class AdcFalso:
    leitura = 0

    def __init__(self, pino):
        self.pino = pino

    def read_u16(self):
        return AdcFalso.leitura


def _carrega(nome, vs=1):
    PinoFalso.log, PinoFalso.niveis = [], {0: vs}
    maquina = types.ModuleType("machine")
    maquina.Pin = PinoFalso
    maquina.ADC = AdcFalso
    sys.modules["machine"] = maquina
    tempo = types.ModuleType("time")
    tempo.sleep_ms = lambda ms: PinoFalso.log.append(("espera", ms))
    tempo.ticks_ms = lambda: 0
    tempo.ticks_diff = lambda a, b: a - b
    sys.modules["utime"] = tempo
    sys.path.insert(0, str(FW))
    spec = importlib.util.spec_from_file_location(nome, FW / ("%s.py" % nome))
    m = importlib.util.module_from_spec(spec)
    sys.modules[nome] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(autouse=True)
def _limpa():
    yield
    for n in ("machine", "utime", "fw_reles", "main"):
        sys.modules.pop(n, None)
    while str(FW) in sys.path:
        sys.path.remove(str(FW))


def test_mapa_dos_reles():
    fw = _carrega("fw_reles")
    assert fw.PINOS == {"potencia": 4, "bomba": 5, "rele6": 6, "dm556_z": 7,
                        "placa2": 8, "rele9": 9, "placa1": 10, "dm556": 11}


def test_import_deixa_todos_os_reles_desligados_em_nivel_alto():
    fw = _carrega("fw_reles")
    assert all(PinoFalso.niveis[p] == 1 for p in fw.PINOS.values())


def test_main_desliga_tudo_antes_de_qualquer_outra_coisa():
    _carrega("main")
    assert {n for n, _ in PinoFalso.log[:8]} == set(range(4, 12))
    assert all(v == 1 for _, v in PinoFalso.log[:8])


def test_ligar_e_ativo_baixo():
    fw = _carrega("fw_reles")
    fw.ligar("bomba", 1)
    assert PinoFalso.niveis[5] == 0
    fw.ligar("bomba", 0)
    assert PinoFalso.niveis[5] == 1


def test_estado_logico():
    fw = _carrega("fw_reles")
    fw.ligar("dm556", 1)
    e = fw.estado()
    assert e["dm556"] == 1 and e["bomba"] == 0 and e["vs"] == 1


def test_nome_desconhecido_levanta():
    fw = _carrega("fw_reles")
    with pytest.raises(KeyError):
        fw.ligar("bomb", 1)


def test_energizar_liga_ramos_antes_da_potencia_e_devolve_24v():
    fw = _carrega("fw_reles")
    PinoFalso.log = []
    assert fw.energizar() == 1
    ligados = [n for n, v in PinoFalso.log if n != "espera" and v == 0]
    assert ligados[-1] == 4 and set(ligados[:-1]) == {7, 8, 10, 11}


def test_energizar_sem_24v_devolve_0():
    fw = _carrega("fw_reles", vs=0)
    assert fw.energizar(timeout_ms=0) == 0


def test_desenergizar_corta_potencia_primeiro_e_desliga_tudo():
    fw = _carrega("fw_reles")
    fw.energizar()
    fw.ligar("bomba", 1)
    PinoFalso.log = []
    fw.desenergizar()
    assert PinoFalso.log[0] == (4, 1)
    assert all(PinoFalso.niveis[p] == 1 for p in fw.PINOS.values())


def test_energizar_liga_um_rele_de_cada_vez():
    """as bobinas puxam ~80 mA cada do 5 V do USB: todas juntas derrubavam a placa (reset em 23/10)"""
    fw = _carrega("fw_reles")
    PinoFalso.log = []
    fw.energizar()
    ligou = [i for i, (n, v) in enumerate(PinoFalso.log) if n != "espera" and v == 0]
    for a, b in zip(ligou, ligou[1:]):
        pausas = [v for n, v in PinoFalso.log[a:b] if n == "espera"]
        assert sum(pausas) >= fw.PAUSA_RELE_MS


def test_tensao_em_volts_pelo_gp26():
    fw = _carrega("fw_reles")
    AdcFalso.leitura = 65535 // 2                        # meia escala: 1,65 V no pino
    assert abs(fw.tensao() - 1.65 * fw.FATOR_DIVISOR) < 0.05
    assert "v" in fw.estado()


def test_estado_mostra_a_tensao_com_uma_casa():
    fw = _carrega("fw_reles")
    AdcFalso.leitura = 0
    assert fw.estado()["v"] == 0.0
