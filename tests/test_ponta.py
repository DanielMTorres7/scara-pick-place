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


def test_faixa_padrao_acha_hexagono_desbotado():
    """C920 com a luz de 23/10: o azul do rolamento sai com saturação ~85"""
    img = np.full((1080, 1920, 3), 230, np.uint8)
    pts = np.array([(900 + 60 * np.cos(a), 500 + 60 * np.sin(a)) for a in np.radians(np.arange(0, 360, 60))], np.int32)
    cv2.fillConvexPoly(img, pts, (100, 70, 60))                  # azul acinzentado: H ~115, S ~102 -> 85 com ruído
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    img[hsv[..., 1] > 50] = cv2.cvtColor(np.uint8([[(116, 85, 100)]]), cv2.COLOR_HSV2BGR)[0, 0]
    cv2.circle(img, (900, 500), 20, (120, 120, 120), -1)
    p = ponta.acha_ponta(img)
    assert p is not None and np.hypot(p["c"][0] - 900, p["c"][1] - 500) < 3


def test_faixa_padrao_ignora_a_mangueira_e_aceita_hexagono_claro():
    """23/10 com a mesa fechada: a mangueira azul-clara da ventosa (H ~101) passa por cima do hexágono e o reflexo deixa
    o hexágono claro (V ~170). A faixa padrão tem que achar o hexágono e não a mangueira."""
    img = np.full((1080, 1920, 3), 230, np.uint8)
    pts = np.array([(900 + 60 * np.cos(a), 500 + 60 * np.sin(a)) for a in np.radians(np.arange(0, 360, 60))], np.int32)
    azul = cv2.cvtColor(np.uint8([[(112, 130, 170)]]), cv2.COLOR_HSV2BGR)[0, 0]
    mangueira = cv2.cvtColor(np.uint8([[(101, 150, 200)]]), cv2.COLOR_HSV2BGR)[0, 0]
    cv2.fillConvexPoly(img, pts, tuple(int(x) for x in azul))
    cv2.circle(img, (900, 500), 20, (200, 200, 200), -1)
    cv2.circle(img, (1150, 500), 230, tuple(int(x) for x in mangueira), 14)   # laço da mangueira em volta da ponta
    cv2.line(img, (900, 500), (1000, 330), tuple(int(x) for x in mangueira), 14)
    p = ponta.acha_ponta(img, perto=(930, 520))
    assert p is not None and np.hypot(p["c"][0] - 900, p["c"][1] - 500) < 6


def test_ponta_sobre_a_mesa_roxa():
    """23/10, mesa em outro lugar: a mesa roxa sai com H ~118-130, S ~90 e entrava na faixa (H até 130); colada no
    hexágono (H ~110, S ~155), virava uma mancha só e a ponta sumia"""
    hsv = np.full((1080, 1920, 3), (124, 95, 125), np.uint8)
    hsv[:, :700] = (119, 90, 130)                               # a parte da mesa mais azulada (C920)
    pts = np.array([(700 + 60 * np.cos(a), 500 + 60 * np.sin(a)) for a in np.radians(np.arange(0, 360, 60))], np.int32)
    cv2.fillConvexPoly(hsv, pts, (110, 155, 145))
    cv2.circle(hsv, (700, 500), 20, (0, 0, 120), -1)
    img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    p = ponta.acha_ponta(img, perto=(690, 510))
    assert p is not None and np.hypot(p["c"][0] - 700, p["c"][1] - 500) < 3
