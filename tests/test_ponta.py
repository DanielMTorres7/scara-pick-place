import cv2
import numpy as np

import ponta


def _hexagono(img, c, r, centro_cinza):
    pts = np.array([(c[0] + r * np.cos(a), c[1] + r * np.sin(a)) for a in np.radians(np.arange(0, 360, 60))], np.int32)
    cv2.fillConvexPoly(img, pts, (110, 30, 8))                   # azul escuro do rolamento (BGR)
    cv2.circle(img, c, 20, (centro_cinza,) * 3, -1)


def test_ponta_com_centro_meio_escuro_ainda_e_ponta_e_cotovelo_escuro_nao():
    img = np.full((1080, 1920, 3), 230, np.uint8)
    _hexagono(img, (1460, 520), 72, 30)       # cotovelo: motor escuro no meio
    _hexagono(img, (1650, 230), 61, 95)       # ponta com menos luz que na calibração antiga
    p = ponta.acha_ponta(img)
    assert p is not None
    assert np.hypot(p["c"][0] - 1650, p["c"][1] - 230) < 3


def test_perto_escolhe_o_candidato_mais_proximo_da_previsao():
    img = np.full((1080, 1920, 3), 230, np.uint8)
    _hexagono(img, (1456, 751), 63, 200)      # alicate de cabo azul: centro bem claro
    _hexagono(img, (500, 700), 61, 95)        # ponta de verdade
    assert np.hypot(*np.subtract(ponta.acha_ponta(img)["c"], (1456, 751))) < 3
    p = ponta.acha_ponta(img, perto=(510, 690))
    assert np.hypot(p["c"][0] - 500, p["c"][1] - 700) < 3
