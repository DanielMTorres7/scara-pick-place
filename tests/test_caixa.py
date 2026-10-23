"""Sementes de caixa: impressão retangular (mesmo quase quadrada, como a do Levoxin) entra; hexágono azul do braço não."""
import cv2
import numpy as np

from caixa import _sementes


def _mesa():
    return np.full((1080, 1920, 3), 235, np.uint8)


def _hexagono(f, c, r):
    pts = np.array([(c[0] + r * np.cos(np.radians(60 * k)), c[1] + r * np.sin(np.radians(60 * k))) for k in range(6)])
    cv2.fillPoly(f, [pts.astype(np.int32)], (140, 40, 20))


def test_impressao_quase_quadrada_entra():
    f = _mesa()
    cv2.rectangle(f, (930, 185), (1007, 275), (160, 60, 20), -1)          # bloco azul 77 x 90 (Levoxin)
    cv2.rectangle(f, (925, 150), (1008, 172), (40, 40, 200), -1)          # faixa vermelha
    s = _sementes(f, None)
    assert len(s) == 1 and abs(s[0][0][0] - 968) < 5 and abs(s[0][0][1] - 230) < 5


def test_impressao_retangular_continua_entrando():
    f = _mesa()
    cv2.rectangle(f, (500, 500), (650, 600), (160, 60, 20), -1)           # 150 x 100 (Micpure)
    assert len(_sementes(f, None)) == 1


def test_hexagono_do_braco_nao_entra():
    f = _mesa()
    _hexagono(f, (1300, 900), 70)
    _hexagono(f, (600, 300), 55)
    assert _sementes(f, None) == []


def _roxo(h=140):
    hsv = np.full((1080, 1920, 3), (h, 90, 110), np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_mesa_roxa_nao_vira_semente():
    for h in (122, 140, 158):                                             # tampo roxo nas duas câmeras
        assert _sementes(_roxo(h), None) == []


def test_caixa_em_mesa_roxa_entra():
    f = _roxo()
    cv2.rectangle(f, (500, 500), (650, 600), (160, 60, 20), -1)           # impressão azul 150 x 100
    s = _sementes(f, None)
    assert len(s) == 1 and abs(s[0][0][0] - 575) < 5


def test_impressao_quase_quadrada_com_cantos_apagados_entra():
    """na C920 a impressão azul (degradê) de algumas caixas sai quase quadrada e só ~83% cheia: ainda é caixa"""
    f = _mesa()
    x0, y0, w, h, c = 700, 700, 90, 78, 25
    pts = np.array([(x0 + c, y0), (x0 + w - c, y0), (x0 + w, y0 + c), (x0 + w, y0 + h - c), (x0 + w - c, y0 + h),
                    (x0 + c, y0 + h), (x0, y0 + h - c), (x0, y0 + c)], np.int32)
    cv2.fillPoly(f, [pts], (160, 60, 20))
    assert len(_sementes(f, None)) == 1


def test_com_o_braco_conhecido_descarta_so_perto_dele():
    """sabendo onde estão os hexágonos do braço na foto, a regra do preenchimento não precisa cortar caixas"""
    f = _mesa()
    _hexagono(f, (1300, 900), 70)
    pts = np.array([(700, 700), (735, 700), (790, 755), (790, 778), (700, 778)], np.int32)   # 90 x 78, ~78% cheia
    cv2.fillPoly(f, [pts], (160, 60, 20))
    assert _sementes(f, None) == []                                      # sem saber do braço: corta as duas
    s = _sementes(f, None, braco_px=[(1290, 910)])
    assert len(s) == 1 and abs(s[0][0][0] - 745) < 5
