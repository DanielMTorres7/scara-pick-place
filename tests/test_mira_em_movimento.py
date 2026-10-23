"""Mira sem parar: a foto sai quando as juntas chegam e o Z ainda desce; a correção vai enquanto o Z termina."""
import pytest

import pick_place
from pick_place import PickPlace, pode_corrigir


def test_pode_corrigir_so_com_a_ventosa_bem_acima_da_caixa():
    z_pega = -87.0
    assert pode_corrigir(0.0, z_pega)
    assert not pode_corrigir(z_pega + 5, z_pega)        # quase encostando: corrigir arrastaria a caixa
    assert not pode_corrigir(z_pega, z_pega)


class ScaraFalso:
    """Z desce sozinho (outra placa) enquanto as juntas andam"""

    def __init__(self, log):
        self.log, self.z, self.fator_vel = log, 51.0, 1.0
        self.j = (0.0, 0.0)

    def posicoes(self):
        return {"j1": self.j[0], "j2": self.j[1], "z": self.z}

    def posicao(self, eixo):
        return self.z

    def ir(self, eixo, alvo, esperar=True, **kw):
        self.log.append(("z", alvo))
        self.alvo_z = alvo

    def ir_juntas(self, *alvo, **kw):
        self.log.append(("juntas", alvo))
        self.j = alvo

    def esperar(self, placa):
        self.log.append("espera_z")
        self.z = self.alvo_z


def test_durante_roda_depois_das_juntas_e_antes_do_z_terminar():
    log = []
    pp = PickPlace.__new__(PickPlace)
    pp.r, pp.obstaculo = ScaraFalso(log), None
    pp.juntas_e_z((10.0, 20.0), -87.0, durante=lambda: log.append("durante"))
    assert log.index(("juntas", (10.0, 20.0))) < log.index("durante") < log.index("espera_z")


def test_mira_le_o_z_na_hora_da_foto(monkeypatch):
    """o Z está andando: a projeção usa o Z de quando a foto saiu, não o de antes"""
    zs = []
    monkeypatch.setattr(pick_place, "ponta_xy", lambda cams, ms, xy, z: zs.append(z() if callable(z) else z) or None)
    pp = PickPlace.__new__(PickPlace)
    pp.r, pp.ms, pp.cams = ScaraFalso([]), {}, {}
    pp.r.z = -20.0
    pp.mira(100.0, 50.0, (1.0, 2.0))
    assert zs == [-20.0]


def test_z_mais_rapido_exige_foto_mais_alta():
    """a 80 mm/s o Z desce ~48 mm durante a correção: a mesma altura que bastava a 45 mm/s não basta"""
    z_pega, z = -87.0, -40.0
    assert pode_corrigir(z, z_pega, vz=45.0)
    assert not pode_corrigir(z, z_pega, vz=80.0)


def test_z_do_pick_place_fica_no_testado_com_carga():
    """23/10, Z no DM556 (2,1 A), ventosa, fonte 25,6 V, rampa em S: 160/700 e 120/2000 sem perda; 200 mm/s perde
    mesmo a 450 mm/s² (o limite é a velocidade). O pick_place usa o ganho com pelo menos 20% de folga."""
    assert 100.0 <= pick_place.VZ <= 0.8 * 160.0
    assert 1200.0 <= pick_place.AZ <= 0.8 * 2000.0


def test_tempo_do_z_usa_a_aceleracao_media_da_rampa_s():
    """na rampa em S (cossenoidal) a média é 2/π do pico: com o pico a descida parece mais curta do que é"""
    import math
    assert pick_place.AZ_MEDIA == pytest.approx(pick_place.AZ * 2 / math.pi)
