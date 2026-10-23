"""Coletora (MDF): não confunde com o tabuleiro de xadrez (madeira + verde) encostado nela."""
import cv2
import numpy as np

from pick_place import acha_coletora

MADEIRA = cv2.cvtColor(np.uint8([[(15, 120, 190)]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()
VERDE = cv2.cvtColor(np.uint8([[(55, 120, 200)]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()
ROXO = cv2.cvtColor(np.uint8([[(140, 90, 110)]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()


def test_coletora_encostada_no_xadrez():
    f = np.full((1080, 1920, 3), ROXO, np.uint8)
    cv2.rectangle(f, (200, 50), (680, 580), MADEIRA, 18)                  # borda da coletora (vista de cima)
    cv2.rectangle(f, (240, 90), (640, 540), (230, 230, 230), -1)          # remédios dentro
    q = 50
    cv2.rectangle(f, (300, 590), (600, 1040), MADEIRA, -1)               # tabuleiro encostado: borda de madeira
    for i in range(8):                                                    # e os quadrados ~50 px para dentro
        for j in range(6):
            cor = VERDE if (i + j) % 2 else MADEIRA
            cv2.rectangle(f, (300 + j * q, 640 + i * q), (300 + (j + 1) * q, 640 + (i + 1) * q), cor, -1)
    col = acha_coletora(f)
    (cx, cy), (w, h), _ = col["rect"]
    # pode levar a faixa de borda do tabuleiro (madeira sem verde, ~1,5 cm), não o tabuleiro
    assert abs(cx - 440) < 15 and abs(cy - 315) < 35
    assert abs(max(w, h) - 548) < 70 and abs(min(w, h) - 498) < 25        # borda externa: 548 x 498


def test_caixas_dentro_da_coletora_ficam_de_fora():
    from pick_place import fora_da_coletora
    hull = cv2.convexHull(np.float32([(100, 100), (300, 100), (300, 250), (100, 250)]))
    caixas = [{"xy": (200.0, 180.0)}, {"xy": (400.0, 180.0)}, {"xy": (-50.0, 0.0)}]
    assert [k["xy"] for k in fora_da_coletora(caixas, hull)] == [(400.0, 180.0), (-50.0, 0.0)]


def test_coletora_fixa_le_os_cantos_do_arquivo(tmp_path):
    from pick_place import coletora_fixa
    arq = tmp_path / "coletora.json"
    assert coletora_fixa(arq) is None                                     # sem arquivo: detecta pela cor
    arq.write_text('{"cam": "C920", "cantos_px": [[210, 0], [684, 0], [684, 584], [210, 584]]}')
    col = coletora_fixa(arq)
    assert col["cam"] == "C920" and col["cantos"].shape == (4, 2) and col["cantos"][2].tolist() == [684, 584]


class _Braco:
    L1 = 300.0

    def cotovelo(self, j1):
        return (300.0, 0.0) if j1 == 0 else (0.0, 300.0)

    def fk(self, j1, j2):
        return (500.0, 0.0) if j1 == 0 else (0.0, 500.0)


def test_braco_livre_ve_os_dois_segmentos_contra_a_coletora():
    from pick_place import braco_livre
    hull = cv2.convexHull(np.float32([(380, -40), (460, -40), (460, 40), (380, 40)]))   # em cima do antebraço em j1=0
    assert not braco_livre(_Braco(), hull, 0, 0)
    assert braco_livre(_Braco(), hull, 90, 0)
    assert braco_livre(_Braco(), None, 0, 0)


def test_coletora_mm_da_coletora_fixa(tmp_path):
    from pick_place import coletora_mm
    from cameras import modelos
    arq = tmp_path / "coletora.json"
    arq.write_text('{"cam": "C920", "cantos_px": [[210, 0], [684, 0], [684, 584], [210, 584]]}')
    hull = coletora_mm(modelos(), arq)
    assert hull is not None and len(hull) >= 4


def test_coletora_com_tamanho_de_coletora_passa():
    import pick_place
    pick_place.confere_coletora(386.0, 250.0)          # boca e largura das detecções certas de 23/10


def test_faixa_de_madeira_nao_e_coletora():
    """23/10: a detecção pegou a borda de madeira da mesa (boca 644 mm, estreita) e as caixas DENTRO da coletora
    viraram alvo: o braço desceu nela. Coletora sem tamanho de coletora para antes de mover."""
    import pytest
    import pick_place
    with pytest.raises(RuntimeError, match="coletora"):
        pick_place.confere_coletora(644.0, 40.0)
    with pytest.raises(RuntimeError, match="coletora"):
        pick_place.confere_coletora(380.0, 30.0)
    with pytest.raises(RuntimeError, match="coletora"):
        pick_place.confere_coletora(150.0, 120.0)
