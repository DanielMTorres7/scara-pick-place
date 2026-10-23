import numpy as np

import ver_cameras


def test_lado_a_lado_reduz_e_junta_com_o_nome():
    a = np.zeros((1080, 1920, 3), np.uint8)
    b = np.full((1080, 1920, 3), 255, np.uint8)
    out = ver_cameras.lado_a_lado({"C920": a, "XWF": b}, largura=960)
    assert out.shape == (540, 1920, 3)
    assert out[300, 1500].tolist() == [255, 255, 255]       # a XWF fica à direita


def test_camera_sem_quadro_vira_tela_preta():
    out = ver_cameras.lado_a_lado({"C920": None, "XWF": np.zeros((1080, 1920, 3), np.uint8)}, largura=960)
    assert out.shape == (540, 1920, 3)
