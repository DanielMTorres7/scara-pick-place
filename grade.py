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
DIST_MAX_MODELO_PX = 80           # idem, prevendo pela calibração atual (erro ~5 px; até ~40 px fora das alturas dela)


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


def le_camera(s):
    """NOME:CX,CY:ESCALA:ANG0 -> previsão grosseira de uma câmera (nome = trecho do nome do dispositivo)"""
    nome, centro, escala, ang0 = s.split(":")
    cx, cy = (float(v) for v in centro.split(","))
    return {"nome": nome, "centro": (cx, cy), "escala": float(escala), "ang0": float(ang0)}


def poses_visiveis(poses, prevs, zs):
    """poses em que pelo menos uma câmera vê a ponta em todas as alturas"""
    return [j for j in poses if any(all(na_imagem(p(*j, z)) for z in zs) for p in prevs)]


def poses_livres(poses, livre):
    """só as poses em que o braço baixo não fica sobre um obstáculo"""
    return [j for j in poses if livre(*j)]


def saida_camera(saida, nome, n_cameras):
    if n_cameras == 1:
        return saida
    base, ext = saida.rsplit(".", 1)
    return "%s_%s.%s" % (base, nome, ext)


def coletar(seq, cams, fator=1.0, r=None, abertas=None):
    """cams: [{"nome", "prev": (j1, j2, z) -> pixel previsto, "saida", "dist_max"}]; uma foto de cada câmera por ponto.
    r/abertas: Scara e câmeras já abertos (calibração pelo servidor de OS): usa esses e não fecha no fim"""
    import ponta
    from cameras import FAIXA_PONTA
    from ponta import FAIXA
    dono = r is None
    if dono:
        from cam import Cam, acha_indice
        from scara import Scara
        r = Scara(fator_vel=min(0.2 * fator, 1.0))
        abertas = [Cam(idx=acha_indice(c["nome"]), nome=c["nome"]) for c in cams]
    dados = [[] for _ in cams]
    vel = {k: v * fator for k, v in VEL.items()}; acel = {k: v * fator for k, v in ACEL.items()}
    try:
        for i, (j1, j2, z) in enumerate(seq):
            if i == 0 or seq[i - 1][:2] != (j1, j2):
                r.ir("z", max(zz for _, _, zz in seq))          # troca de pose sempre no Z mais alto
                r.ir_juntas(j1, j2, vmax=vel, amax=acel)
            r.ir("z", z); time.sleep(0.3)
            for c, cam, d in zip(cams, abertas, dados):
                esp = c["prev"](j1, j2, z)
                faixa = FAIXA_PONTA.get(c["nome"], FAIXA)
                p = ponta.ponta_precisa(cam.foto(), esperado=esp, faixa=faixa) if na_imagem(esp, margem=0) else None
                if p and math.dist(p, esp) > c["dist_max"]:
                    print("%s: descartado" % c["nome"], p, "previsto", esp)
                    p = None
                d.append({"j1": j1, "j2": j2, "z": z, "px": [round(p[0], 1), round(p[1], 1)] if p else None})
                json.dump(d, open(c["saida"], "w"), indent=1)     # a cada ponto: uma queda não perde a coleta
            print("%d/%d" % (i + 1, len(seq)), j1, j2, z, {c["nome"]: d[-1]["px"] for c, d in zip(cams, dados)})
    except BaseException:
        r.parar(); raise
    finally:
        if dono:
            for cam in abertas:
                cam.fechar()
            r.fechar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", action="append", type=le_camera,
                    help="NOME:CX,CY:ESCALA:ANG0, uma por câmera (ex.: C920:1110,746:1.85:90); sem --cam: C920 com "
                         "--centro/--escala/--ang0")
    ap.add_argument("--centro", default="932,522", help="eixo do J1 na imagem (px)")
    ap.add_argument("--escala", type=float, default=1.97, help="px/mm")
    ap.add_argument("--ang0", type=float, default=-0.28, help="direção do J1 = 0 na imagem (°)")
    ap.add_argument("--o2", type=float, default=-22.73)
    ap.add_argument("--j1", default="-120:120:20")
    ap.add_argument("--j2", default="-100:130:30")
    ap.add_argument("--z", default="-40,10")
    ap.add_argument("--saida", default="dados_grade.json", help="com várias câmeras vira dados_grade_<NOME>.json")
    ap.add_argument("--fator", type=float, default=1.0, help="multiplica velocidade e aceleração")
    ap.add_argument("--modelo", action="store_true",
                    help="prevê pela calibração atual de cada câmera (cameras.CAMERAS) em vez de CX,CY:ESCALA:ANG0")
    ap.add_argument("--simular", action="store_true", help="só lista as poses")
    ap.add_argument("--evitar-coletora", action="store_true",
                    help="tira as poses em que o braço baixo ficaria sobre a coletora (coletora.json)")
    a = ap.parse_args()
    zs = [float(v) for v in a.z.split(",")]
    specs = a.cam or [{"nome": "C920", "centro": tuple(float(v) for v in a.centro.split(",")),
                       "escala": a.escala, "ang0": a.ang0}]
    cams = []
    for c in specs:
        if a.modelo:
            from cameras import modelos
            m = modelos()[c["nome"]]
            prev, dist_max = (lambda j1, j2, z, m=m: m.robo_para_pixel(*m.fk(j1, j2), z)), DIST_MAX_MODELO_PX
        else:
            prev, dist_max = (lambda j1, j2, z, c=c: previsto(j1, j2, c["centro"], c["escala"], c["ang0"], a.o2)), \
                DIST_MAX_PX
        cams.append({"nome": c["nome"], "prev": prev, "dist_max": dist_max,
                     "saida": saida_camera(a.saida, c["nome"], len(specs))})
    poses = []
    for k, j1 in enumerate(faixa(a.j1)):
        j2s = faixa(a.j2)
        poses += [(j1, j2) for j2 in (j2s if k % 2 == 0 else j2s[::-1])]   # serpente: J2 vai e volta
    poses = poses_visiveis(poses, [c["prev"] for c in cams], zs)
    if a.evitar_coletora:
        from cameras import modelos
        from pick_place import braco_livre, coletora_mm
        ms = modelos()
        hull = coletora_mm(ms)
        n = len(poses)
        poses = poses_livres(poses, lambda j1, j2: braco_livre(ms["C920"], hull, j1, j2))
        print("%d poses tiradas por ficarem sobre a coletora" % (n - len(poses)))
    seq = sequencia(poses, zs)
    print("%d poses, %d pontos" % (len(poses), len(seq)))
    if a.simular:
        for j in poses:
            print(j, {c["nome"]: [[round(v) for v in c["prev"](*j, z)] for z in zs] for c in cams})
    else:
        coletar(seq, cams, a.fator)
