"""Coleta a grade de calibração: leva a ponta a várias poses (J1, J2) em 2 alturas e anota o pixel dela.

Saída no formato do calibrar.py (lista de {j1, j2, z, px}); px = None quando a ponta não foi achada.
As poses saem de uma previsão grosseira (vista de cima, sem paralaxe): eixo do J1 na imagem, px/mm e
direção do J1 = 0 na imagem, medidos girando o J1 (medir_rot.py). Só entram as que caem dentro da imagem.
"""
import argparse
import json
import math
import time

W, H = 1920, 1080
L1, L2 = 300.0, 200.0
VEL = {"j1": 15.0, "j2": 20.0}    # °/s e °/s²: devagar, o braço passa por toda a mesa
ACEL = {"j1": 30.0, "j2": 30.0}
DIST_MAX_PX = 200                 # achado longe disso da previsão = outra coisa azul na imagem


def sequencia(poses, zs):
    """(j1, j2, z) para cada pose nas alturas zs, invertendo a ordem do Z a cada pose (menos subida/descida)"""
    out = []
    for i, (j1, j2) in enumerate(poses):
        for z in (zs if i % 2 == 0 else zs[::-1]):
            out.append((j1, j2, z))
    return out


def na_imagem(px, margem=150):
    return margem <= px[0] <= W - margem and margem <= px[1] <= H - margem


def previsto(j1, j2, centro, escala, ang0, o2):
    """pixel aproximado da ponta: ângulo anti-horário no robô = ângulo decrescente na imagem (y para baixo)"""
    a = math.radians(j1); b = math.radians(j1 + j2 + o2)
    x, y = L1 * math.cos(a) + L2 * math.cos(b), L1 * math.sin(a) + L2 * math.sin(b)
    r, t = math.hypot(x, y) * escala, math.radians(ang0) - math.atan2(y, x)
    return centro[0] + r * math.cos(t), centro[1] + r * math.sin(t)


def faixa(s):
    a, b, p = (float(v) for v in s.split(":"))
    n = int(math.floor((b - a) / p + 1e-9))
    return [a + i * p for i in range(n + 1)]


def coletar(seq, prev, saida):
    from cam import Cam
    from ponta import ponta_precisa
    from scara import Scara
    r = Scara(); c = Cam(); dados = []
    try:
        for i, (j1, j2, z) in enumerate(seq):
            if not dados or (dados[-1]["j1"], dados[-1]["j2"]) != (j1, j2):
                r.ir("z", max(zz for _, _, zz in seq))          # troca de pose sempre no Z mais alto
                r.ir_juntas(j1, j2, vmax=VEL, amax=ACEL)
            r.ir("z", z); time.sleep(0.3)
            p = ponta_precisa(c.foto())
            if p and math.dist(p, prev[(j1, j2)]) > DIST_MAX_PX:
                print("descartado", p, "previsto", prev[(j1, j2)])
                p = None
            dados.append({"j1": j1, "j2": j2, "z": z, "px": [round(p[0], 1), round(p[1], 1)] if p else None})
            print("%d/%d" % (i + 1, len(seq)), dados[-1])
            json.dump(dados, open(saida, "w"), indent=1)          # a cada ponto: uma queda não perde a coleta
    except BaseException:
        r.parar(); raise
    finally:
        c.fechar(); r.fechar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--centro", default="932,522", help="eixo do J1 na imagem (px)")
    ap.add_argument("--escala", type=float, default=1.97, help="px/mm")
    ap.add_argument("--ang0", type=float, default=-0.28, help="direção do J1 = 0 na imagem (°)")
    ap.add_argument("--o2", type=float, default=-22.73)
    ap.add_argument("--j1", default="-120:120:20")
    ap.add_argument("--j2", default="-100:130:30")
    ap.add_argument("--z", default="-40,10")
    ap.add_argument("--saida", default="dados_grade.json")
    ap.add_argument("--simular", action="store_true", help="só lista as poses")
    a = ap.parse_args()
    centro = tuple(float(v) for v in a.centro.split(","))
    prev, poses = {}, []
    for k, j1 in enumerate(faixa(a.j1)):
        j2s = faixa(a.j2)
        for j2 in (j2s if k % 2 == 0 else j2s[::-1]):             # serpente: J2 vai e volta
            p = previsto(j1, j2, centro, a.escala, a.ang0, a.o2)
            if na_imagem(p):
                prev[(j1, j2)] = p; poses.append((j1, j2))
    seq = sequencia(poses, [float(v) for v in a.z.split(",")])
    print("%d poses, %d pontos" % (len(poses), len(seq)))
    if a.simular:
        for j in poses: print(j, [round(v) for v in prev[j]])
    else:
        coletar(seq, prev, a.saida)
