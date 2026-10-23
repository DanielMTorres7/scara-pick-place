"""Scara liga a energia pelos relés ao abrir e corta ao fechar (no boot dos relés tudo fica desligado)."""
import pytest

import scara


class Registro:
    def __init__(self, log, nome, falha=None):
        self.log, self.nome, self.falha = log, nome, falha
        self.eventos = []

    def energizar(self):
        self.log.append("energizar")
        if self.falha:
            raise self.falha

    def desenergizar(self):
        self.log.append("desenergizar")

    def ligar(self, nome, v):
        self.log.append(("ligar", nome, v))

    def fechar(self):
        self.log.append(("fechar", self.nome))

    def reiniciar(self):
        self.log.append(("reiniciar", self.nome))

    def cmd(self, c, **kw):
        self.log.append(("cmd", self.nome, c))
        return {}


def _abre(monkeypatch, falha=None):
    log = []
    monkeypatch.setattr(scara, "acha_portas", lambda: {"braco": "A", "z": "B"})
    monkeypatch.setattr(scara, "Reles", lambda: Registro(log, "reles", falha))
    monkeypatch.setattr(scara, "Placa", lambda p: Registro(log, p))
    monkeypatch.setattr(scara.Scara, "referenciar_z", lambda self, **kw: scara.Z_CHAVE)   # coberto em test_fins_de_curso
    return log


def test_abrir_energiza_antes_de_falar_com_as_placas(monkeypatch):
    log = _abre(monkeypatch)
    scara.Scara()
    assert log[0] == "energizar"


def test_fechar_corta_energia_e_fecha_reles_por_ultimo(monkeypatch):
    log = _abre(monkeypatch)
    r = scara.Scara()
    log.clear()
    r.fechar()
    assert log[-2:] == ["desenergizar", ("fechar", "reles")]
    assert ("fechar", "A") in log and ("fechar", "B") in log


def test_sem_24v_desliga_tudo_e_levanta(monkeypatch):
    from reles import SemEnergia
    log = _abre(monkeypatch, falha=SemEnergia("sem 24 V"))
    with pytest.raises(SemEnergia):
        scara.Scara()
    assert log[-2:] == ["desenergizar", ("fechar", "reles")]


def test_bomba_vai_pelo_rele(monkeypatch):
    log = _abre(monkeypatch)
    r = scara.Scara()
    r.bomba(1)
    assert log[-1] == ("ligar", "bomba", 1)


def test_abrir_espera_os_tmc_e_descarta_os_eventos_da_partida(monkeypatch):
    """o religamento dos relés reinicia os TMC; esse aviso chega atrasado e não pode parar o primeiro ciclo"""
    class PlacaLiga:
        def __init__(self, p):
            self.eventos, self.n = [], 0

        def reiniciar(self):
            pass

        def cmd(self, c, **kw):
            if c == "st":
                self.n += 1
                if self.n == 2:
                    self.eventos.append("TMC reiniciou (VM caiu?): configuração regravada")
                return {"tmci": {"ok": self.n >= 2}}
            return {}

    monkeypatch.setattr(scara, "acha_portas", lambda: {"braco": "A", "z": "B"})
    monkeypatch.setattr(scara, "Reles", lambda: Registro([], "reles"))
    monkeypatch.setattr(scara, "Placa", PlacaLiga)
    monkeypatch.setattr(scara.Scara, "referenciar_z", lambda self, **kw: scara.Z_CHAVE)
    monkeypatch.setattr(scara.time, "sleep", lambda s: None)
    r = scara.Scara()
    assert all(p.n >= 2 and p.eventos == [] for p in r.placas.values())
