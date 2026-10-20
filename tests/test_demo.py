import pytest

import demo


def test_rpm_no_motor_para_velocidade_do_eixo():
    assert demo.vel("j1", 900) == pytest.approx(385.714, abs=1e-3)   # redução 14:1
    assert demo.vel("j2", 900) == pytest.approx(450.0)              # 12:1
    assert demo.vel("z", 900) == pytest.approx(120.0)               # fuso de 8 mm/volta


def test_acel_chega_na_velocidade_com_um_quarto_do_curso():
    v, delta = 300.0, 120.0
    a = demo.acel(v, -delta)
    assert v * v / (2 * a) == pytest.approx(delta / 4)


def test_perda_em_graus_usa_so_a_componente_na_direcao_da_junta():
    assert demo.perda_graus((10.0, 3.0), (5.0, 0.0)) == pytest.approx(2.0)
    assert demo.perda_graus((-10.0, 0.0), (5.0, 0.0)) == pytest.approx(-2.0)


def _xadrez():
    import numpy as np
    img = np.full((1080, 1920, 3), 235, np.uint8)
    for i in range(7):                       # 7 linhas x 6 colunas de casas = 5x6 cantos internos (o que a mesa mostra)
        for j in range(6):
            cor = (60, 200, 60) if (i + j) % 2 else (70, 110, 160)     # verde / marrom (BGR)
            img[150 + i * 70:150 + (i + 1) * 70, 250 + j * 70:250 + (j + 1) * 70] = cor
    return img


def test_movimento_da_camera_pelos_cantos_do_tabuleiro():
    import cv2
    import numpy as np
    f0 = _xadrez()
    M = cv2.getRotationMatrix2D((960, 540), 1.5, 1.0); M[:, 2] += (12, -7)
    f1 = cv2.warpAffine(f0, M, (1920, 1080), borderValue=(235, 235, 235))
    Me = demo.mov_camera(f0, f1)
    assert np.allclose(demo.aplica(Me, (1600.0, 400.0)), demo.aplica(M, (1600.0, 400.0)), atol=1.0)


def test_movimento_da_camera_sem_tabuleiro_levanta():
    import numpy as np
    vazio = np.full((1080, 1920, 3), 235, np.uint8)
    with pytest.raises(RuntimeError, match="tabuleiro"):
        demo.mov_camera(vazio, vazio)
