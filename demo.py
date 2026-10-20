"""Demo de velocidade: sobe a rpm dos motores em degraus e confere pela câmera/fim de curso se perdeu passo.

python demo.py teste [--eixos j2,z]  # J1, J2 e Z a 300 -> 600 -> 900 rpm; para no 1º degrau que perder passo
python demo.py show --rpm 600        # vai e volta J1+J2 e sobe e desce o Z na rpm escolhida (a que passou no teste)
"""
import argparse
import math
import time

import cv2
import numpy as np

from cam import Cam
from ponta import acha_ponta, ponta_precisa
from scara import EIXOS, Scara, Z_CHAVE

RED = {"j1": 14, "j2": 12}       # redução das juntas
PASSO_Z = 8.0                    # mm por volta do fuso
DEGRAUS = (300, 600, 900)        # rpm no motor
CURSO = {"j1": (-60.0, 60.0), "j2": (-60.0, 100.0), "z": (-90.0, 40.0)}   # longe dos extremos (cabos)
REF = (0.0, 80.0, -40.0)         # pose em que a câmera confere a ponta
LENTO = ({"j1": 30.0, "j2": 40.0}, {"j1": 60.0, "j2": 60.0})
LIMITE_PX = 8.0                  # ~4 mm: acima disso a junta perdeu passo
PASSO_GANHO = 3.0                # ° de junta para medir quantos px a ponta anda por grau
LIMITE_Z_MM = 1.0
VAI_VOLTA = 2
SHOW = [(-60.0, -60.0), (60.0, 100.0), (-30.0, 40.0), (45.0, -40.0), (0.0, 80.0)]


def vel(eixo, rpm):
    """rpm no motor -> °/s na junta (J1, J2) ou mm/s (Z)"""
    if eixo == "z":
        return rpm * PASSO_Z / 60
    return rpm * 360 / 60 / RED[eixo]


def acel(v, delta):
    """aceleração que chega em v depois de 1/4 do curso (metade do movimento em velocidade máxima)"""
    return 2 * v * v / abs(delta)


def perda_graus(erro, g):
    """erro da ponta (px) -> graus de junta, pela componente na direção em que a junta move a ponta (g, px/°)"""
    return float(np.dot(erro, g) / np.dot(g, g))


def mov_camera(f0, f1):
    """transformação 2x3 (rotação + translação + escala) do fundo entre duas fotos: a câmera se mexeu?"""
    o = cv2.ORB_create(4000)
    k0, d0 = o.detectAndCompute(cv2.cvtColor(f0, cv2.COLOR_BGR2GRAY), None)
    k1, d1 = o.detectAndCompute(cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY), None)
    mt = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d0, d1)
    p0 = np.float32([k0[m.queryIdx].pt for m in mt]); p1 = np.float32([k1[m.trainIdx].pt for m in mt])
    M, _ = cv2.estimateAffinePartial2D(p0, p1, ransacReprojThreshold=3)
    if M is None:
        raise RuntimeError("não deu para comparar o fundo entre as fotos")
    return M


def aplica(M, p):
    return tuple(M[:, :2] @ np.asarray(p, float) + M[:, 2])


class Demo:
    def __init__(self):
        self.r = Scara(); self.c = Cam()
        for p in ("braco", "z"):
            self.r.energizar(p)
        self.ref_f = self.foto_na_ref()
        self.ref_px = ponta_precisa(self.ref_f)
        if self.ref_px is None:
            raise RuntimeError("ponta não encontrada na pose de referência")
        self.g = {k: self.ganho(k) for k in RED}
        print("referência da ponta:", self.ref_px, "px/°:", {k: np.round(v, 2).tolist() for k, v in self.g.items()})

    def foto_na_ref(self):
        self.r.ir("z", REF[2])
        self.r.ir_juntas(REF[0] - 10, REF[1] - 10, *LENTO)   # chega sempre pelo mesmo lado (folga)
        self.r.ir_juntas(REF[0], REF[1], *LENTO)
        time.sleep(0.5)
        return self.c.foto()

    def ganho(self, eixo):
        """px que a ponta anda na imagem por grau da junta, na pose de referência"""
        q = {"j1": REF[0], "j2": REF[1]}; q[eixo] += PASSO_GANHO
        self.r.ir_juntas(q["j1"], q["j2"], *LENTO); time.sleep(0.5)
        p = ponta_precisa(self.c.foto(), esperado=self.ref_px)
        self.foto_na_ref()
        return (np.subtract(p, self.ref_px)) / PASSO_GANHO

    def junta(self, eixo, rpm, n=VAI_VOLTA):
        a, b = CURSO[eixo]
        v = vel(eixo, rpm)
        vmax = {"j1": v, "j2": v}; amax = {"j1": acel(v, b - a), "j2": acel(v, b - a)}
        fixo = {"j1": REF[0], "j2": REF[1]}
        self.r.ir_juntas(**{**fixo, eixo: a}, vmax=LENTO[0], amax=LENTO[1])
        t0 = time.time()
        for _ in range(n):
            T1 = self.r.ir_juntas(**{**fixo, eixo: b}, vmax=vmax, amax=amax)
            T2 = self.r.ir_juntas(**{**fixo, eixo: a}, vmax=vmax, amax=amax)
        print("  %s: %d vai-e-volta de %.0f° em %.1f s (%.2f s por trecho)" % (eixo, n, b - a, time.time() - t0, (T1 + T2) / 2))

    def z(self, rpm, n=VAI_VOLTA):
        a, b = CURSO["z"]
        f = vel("z", rpm) / EIXOS["z"]["v"]
        self.r.ir("z", a)
        for _ in range(n):
            self.r.ir("z", b, fator=f); self.r.ir("z", a, fator=f)

    def erro_juntas(self, eixo):
        """(px, graus perdidos, px que a câmera andou), já descontando o movimento da câmera"""
        f = self.foto_na_ref()
        M = mov_camera(self.ref_f, f)
        esp = aplica(M, self.ref_px)
        p = ponta_precisa(f, esperado=esp)
        if p is None:                        # perdeu muito: o hexágono mais próximo do previsto, como estimativa
            h = acha_ponta(f, perto=esp)
            if h is None:
                raise RuntimeError("ponta não encontrada: perdeu passo demais para medir pela câmera")
            p = h["c"]
        erro = np.subtract(p, esp)
        g = M[:, :2] @ self.g[eixo]
        return float(np.hypot(*erro)), perda_graus(erro, g), math.dist(esp, self.ref_px)

    def erro_z(self):
        zc = self.r.referenciar_z(vbusca=20.0)
        self.r.definir("z", Z_CHAVE)
        return zc - Z_CHAVE

    def teste(self, eixos=("j1", "j2", "z")):
        seguro = {}
        for eixo in eixos:
            for rpm in DEGRAUS:
                print("%s a %d rpm" % (eixo, rpm))
                if eixo == "z":
                    self.z(rpm); e = self.erro_z(); ok = abs(e) <= LIMITE_Z_MM
                    print("  Z: fim de curso a %+.2f mm do esperado" % e)
                else:
                    self.junta(eixo, rpm); e, graus, cam = self.erro_juntas(eixo); ok = e <= LIMITE_PX
                    print("  ponta a %.1f px da referência: %s perdeu ~%+.2f°%s" % (
                        e, eixo, graus, "  (câmera andou %.0f px, descontado)" % cam if cam > 3 else ""))
                if not ok:
                    print("  PERDEU PASSO: %s fica em %s rpm" % (eixo, seguro.get(eixo, "<%d" % DEGRAUS[0])))
                    if eixo != "z":
                        return seguro    # posição da junta perdida: re-zerar (diagnostico.py) antes de seguir
                    break
                seguro[eixo] = rpm
        return seguro

    def show(self, rpm, voltas):
        vj = {k: vel(k, rpm) for k in RED}
        aj = {k: acel(vj[k], CURSO[k][1] - CURSO[k][0]) for k in RED}
        f = vel("z", rpm) / EIXOS["z"]["v"]
        for _ in range(voltas):
            for j1, j2 in SHOW:
                self.r.ir_juntas(j1, j2, vmax=vj, amax=aj)
                self.r.ir("z", CURSO["z"][0], fator=f); self.r.ir("z", REF[2], fator=f)
        e, graus, cam = self.erro_juntas("j1")
        print("ponta a %.1f px da referência (câmera andou %.0f px, descontado)" % (e, cam))

    def fechar(self):
        self.c.fechar(); self.r.fechar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=("teste", "show"))
    ap.add_argument("--rpm", type=float, default=600)
    ap.add_argument("--voltas", type=int, default=3)
    ap.add_argument("--eixos", default="j1,j2,z", help="teste: eixos testados")
    a = ap.parse_args()
    d = Demo()
    try:
        if a.modo == "teste":
            print("rpm seguras:", d.teste(a.eixos.split(",")))
        else:
            d.show(a.rpm, a.voltas)
    except BaseException:
        d.r.parar(); raise
    finally:
        d.fechar()
