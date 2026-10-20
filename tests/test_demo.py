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


def test_movimento_da_camera_recupera_rotacao_e_deslocamento_do_fundo():
    import cv2
    import numpy as np
    rng = np.random.default_rng(0)
    f0 = cv2.GaussianBlur(rng.integers(0, 255, (540, 960), np.uint8), (3, 3), 0)
    f0 = cv2.cvtColor(f0, cv2.COLOR_GRAY2BGR)
    M = cv2.getRotationMatrix2D((480, 270), 2.0, 1.0); M[:, 2] += (15, -8)
    f1 = cv2.warpAffine(f0, M, (960, 540))
    Me = demo.mov_camera(f0, f1)
    assert np.allclose(demo.aplica(Me, (400.0, 300.0)), demo.aplica(M, (400.0, 300.0)), atol=1.0)
