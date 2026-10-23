"""Perfis para mover o Z junto com J1+J2: duração/posição das juntas no tempo e tempo do Z (trapézio)."""
import pytest

import scara


def test_plano_juntas_parado_dura_zero():
    assert scara.plano_juntas({"j1": 10, "j2": 5}, {"j1": 10, "j2": 5})[0] == 0.0


def test_juntas_em_vai_do_inicio_ao_alvo():
    ini, alvo = {"j1": 0.0, "j2": 0.0}, {"j1": 60.0, "j2": -30.0}
    T, f = scara.plano_juntas(ini, alvo, scara.VEL_SEGURA, scara.ACEL_SEGURA)
    assert T > 0
    assert scara.juntas_em(ini, alvo, T, f, scara.SUAVE, 0) == pytest.approx(ini)
    assert scara.juntas_em(ini, alvo, T, f, scara.SUAVE, T) == pytest.approx(alvo)
    meio = scara.juntas_em(ini, alvo, T, f, scara.SUAVE, T / 2)
    assert meio["j1"] == pytest.approx(30.0, abs=0.5) and meio["j2"] == pytest.approx(-15.0, abs=0.5)


def test_tempo_ate_no_trapezio():
    # 100 mm a 50 mm/s e 100 mm/s²: rampa de 0,5 s (12,5 mm), cruzeiro de 1,5 s, rampa de 0,5 s
    assert scara.tempo_ate(100, 12.5, 50, 100) == pytest.approx(0.5)
    assert scara.tempo_ate(100, 50, 50, 100) == pytest.approx(1.25)
    assert scara.tempo_ate(100, 100, 50, 100) == pytest.approx(2.5)


def test_tempo_ate_no_triangulo():
    # 10 mm não chega a 50 mm/s: sobe 0,316 s e desce 0,316 s
    assert scara.tempo_ate(10, 10, 50, 100) == pytest.approx(0.632, abs=1e-3)
    assert scara.tempo_ate(10, 5, 50, 100) == pytest.approx(0.316, abs=1e-3)


def _traj():
    ini, alvo = {"j1": 0.0, "j2": 0.0}, {"j1": 60.0, "j2": 0.0}
    T, f = scara.plano_juntas(ini, alvo, scara.VEL_SEGURA, scara.ACEL_SEGURA)
    return (lambda t: scara.juntas_em(ini, alvo, T, f, scara.SUAVE, t)), T


def test_t_saida_e_quando_o_braco_deixa_a_coletora_de_vez():
    from pick_place import t_saida
    traj, T = _traj()
    assert t_saida(lambda j1, j2: j1 > 30, traj, T) == pytest.approx(T / 2, abs=0.03)   # simétrico: meio caminho
    assert t_saida(lambda j1, j2: True, traj, T) == 0.0


def test_t_entrada_e_quando_o_braco_chega_na_coletora():
    from pick_place import t_entrada
    traj, T = _traj()
    assert t_entrada(lambda j1, j2: j1 < 30, traj, T) == pytest.approx(T / 2, abs=0.03)
    assert t_entrada(lambda j1, j2: True, traj, T) is None
