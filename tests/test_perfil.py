import numpy as np
import pytest

import scara


def _amostra(T, f, suave, n=4001):
    t = np.linspace(0, T, n)
    s = np.array([scara.s_curva(x, T, f, suave) for x in t])
    v = np.gradient(s, t); a = np.gradient(v, t)
    return t, s, v, a


@pytest.mark.parametrize("suave", [0.0, 0.5, 1.0])
def test_curva_vai_de_0_a_1_sem_voltar(suave):
    t, s, v, _ = _amostra(2.0, 0.3, suave)
    assert s[0] == pytest.approx(0) and s[-1] == pytest.approx(1)
    assert np.all(np.diff(s) >= -1e-12)


def test_suave_0_e_o_trapezio():
    for x in np.linspace(0, 2.0, 50):
        assert scara.s_curva(x, 2.0, 0.3, 0.0) == pytest.approx(scara.s_trapezio(x, 2.0, 0.3))


@pytest.mark.parametrize("suave", [0.0, 0.5, 1.0])
def test_aceleracao_de_pico_e_a_prevista(suave):
    T, f = 2.0, 0.3
    _, _, _, a = _amostra(T, f, suave, 20001)
    pico = 1 / (T * T * (1 - f) * f * (1 - suave / 2))
    assert np.max(np.abs(a[50:-50])) == pytest.approx(pico, rel=0.02)


def test_curva_s_nao_tem_degrau_de_aceleracao():
    t, _, _, a = _amostra(2.0, 0.3, 1.0, 20001)
    assert np.max(np.abs(np.diff(a[50:-50]))) < 0.01 * np.max(np.abs(a))


def test_perfil_sincrono_com_curva_s_respeita_a_aceleracao_de_pico():
    d, amax = {"j1": 120.0}, {"j1": 100.0}
    for suave in (0.0, 1.0):
        T, f = scara.perfil_sincrono(d, {"j1": 1e9}, amax, suave)
        pico = 120.0 / (T * T * (1 - f) * f * (1 - suave / 2))
        assert pico <= 100.0 + 1e-6
