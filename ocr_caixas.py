"""Nome da caixa de remédio por OCR local (RapidOCR). FORA DE USO desde 23/10 (o pick_place voltou a usar só o Gemini).

A caixa vem do OpenCV (caixa.acha_caixas: cantos em px): recorta endireitada (lado maior na horizontal), amplia e lê
nas duas orientações. A leitura sai aproximada ("Fancox", "Dararen", "rpado"): vale o remédio da lista mais parecido,
só se a semelhança passar de LIMIAR; senão a caixa fica sem nome (melhor que nome errado). ~1 s por caixa na CPU.
"""
import difflib
import re
import threading

import cv2
import numpy as np

# remédios já vistos na mesa (23/10); remédio novo: acrescentar aqui (os pedidos na OS entram sozinhos, por `extras`)
CATALOGO = ("levoxin", "micpure", "flancox", "arpadol", "donaren", "miosan")
LIMIAR = 0.7        # semelhança mínima (difflib): "Dararen" x donaren = 0,71; lixo do OCR ("CBum", "Dado") < 0,4
ESCALA = 4          # o nome tem ~10-15 px de altura na foto 1080p: ampliar ajuda o OCR
ESCALAS = (ESCALA, 3)   # sem nome a 4x, tenta a 3x (23/10: a Micpure só saiu a 3x)

_local = threading.local()     # um leitor por thread: o pick_place lê várias caixas ao mesmo tempo


def casa_nome(textos, extras=()):
    """nome da lista (com inicial maiúscula) mais parecido com algum texto lido, ou "" se nenhum passar do LIMIAR"""
    lista = {n.lower() for n in CATALOGO} | {n.lower() for n in extras}
    melhor, nota = "", LIMIAR
    for t in textos:
        t = re.sub(r"[^a-z]", "", t.lower())
        if len(t) < 3:
            continue
        for n in lista:
            r = difflib.SequenceMatcher(None, t, n).ratio()
            if r >= nota:
                melhor, nota = n, r
    return melhor.capitalize()


def recorte(f, cantos, escala=ESCALA):
    """a caixa endireitada e ampliada, com o lado maior na horizontal"""
    c = np.float32(cantos)
    if np.linalg.norm(c[1] - c[0]) < np.linalg.norm(c[2] - c[1]):
        c = np.roll(c, -1, axis=0)
    w, h = np.linalg.norm(c[1] - c[0]) * escala, np.linalg.norm(c[2] - c[1]) * escala
    W, H = int(round(w)), int(round(h))
    m = cv2.getPerspectiveTransform(c, np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
    return cv2.warpPerspective(f, m, (W, H))


def _leitor():
    if getattr(_local, "ocr", None) is None:
        from rapidocr_onnxruntime import RapidOCR    # só quando precisa: carrega os modelos (~1 s)
        _local.ocr = RapidOCR()
    return _local.ocr


# o RapidOCR já endireita texto de ponta-cabeça: 0° e 90° bastam (23/10, 17 caixas reais: os mesmos 11 nomes que com
# as 4 orientações, em 2/3 do tempo; cada leitura ~0,45 s)
GIROS = (None, cv2.ROTATE_90_CLOCKWISE)


def ler_textos(img, giro=None):
    """textos lidos na imagem (girada por `giro`, constante do cv2.rotate)"""
    r, _ = _leitor()(img if giro is None else cv2.rotate(img, giro))
    return [x[1] for x in (r or [])]


def nome_por_ocr(f, cantos, extras=()):
    """nome da caixa: nas ESCALAS e nas 4 orientações (de ponta-cabeça; nome ao longo do lado menor — 23/10: Micpure e
    uma Arpadol só saíram com a caixa girada 90°), parando na primeira leitura que dá um nome da lista"""
    for escala in ESCALAS:
        img = recorte(f, cantos, escala)
        for giro in GIROS:
            nome = casa_nome(ler_textos(img, giro), extras)
            if nome:
                return nome
    return ""
