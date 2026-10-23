"""Homing do J1 pela visão: a ponta vista pelas câmeras em poses conhecidas dá o desvio do J1. O J2 fica fixo (a chave
dele garante ~0,3°): soltá-lo deixa o viés da calibração da XWF contaminar o J1."""
import pytest

import homing
from cameras import modelos


def _vista(ms, pose, z, d1, d2=0.0):
    """pixel em que cada câmera veria a ponta se as juntas reais fossem pose + (d1, d2)"""
    return {n: ms[n].robo_para_pixel(*ms[n].fk(pose[0] + d1, pose[1] + d2), z)[:2] for n in ms}


def test_recupera_o_desvio_do_j1():
    ms = modelos()
    pose = homing.POSES[0]
    d1, resid = homing.estimar_desvio(_vista(ms, pose, homing.Z, 5.7), ms, pose, homing.Z)
    assert d1 == pytest.approx(5.7, abs=0.02) and resid < 0.5


def test_com_uma_camera_so_tambem_estima():
    ms = modelos()
    pose = homing.POSES[0]
    d1, _ = homing.estimar_desvio({"C920": _vista(ms, pose, homing.Z, -3.0)["C920"]}, ms, pose, homing.Z)
    assert d1 == pytest.approx(-3.0, abs=0.02)


def test_sem_camera_nenhuma_levanta():
    with pytest.raises(homing.HomingFalhou):
        homing.estimar_desvio({}, modelos(), homing.POSES[0], homing.Z)


def test_desvio_absurdo_levanta():
    with pytest.raises(homing.HomingFalhou, match="J1"):
        homing.conferir([30.0, 29.5])


def test_uma_medida_so_nao_corrige():
    """23/10: uma câmera numa pose só deu +8,24° (detecção errada), foi aplicado e o J1 bateu na parede"""
    with pytest.raises(homing.HomingFalhou, match="uma medida"):
        homing.conferir([8.24])


def test_poses_que_discordam_levantam():
    with pytest.raises(homing.HomingFalhou, match="discordam"):
        homing.conferir([0.5, 4.0])


def test_desvio_final_e_a_mediana():
    assert homing.conferir([1.0, 1.2]) == pytest.approx(1.1)


def test_uma_medida_fora_entre_quatro_e_descartada():
    """23/10, lugar novo: C920 e XWF nas duas poses deram +3,60, +5,71, +3,91, +4,43 (a XWF da pose 0 fora, calibração);
    as outras três concordam: vale a mediana delas"""
    assert homing.conferir([3.60, 5.71, 3.91, 4.43]) == pytest.approx(3.91)


def test_duas_medidas_fora_ainda_recusa():
    with pytest.raises(homing.HomingFalhou, match="discordam"):
        homing.conferir([3.6, 5.7, 3.9, 6.0])


def test_com_tres_medidas_descarta_a_de_fora():
    """23/10, calibração nova: C920 +0,06 e +0,57, XWF na pose 0 +1,70 (essa câmera nessa pose destoa sempre)"""
    assert homing.conferir([0.06, 1.70, 0.57]) == pytest.approx(0.315)


def test_com_tres_medidas_todas_espalhadas_recusa():
    with pytest.raises(homing.HomingFalhou, match="discordam"):
        homing.conferir([0.0, 1.6, 3.2])



class _RFalso:
    def __init__(self):
        self.j1 = 0.0

    def posicao(self, eixo):
        return self.j1 if eixo == "j1" else 100.0

    def definir(self, eixo, v):
        self.j1 = v


def test_uma_medida_so_corrige_provisorio_e_confere_na_segunda_passada(monkeypatch):
    """23/10: J1 alinhado à mão ~15° fora, só uma câmera achou a ponta (+15,63). Aplica, mede de novo: as outras poses
    passam a achar a ponta e confirmam."""
    passadas = iter([([15.63], ["XWF"]), ([0.30, 0.50, 0.40], ["C920", "XWF", "C920"])])
    monkeypatch.setattr(homing, "_medir", lambda *a, **k: next(passadas))
    r = _RFalso()
    assert homing.homing_j1(r, {}, {}) == pytest.approx(16.03)
    assert r.j1 == pytest.approx(16.03)


def test_segunda_passada_sem_confirmar_desfaz_e_para(monkeypatch):
    passadas = iter([([15.63], ["XWF"]), ([9.0], ["XWF"])])
    monkeypatch.setattr(homing, "_medir", lambda *a, **k: next(passadas))
    r = _RFalso()
    with pytest.raises(homing.HomingFalhou):
        homing.homing_j1(r, {}, {})
    assert r.j1 == 0.0                                   # a correção provisória não fica


def _fundo():
    import numpy as np
    return np.full((1080, 1920, 3), (90, 30, 60), np.uint8)       # mesa roxa (BGR)


def _ponta(img, c):
    import cv2
    import numpy as np
    pts = np.array([(c[0] + 62 * np.cos(a), c[1] + 62 * np.sin(a)) for a in np.radians(np.arange(0, 360, 60))], np.int32)
    cv2.fillConvexPoly(img, pts, (150, 60, 25))                    # azul do hexágono
    cv2.circle(img, c, 30, (200, 200, 200), -1)                     # rolamento claro
    cv2.circle(img, c, 30, (40, 40, 40), 4)                         # anel (borda que o Hough acha)
    cv2.circle(img, c, 12, (230, 230, 230), -1)


def _logo_de_caixa(img, c):
    import cv2
    cv2.rectangle(img, (c[0] - 70, c[1] - 55), (c[0] + 70, c[1] + 55), (150, 60, 25), -1)   # azul da embalagem
    cv2.rectangle(img, (c[0] - 25, c[1] - 20), (c[0] + 25, c[1] + 20), (235, 235, 235), -1)  # miolo branco, sem anel


def test_logo_azul_de_caixa_nao_vira_ponta():
    """23/10: a XWF marcou o logo azul de uma caixa embaixo da pose do homing (centro claro, sem rolamento) e o J1 saiu
    ~15° errado. Sem o anel do rolamento, não é a ponta."""
    img = _fundo()
    _logo_de_caixa(img, (1568, 685))
    assert homing.ponta_ampla(img, (1474, 711), ((100, 60, 30), (125, 255, 255))) is None


def test_ponta_com_anel_e_achada_mesmo_com_caixa_ao_lado():
    import numpy as np
    img = _fundo()
    _logo_de_caixa(img, (1568, 685))
    _ponta(img, (1480, 715))
    p = homing.ponta_ampla(img, (1474, 711), ((100, 60, 30), (125, 255, 255)))
    assert p is not None and np.hypot(p[0] - 1480, p[1] - 715) < 4
