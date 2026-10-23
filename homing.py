"""Homing do J1 pela visão. O J1 não tem fim de curso e, desenergizado, pode ser girado sem a placa saber.

Uma vez por execução: o braço passa no alto por POSES em que as câmeras veem a ponta; cada câmera em cada pose dá
uma medida do desvio entre o J1 real e o da placa. Só corrige com pelo menos duas medidas que concordem (mediana):
em 23/10 uma medida só (+8,24°, detecção errada) foi aplicada e o J1 bateu na parede. O J2 fica fixo: a chave dele o garante (~0,3°),
e soltá-lo no ajuste deixa o viés da calibração da XWF contaminar o J1 (medido em 23/10).
"""
import time

import numpy as np
from scipy.optimize import least_squares

from cameras import FAIXA_PONTA
from ponta import FAIXA, _anel, hexagonos

# ponta longe da borda nas duas câmeras (a 2ª só na C920) em Z, mesmo com o J1 alguns graus fora; r = 300 e 412 mm
POSES = ((-35.0, -110.0), (-105.0, 70.0))
Z = 75.0                 # no alto: passa por cima da coletora e das caixas
MAX_DESVIO = 20.0        # °: mais que isso é detecção errada (ou o braço foi muito mexido)
MAX_DISCORDA = 1.5       # °: poses que discordam mais que isso = alguma detecção errada
MIN_CORRIGE = 0.2        # °: abaixo disso não mexe na placa
BUSCA_PX = 250           # até onde procurar a ponta em volta da previsão (~15-20° de J1)
RAIO_ANEL_PX = 90        # busca do anel do rolamento em volta da previsão (J1 a poucos graus)


class HomingFalhou(RuntimeError):
    """não deu para achar o J1 pela visão: não mover às cegas"""


def estimar_desvio(obs, ms, pose, z):
    """obs {câmera: (u, v)} da ponta com o braço em `pose` -> (d1, resíduo px): J1 real = pose[0] + d1"""
    if not obs:
        raise HomingFalhou("ponta não encontrada em nenhuma câmera")

    def res(p):
        out = []
        for n, (u, v) in obs.items():
            pu, pv = ms[n].robo_para_pixel(*ms[n].fk(pose[0] + p[0], pose[1]), z)[:2]
            out += [pu - u, pv - v]
        return out
    r = least_squares(res, [0.0])
    return float(r.x[0]), float(np.sqrt(np.mean(np.square(res(r.x)))))


def conferir(desvios):
    """medidas do desvio do J1 (uma por câmera em cada pose) -> desvio final (mediana); levanta se houver uma medida
    só, se for absurdo ou se as medidas discordarem"""
    if len(desvios) < 2:
        raise HomingFalhou("só uma medida do J1 (%s°): sem como conferir, o homing não corrige"
                           % ", ".join("%+.2f" % d for d in desvios))
    d1 = float(np.median(desvios))
    if abs(d1) > MAX_DESVIO:
        raise HomingFalhou("J1 %.1f° fora do esperado: detecção errada ou braço muito mexido (confira à mão)" % d1)
    if max(desvios) - min(desvios) > MAX_DISCORDA and len(desvios) >= 3:
        # uma câmera numa pose pode sair da calibração (23/10: XWF +1,8° fora das outras três): descarta só a
        # mais longe da mediana se as restantes (pelo menos 2) concordarem
        fora = max(desvios, key=lambda d: abs(d - d1))
        resto = list(desvios)
        resto.remove(fora)
        if max(resto) - min(resto) <= MAX_DISCORDA:
            print("homing J1: medida %+.2f° descartada (fora das outras: %s)" % (fora, ", ".join("%+.2f" % d for d in resto)))
            return float(np.median(resto))
    if max(desvios) - min(desvios) > MAX_DISCORDA:
        raise HomingFalhou("as medidas discordam no desvio do J1 (%s°): alguma detecção errada"
                           % ", ".join("%+.2f" % d for d in desvios))
    return d1


def ponta_ampla(f, esperado, faixa):
    """ponta só com o anel do rolamento (23/10: o logo azul de uma caixa embaixo da pose, com miolo branco, passou por
    ponta e o J1 saiu ~15° errado). Primeiro o anel em volta da previsão (cobre o hexágono grudado no azul da caixa,
    que vira mancha grande demais); senão os candidatos azuis até BUSCA_PX, do mais perto, com anel no centro."""
    a = _anel(f, int(esperado[0]), int(esperado[1]), RAIO_ANEL_PX)
    if a is not None:
        return a
    hs, _ = hexagonos(f, faixa)
    for h in sorted(hs, key=lambda h: np.hypot(h["c"][0] - esperado[0], h["c"][1] - esperado[1])):
        if np.hypot(h["c"][0] - esperado[0], h["c"][1] - esperado[1]) > BUSCA_PX:
            break
        if not (h["circ"] > 0.35 and 40 < h["r"] < 95):
            continue
        a = _anel(f, int(h["c"][0]), int(h["c"][1]), 40)
        if a is not None and np.hypot(a[0] - h["c"][0], a[1] - h["c"][1]) < 15:
            return a
    return None


def _medir(r, cams, ms, vmax=None, amax=None):
    """passa pelas POSES no alto: (desvios do J1, câmera de cada um), uma medida por câmera que achou a ponta"""
    if r.posicao("z") < Z:
        r.ir("z", Z)
    desvios, vistas = [], []
    for pose in POSES:
        r.ir_juntas(*pose, vmax=vmax, amax=amax)
        time.sleep(0.2)
        obs = {}
        for n, cam in cams.items():
            esp = ms[n].robo_para_pixel(*ms[n].fk(*pose), Z)[:2]
            p = ponta_ampla(cam.foto(), esp, FAIXA_PONTA.get(n, FAIXA))
            if p is not None:
                obs[n] = p
        for n, p in obs.items():            # cada câmera conta como uma medida independente
            desvios.append(estimar_desvio({n: p}, ms, pose, Z)[0])
            vistas.append(n)
    return desvios, vistas


def homing_j1(r, cams, ms, vmax=None, amax=None):
    """mede o desvio do J1 pelas câmeras e corrige a placa; devolve o desvio (°). Com o J1 alinhado à mão só
    "mais ou menos" (23/10: ~15°) uma pose só acha a ponta: aplica essa medida provisória e mede de novo, que com o J1
    perto do certo as outras poses acham a ponta e confirmam; sem confirmar, desfaz e levanta."""
    desvios, vistas = _medir(r, cams, ms, vmax, amax)
    if not desvios:
        raise HomingFalhou("ponta não encontrada em nenhuma pose do homing")
    d0 = 0.0
    if len(desvios) == 1 and abs(desvios[0]) <= MAX_DESVIO:
        d0 = desvios[0]
        j1 = r.posicao("j1")
        r.definir("j1", j1 + d0)
        print("homing J1: uma medida só (%+.2f°, %s): corrigido provisoriamente, medindo de novo" % (d0, vistas[0]))
        try:
            desvios, vistas = _medir(r, cams, ms, vmax, amax)
            if not desvios:
                raise HomingFalhou("ponta não encontrada na segunda passada do homing")
            conferir(desvios)
        except HomingFalhou:
            r.definir("j1", r.posicao("j1") - d0)        # a correção provisória não fica
            raise
    d1 = conferir(desvios)
    if abs(d1) >= MIN_CORRIGE:
        r.definir("j1", r.posicao("j1") + d1)
    print("homing J1: desvio %+.2f°%s (medidas: %s; câmeras %s)" % (
        d0 + d1, "" if abs(d1) >= MIN_CORRIGE else ", não corrigido", ", ".join("%+.2f" % d for d in desvios),
        ", ".join(vistas)))
    return d0 + d1
