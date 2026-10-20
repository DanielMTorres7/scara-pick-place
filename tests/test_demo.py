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
