"""Teste com as duas câmeras: acha as caixas de remédio na mesa toda e leva a ponta até cima de cada uma (sem pegar).

Cada câmera fotografa com o braço fora da vista dela; as caixas viram coordenadas do robô e as duas listas se juntam.
Em cada caixa: vai no alto, desce até Z_MIRA, confere a ponta pela câmera que a vê melhor (corrige uma vez) e desce
até Z_PERTO (a chave de baixo do Z não deixa encostar).

Uso: python ir_caixas.py
"""
import math
import time

from cam import Cam, acha_indice
from cameras import CAMERAS, fotos, modelos, ponta_xy, ver_caixas
from scara import ACEL_SEGURA as AMAX
from scara import VEL_SEGURA as VMAX
from scara import Scara

Z_ALTO = -40.0            # deslocamento: ventosa ~65 mm acima de uma caixa de 30 mm
Z_MIRA = -65.0
Z_PERTO = -75.0           # ~10 mm acima do topo da caixa (a ventosa encosta em -84)


def main():
    ms = modelos()
    r = Scara(fator_vel=1.0)
    cams = {nome: Cam(idx=acha_indice(nome)) for nome, _, _ in CAMERAS}
    try:
        if r.posicao("z") < Z_ALTO:
            r.ir("z", Z_ALTO)
        caixas = ver_caixas(fotos(r, cams, "fotos/ir_caixas"), ms)
        print("%d caixas:" % len(caixas))
        for k in caixas:
            print("   (%.0f, %.0f) mm vista por %s" % (*k["xy"], "+".join(k["cams"])))
        m = ms["C920"]
        for i, k in enumerate(caixas):
            x, y = k["xy"]
            pos = r.posicoes()
            try:
                cmd = m.ik(x, y, ref=(pos["j1"], pos["j2"]))
            except ValueError as ex:
                print("caixa %d (%.0f, %.0f): fora do alcance (%s)" % (i + 1, x, y, ex))
                continue
            t = time.time()
            r.ir("z", Z_ALTO)
            r.ir_juntas(*cmd, vmax=VMAX, amax=AMAX)
            r.ir("z", Z_MIRA)
            v = ponta_xy(cams, ms, m.fk(*cmd), Z_MIRA)
            if v is None:
                print("caixa %d: ponta não encontrada, sem correção" % (i + 1))
            else:
                n, xr, yr = v
                e = math.hypot(x - xr, y - yr)
                print("caixa %d (%.0f, %.0f): juntas (%.1f, %.1f), erro %.1f mm pela %s" % (i + 1, x, y, *cmd, e, n))
                if e > 2.0:
                    xa, ya = m.fk(*cmd)
                    cmd = m.ik(xa + x - xr, ya + y - yr, ref=cmd)
                    r.ir_juntas(*cmd, vmax=VMAX, amax=AMAX)
                    v = ponta_xy(cams, ms, m.fk(*cmd), Z_MIRA)
                    if v is not None:
                        print("   depois da correção: %.1f mm pela %s" % (math.hypot(x - v[1], y - v[2]), v[0]))
            r.ir("z", Z_PERTO)
            time.sleep(0.5)
            r.ir("z", Z_ALTO)
            print("   %.1f s" % (time.time() - t))
        r.ir_juntas(*CAMERAS[0][2], vmax=VMAX, amax=AMAX)
    except BaseException:
        r.parar()
        raise
    finally:
        for c in cams.values():
            c.fechar()
        r.fechar()


if __name__ == "__main__":
    main()
