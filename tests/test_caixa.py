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
