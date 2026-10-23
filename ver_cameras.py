"""Janela com as câmeras ao vivo, lado a lado (C920 | XWF). Tecla s salva uma foto de cada em fotos/, q sai.

A câmera só abre num programa por vez: feche esta janela antes de rodar o pick_place, a grade etc.
Uso: python ver_cameras.py
"""
import time

import cv2
import numpy as np

from cameras import CAMERAS

LARGURA = 960      # px de cada câmera na janela


def lado_a_lado(quadros, largura=LARGURA):
    """{nome: quadro BGR ou None} -> uma imagem com as câmeras reduzidas a `largura`, na ordem dada, com o nome"""
    altura = largura * 9 // 16
    partes = []
    for nome, f in quadros.items():
        p = np.zeros((altura, largura, 3), np.uint8) if f is None else cv2.resize(f, (largura, altura))
        cv2.putText(p, nome, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        partes.append(p)
    return np.hstack(partes)


def main():
    from cam import Cam, acha_indice
    cams = {nome: Cam(idx=acha_indice(nome)) for nome, _, _ in CAMERAS}
    try:
        while True:
            quadros = {nome: c.c.read()[1] for nome, c in cams.items()}
            cv2.imshow("cameras", lado_a_lado(quadros))
            tecla = cv2.waitKey(30) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("s"):
                t = time.strftime("%H%M%S")
                for nome, f in quadros.items():
                    if f is not None:
                        cv2.imwrite("fotos/ver_%s_%s.jpg" % (t, nome), f)
                print("salvas fotos/ver_%s_*.jpg" % t)
    finally:
        for c in cams.values():
            c.fechar()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
