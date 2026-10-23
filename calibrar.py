"""Ajusta o modelo câmera + braço a partir da grade (dados_grade.json).

Robô: x,y em mm no referencial da base (x = direção do braço com J1 = 0, ângulos anti-horários vistos de cima),
z = posição do eixo Z (mm). Ponta (centro do rolamento = eixo da ventosa) = FK(j1, j2 + o2).
Câmera: projeção 3x4 P (pinhole), pixel ~ P [x, y, z, 1].
"""
import json, math
import numpy as np
from scipy.optimize import least_squares

L1, L2 = 300.0, 200.0

def fk(j1, j2, o2):
    a = np.radians(j1); b = np.radians(j1 + j2 + o2)
    return L1 * np.cos(a) + L2 * np.cos(b), L1 * np.sin(a) + L2 * np.sin(b)

def projeta(P, x, y, z):
    X = np.stack([x, y, z, np.ones_like(x)])
    u = P @ X
    return u[:2] / u[2]

def dlt(X, uv):
    A = []
    for (x, y, z), (u, v) in zip(X, uv):
        A.append([x, y, z, 1, 0, 0, 0, 0, -u * x, -u * y, -u * z, -u])
        A.append([0, 0, 0, 0, x, y, z, 1, -v * x, -v * y, -v * z, -v])
    _, _, vt = np.linalg.svd(np.array(A))
    P = vt[-1].reshape(3, 4)
    return P / P[2, 3]

def ajustar(dados):
    d = [x for x in dados if x["px"]]
    j1 = np.array([x["j1"] for x in d], float); j2 = np.array([x["j2"] for x in d], float)
    z = np.array([x["z"] for x in d], float); uv = np.array([x["px"] for x in d], float)

    def res(p):
        o2 = p[0]; P = np.append(p[1:], 1.0).reshape(3, 4)
        x, y = fk(j1, j2, o2)
        return (projeta(P, x, y, z).T - uv).ravel()

    melhor = None
    for o2 in np.arange(-180, 180, 10):           # o zero do J2 é desconhecido: varre e refina
        x, y = fk(j1, j2, o2)
        P0 = dlt(np.c_[x, y, z], uv)
        r = least_squares(res, np.r_[o2, P0.ravel()[:11]], loss="soft_l1", f_scale=3.0)
        if melhor is None or r.cost < melhor.cost:
            melhor = r
    p = melhor.x
    e = res(p).reshape(-1, 2); err = np.hypot(e[:, 0], e[:, 1])
    return {"o2": float(((p[0] + 180) % 360) - 180), "P": np.append(p[1:], 1.0).reshape(3, 4).tolist(),
            "L1": L1, "L2": L2}, err, d

if __name__ == "__main__":
    import sys
    # uso: python calibrar.py [dados_grade.json] [calibracao_braco.json]
    cal, err, d = ajustar(json.load(open(sys.argv[1] if len(sys.argv) > 1 else "dados_grade.json")))
    for x, e in zip(d, err):
        print(x["j1"], x["j2"], x["z"], x["px"], "erro %.1f px" % e)
    print("erro mediano %.2f px, max %.1f px" % (np.median(err), err.max()))
    print("o2 (J2 com braço esticado = -o2) = %.2f" % cal["o2"])
    P = np.array(cal["P"])
    # centro da câmera no referencial do robô
    C = -np.linalg.solve(P[:, :3], P[:, 3]); print("centro da câmera (x,y,z) mm:", np.round(C, 1))
    json.dump(cal, open(sys.argv[2] if len(sys.argv) > 2 else "calibracao_braco.json", "w"), indent=1)
