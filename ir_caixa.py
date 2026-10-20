"""Leva a ventosa ao centro da caixa vista pela câmera, confere pela câmera (malha fechada) e desce até encostar.

Uso: python ir_caixa.py [--sem-descer]
"""
import math
import sys

import cv2
import numpy as np

import modelo
from cam import Cam
from caixa import acha_caixas
from modelo import Modelo
from ponta import ponta_precisa
from scara import MovimentoAbortado, Scara, Z_TOQUE_MESA

Z_ALTO = -40.0          # altura de deslocamento (ventosa ~65 mm acima de uma caixa de 30 mm)
FOLGA_LENTA = 10.0      # mm acima do toque em que a descida passa a ser lenta
V_TOQUE = 0.1           # fração da velocidade do Z (20 mm/s) na aproximação final = 2 mm/s


def main(roi=None, tol_mm=1.5, max_iter=3, descer=True, altura_caixa=modelo.ALTURA_CAIXA):
    m = Modelo()
    r = Scara(fator_vel=1.0)
    c = Cam()
    try:
        if r.posicao("z") < Z_ALTO:
            r.ir("z", Z_ALTO)
        f = c.foto()
        cx = acha_caixas(f, roi=roi)
        if not cx:
            raise RuntimeError("nenhuma caixa encontrada")
        caixa = cx[0]
        u, v = caixa["centro"]
        x, y = m.caixa_para_robo(u, v, altura_caixa)
        print("caixa px (%.1f, %.1f) -> robô (%.1f, %.1f) mm" % (u, v, x, y))
        pos = r.posicoes()
        cmd = list(m.ik(x, y, ref=(pos["j1"], pos["j2"])))
        for it in range(max_iter + 1):
            print("iter %d: J1=%.2f J2=%.2f" % (it, cmd[0], cmd[1]))
            r.ir_juntas(cmd[0], cmd[1])
            z = r.posicao("z")
            f = c.foto("fotos/ir_caixa_%d.jpg" % it)
            p = ponta_precisa(f)
            if p is None:
                raise RuntimeError("ponta não encontrada na imagem")
            xr, yr = m.pixel_para_robo(p[0], p[1], z)          # onde a ponta está de fato (mm)
            ex, ey = x - xr, y - yr
            e = math.hypot(ex, ey)
            prev = m.robo_para_pixel(x, y, z)
            print("   ponta px (%.1f, %.1f), esperado (%.1f, %.1f) -> erro %.1f mm" % (p[0], p[1], prev[0], prev[1], e))
            if e <= tol_mm or it == max_iter:
                break
            xa, ya = m.fk(*cmd)
            cmd = list(m.ik(xa + ex, ya + ey, ref=cmd))
        vis = f.copy()
        cv2.drawContours(vis, [np.int32(caixa["cantos"])], -1, (0, 255, 0), 2)
        cv2.drawMarker(vis, (int(u), int(v)), (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
        cv2.drawMarker(vis, (int(prev[0]), int(prev[1])), (255, 0, 255), cv2.MARKER_TILTED_CROSS, 30, 2)
        cv2.drawMarker(vis, (int(p[0]), int(p[1])), (0, 0, 255), cv2.MARKER_CROSS, 40, 2)
        cv2.imwrite("fotos/ir_caixa_final.jpg", vis)
        if descer:
            z_toque = Z_TOQUE_MESA + altura_caixa
            r.ir("z", z_toque + FOLGA_LENTA)
            try:
                r.ir("z", z_toque, fator=V_TOQUE)
            except MovimentoAbortado as ex:   # o fim de curso de baixo aciona antes de encostar numa caixa baixa
                if "FIM" not in str(ex):
                    raise
                print("fim de curso de baixo antes de encostar:", ex)
            print("encostou: z = %.2f" % r.posicao("z"))
            c.foto("fotos/ir_caixa_toque.jpg")
        return {"caixa_mm": (x, y), "juntas": cmd, "erro_mm": e}
    except Exception as ex:
        print("ERRO", ex)
        r.parar()
        raise
    finally:
        c.fechar()
        r.fechar()


if __name__ == "__main__":
    print(main(roi=(560, 450, 860, 780), descer="--sem-descer" not in sys.argv))
