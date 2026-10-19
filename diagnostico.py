"""Mede pela câmera quanto J1 e J2 se deslocaram do modelo (e confere o Z pela chave de cima)."""
import json, time, sys
import numpy as np
from scipy.optimize import least_squares
from scara import Scara, Z_CHAVE
from cam import Cam
from modelo import Modelo
from ponta import ponta_precisa

POSES = [(-90, -50), (-70, -110), (-50, -20), (-110, -20), (-90, 10)]

def medir(r, c, m, checar_z=True, lento={"j1": 30, "j2": 30}):
    out = {}
    if checar_z:
        zc = r.referenciar_z(); out["z_erro"] = zc - Z_CHAVE; r.definir("z", Z_CHAVE)
    r.ir("z", -40)
    obs = []
    for j in POSES:
        r.ir_juntas(*j, amax=lento); time.sleep(0.3)
        p = ponta_precisa(c.foto())
        if p: obs.append((j, p))
    def res(d):
        e = []
        for (j1, j2), p in obs:
            u = m.robo_para_pixel(*m.fk(j1 + d[0], j2 + d[1]), -40)
            e += [u[0] - p[0], u[1] - p[1]]
        return e
    s = least_squares(res, [0, 0])
    out.update({"dj1": s.x[0], "dj2": s.x[1], "residuo_px": float(np.sqrt(np.mean(np.square(s.fun))))})
    return out

def corrigir(r, d):
    pos = r.posicoes()
    r.definir("j1", pos["j1"] + d["dj1"]); r.definir("j2", pos["j2"] + d["dj2"])

if __name__ == "__main__":
    r = Scara(fator_vel=1.0); c = Cam(); m = Modelo()
    try:
        d = medir(r, c, m)
        print({k: round(v, 2) for k, v in d.items()})
        if "--corrigir" in sys.argv:
            corrigir(r, d); print("corrigido:", {k: round(v, 2) for k, v in medir(r, c, m, checar_z=False).items()})
    finally:
        c.fechar(); r.fechar()
