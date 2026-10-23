"""Duas câmeras de cima (C920 e XWF-1080P, giradas 180° uma da outra), cada uma com a sua calibração.

Juntas veem a mesa toda: cada caixa é convertida para o referencial do robô pela câmera que a viu e as detecções
da mesma caixa nas duas câmeras viram uma só. A ponta é conferida pela câmera que a vê mais longe da borda.
"""
import math
import os

from caixa import acha_caixas
from modelo import ALTURA_CAIXA, Modelo
from ponta import FAIXA, ponta_precisa
from scara import ACEL_SEGURA, VEL_SEGURA

AQUI = os.path.dirname(os.path.abspath(__file__))
# nome (trecho do nome do dispositivo), calibração e pose (J1, J2) em que o braço fica fora da vista dela na foto
CAMERAS = (
    ("C920", os.path.join(AQUI, "calibracao_braco.json"), (0.0, 0.0)),
    ("XWF", os.path.join(AQUI, "calibracao_XWF.json"), (-125.0, 0.0)),
)
# HSV do hexágono azul da ponta em cada câmera (hoje a mesma nas duas: ver ponta.FAIXA)
FAIXA_PONTA = {"C920": FAIXA, "XWF": FAIXA}
MESMA_CAIXA_MM = 40.0
MAX_PX = 70               # ponta achada mais longe que isso da previsão = outra coisa azul (o erro inicial chega a ~25 mm)
W, H = 1920, 1080


def juntar_caixas(obs, dist=MESMA_CAIXA_MM):
    """obs: [{"cam", "xy", ...}] -> [{"xy" (média), "cams", "obs"}]; duas detecções da mesma câmera nunca se juntam"""
    grupos = []
    for o in obs:
        livres = [g for g in grupos if o["cam"] not in g["cams"]]
        perto = min(livres, key=lambda g: math.dist(g["xy"], o["xy"]), default=None)
        if perto is not None and math.dist(perto["xy"], o["xy"]) <= dist:
            perto["obs"].append(o)
            perto["cams"].append(o["cam"])
            n = len(perto["obs"])
            perto["xy"] = tuple(sum(x["xy"][i] for x in perto["obs"]) / n for i in (0, 1))
        else:
            grupos.append({"xy": tuple(o["xy"]), "cams": [o["cam"]], "obs": [o]})
    return grupos


def folga_borda(px, w, h):
    """distância (px) do ponto até a borda mais próxima da imagem; negativa fora dela"""
    return min(px[0], px[1], w - px[0], h - px[1])


def modelos():
    return {nome: Modelo(cal) for nome, cal, _ in CAMERAS}


def fotos(r, cams, prefixo="fotos/mesa"):
    """uma foto por câmera, cada uma com o braço na pose fora da vista dela: {nome: (foto, (j1, j2), z)}"""
    out = {}
    for nome, _, pose in CAMERAS:
        r.ir_juntas(*pose, vmax=VEL_SEGURA, amax=ACEL_SEGURA)
        out[nome] = (cams[nome].foto("%s_%s.jpg" % (prefixo, nome)), pose, r.posicao("z"))
    return out


def braco_px(m, pose, z):
    """pixels previstos do cotovelo e da ponta (os hexágonos azuis do braço)"""
    return [m.robo_para_pixel(*m.cotovelo(pose[0]), z)[:2], m.robo_para_pixel(*m.fk(*pose), z)[:2]]


def ver_caixas(fs, ms):
    """caixas de remédio das fotos de todas as câmeras, juntas no referencial do robô"""
    obs = []
    for nome, (f, pose, z) in fs.items():
        m = ms[nome]
        for k in acha_caixas(f, braco_px=braco_px(m, pose, z)):
            obs.append({"cam": nome, "px": k["centro"], "cantos": k["cantos"],
                        "xy": m.caixa_para_robo(*k["centro"], ALTURA_CAIXA)})
    return juntar_caixas(obs)


def ponta_xy(cams, ms, xy, z):
    """(câmera, x, y) da ponta, esperada em `xy` (mm) na altura z, vista pela câmera em que ela fica mais longe da
    borda; None se nenhuma achou. `z` pode ser uma função: é lida logo depois da foto (Z em movimento)."""
    z_agora = z if callable(z) else (lambda: z)
    z0 = z_agora()
    prev = {n: ms[n].robo_para_pixel(*xy, z0) for n in ms}
    for n in sorted(ms, key=lambda n: -folga_borda(prev[n], W, H)):
        if folga_borda(prev[n], W, H) < 60:
            break
        f = cams[n].foto()
        zf = z_agora()
        p = ponta_precisa(f, esperado=prev[n], faixa=FAIXA_PONTA.get(n, FAIXA))
        if p is not None and math.dist(p, prev[n][:2]) <= MAX_PX:
            return (n, *ms[n].pixel_para_robo(p[0], p[1], zf))
    return None
