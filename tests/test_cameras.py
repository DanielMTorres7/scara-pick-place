"""Duas câmeras: caixas vistas pelas duas viram uma só (no referencial do robô); a ponta é conferida pela câmera
que a vê mais longe da borda."""
import pytest

import cameras


def test_mesma_caixa_vista_pelas_duas_vira_uma_na_media():
    obs = [{"cam": "C920", "xy": (300.0, 100.0)}, {"cam": "XWF", "xy": (310.0, 104.0)}]
    out = cameras.juntar_caixas(obs)
    assert len(out) == 1
    assert out[0]["xy"] == pytest.approx((305.0, 102.0))
    assert out[0]["cams"] == ["C920", "XWF"]


def test_caixas_distantes_ficam_separadas():
    obs = [{"cam": "C920", "xy": (300.0, 100.0)}, {"cam": "XWF", "xy": (300.0, 200.0)},
           {"cam": "XWF", "xy": (-200.0, 300.0)}]
    assert len(cameras.juntar_caixas(obs)) == 3


def test_duas_caixas_da_mesma_camera_nunca_se_juntam():
    obs = [{"cam": "C920", "xy": (300.0, 100.0)}, {"cam": "C920", "xy": (330.0, 100.0)}]
    assert len(cameras.juntar_caixas(obs)) == 2


def test_folga_da_borda():
    assert cameras.folga_borda((960, 540), 1920, 1080) == 540
    assert cameras.folga_borda((100, 540), 1920, 1080) == 100
    assert cameras.folga_borda((-5, 540), 1920, 1080) < 0
