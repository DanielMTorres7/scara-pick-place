"""OCR local dos nomes das caixas (ocr_caixas): FORA DE USO desde 23/10 (o user voltou ao Gemini só); fica para religar.
As leituras do RapidOCR nas fotos reais saem aproximadas; a lista de remédios conhecidos as corrige e descarta o resto."""
import cv2
import numpy as np

import ocr_caixas


def test_leituras_reais_viram_o_nome_da_lista():
    casos = {("Fancox",): "Flancox", ("Dararen",): "Donaren", ("Doraren",): "Donaren", ("rpado",): "Arpadol",
             ("UXOAO", "Levoxin"): "Levoxin", ("Levodn", "UPLDAS"): "Levoxin", ("Arpadol", "Arpadol"): "Arpadol"}
    for textos, nome in casos.items():
        assert ocr_caixas.casa_nome(list(textos)) == nome, textos


def test_lixo_do_ocr_nao_vira_nome():
    for textos in (["XO"], ["CBum"], ["De", "Dado"], ["公", "XO"], []):
        assert ocr_caixas.casa_nome(textos) == "", textos


def test_nome_pedido_na_os_entra_na_lista():
    assert ocr_caixas.casa_nome(["Novalgina"]) == ""
    assert ocr_caixas.casa_nome(["Novalgna"], extras=["novalgina"]) == "Novalgina"


def test_recorte_deixa_o_lado_maior_na_horizontal():
    f = np.zeros((1080, 1920, 3), np.uint8)
    rect = ((900.0, 500.0), (120.0, 180.0), 30.0)                   # caixa de pé e girada
    cantos = cv2.boxPoints(rect)
    r = ocr_caixas.recorte(f, cantos, escala=4)
    assert r.shape[1] > r.shape[0]
    assert abs(r.shape[1] - 180 * 4) < 4 and abs(r.shape[0] - 120 * 4) < 4


def test_nome_impresso_ao_longo_do_lado_menor_e_lido_girando_90(monkeypatch):
    """23/10: Micpure e uma Arpadol só foram lidas com a caixa girada 90° (nome ao longo do lado menor)"""
    def leitor_falso(img):
        return ([[None, "Micpure", 0.9]] if img.shape[0] > img.shape[1] else []), None   # só de pé
    monkeypatch.setattr(ocr_caixas, "_leitor", lambda: leitor_falso)
    f = np.zeros((1080, 1920, 3), np.uint8)
    cantos = cv2.boxPoints(((900.0, 500.0), (180.0, 120.0), 0.0))
    assert ocr_caixas.nome_por_ocr(f, cantos) == "Micpure"

