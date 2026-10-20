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


def test_limita_respeita_rpm_e_aceleracao_medidas():
    v, a = demo.limita("j1", 900, 120)
    assert v == pytest.approx(demo.vel("j1", demo.LIMITES["j1"][0]))
    assert a == pytest.approx(demo.LIMITES["j1"][1])
    v, a = demo.limita("j2", 150, 160)               # abaixo dos limites: rpm pedida, aceleração da rampa normal
    assert v == pytest.approx(demo.vel("j2", 150))
    assert a == pytest.approx(demo.acel(v, 160))


def test_perdas_separa_as_duas_juntas():
    g = {"j1": (-4.7, -12.0), "j2": (-5.0, -3.3)}
    erro = tuple(2.0 * a - 1.5 * b for a, b in zip(g["j1"], g["j2"]))     # j1 +2°, j2 -1.5°
    p = demo.perdas(erro, g)
    assert p["j1"] == pytest.approx(2.0)
    assert p["j2"] == pytest.approx(-1.5)


def test_cantos_do_tabuleiro_iguais_em_chamadas_repetidas():
    import numpy as np
    f = _xadrez()
    cs = [demo.cantos_xadrez(f) for _ in range(10)]
    assert all(c is not None for c in cs)
    assert all(np.allclose(c, cs[0]) for c in cs)
