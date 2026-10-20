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
from scara import EIXOS, MovimentoAbortado, Scara, Z_CHAVE

RED = {"j1": 14, "j2": 12}       # redução das juntas
PASSO_Z = 8.0                    # mm por volta do fuso
DEGRAUS = (300, 600, 900)        # rpm no motor
CURSO = {"j1": (-60.0, 60.0), "j2": (-60.0, 100.0), "z": (-90.0, 40.0)}   # longe dos extremos (cabos)
REF = (0.0, 80.0, -40.0)         # pose em que a câmera confere a ponta
LENTO = ({"j1": 30.0, "j2": 40.0}, {"j1": 60.0, "j2": 60.0})
LIMITE_GRAUS = 0.5               # perda além da do 1º degrau (base: folga + ruído da câmera ~0,3°)
PASSO_GANHO = 3.0                # ° de junta para medir quantos px a ponta anda por grau
LIMITE_Z_MM = 1.0
VAI_VOLTA = 5                    # ciclos por degrau: uma perda pequena por ciclo cresce acima do ruído (~3 px)
N_FOTOS = 5                      # mediana da ponta em cada conferência
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


XADREZ = (5, 6)                  # cantos internos visíveis do tabuleiro da mesa (os cabos tapam o resto)


def cantos_xadrez(f):
    """cantos internos do tabuleiro verde/marrom (px) ou None"""
    m = cv2.inRange(cv2.cvtColor(f, cv2.COLOR_BGR2HSV), (40, 60, 60), (90, 255, 255))
    g = 255 - cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    ok, c = cv2.findChessboardCornersSB(g, XADREZ, flags=cv2.CALIB_CB_EXHAUSTIVE)
    return c.reshape(-1, 2) if ok else None


def mov_camera(f0, f1):
    """transformação 2x3 da câmera entre duas fotos, pelos cantos do tabuleiro parado na mesa.
    (O fundo inteiro não serve: a tela do notebook rolando arrasta a estimativa.)"""
    c0, c1 = cantos_xadrez(f0), cantos_xadrez(f1)
    if c0 is None or c1 is None:
        raise RuntimeError("tabuleiro não encontrado: sem ele não dá para saber se a câmera se mexeu")
    if np.mean(np.hypot(*(c1[::-1] - c0).T)) < np.mean(np.hypot(*(c1 - c0).T)):
        c1 = c1[::-1]                              # o detector pode numerar a partir do canto oposto
    M, _ = cv2.estimateAffinePartial2D(c0, c1, method=cv2.LMEDS)
    return M


def aplica(M, p):
    return tuple(M[:, :2] @ np.asarray(p, float) + M[:, 2])


def ponta_mediana(fs, esperado=None):
    """mediana da ponta em várias fotos (o detector varia ~3 px de uma foto para outra)"""
    ps = [p for p in (ponta_precisa(f, esperado=esperado) for f in fs) if p is not None]
    return tuple(np.median(ps, axis=0)) if ps else None


class Demo:
    def __init__(self, acel_fator=1.0):
        self.acel_fator = acel_fator
        self.r = Scara(); self.c = Cam()
        for p in ("braco", "z"):
            self.r.energizar(p)
        fs = self.fotos_na_ref()
        self.ref_f = fs[0]
        self.ref_px = ponta_mediana(fs)
        if self.ref_px is None:
            raise RuntimeError("ponta não encontrada na pose de referência")
        self.g = {k: self.ganho(k) for k in RED}
        print("referência da ponta:", self.ref_px, "px/°:", {k: np.round(v, 2).tolist() for k, v in self.g.items()})

    def fotos_na_ref(self, n=N_FOTOS):
        self.r.ir("z", REF[2])
        self.r.ir_juntas(REF[0] - 10, REF[1] - 10, *LENTO)   # chega sempre pelo mesmo lado (folga)
        self.r.ir_juntas(REF[0], REF[1], *LENTO)
        time.sleep(0.8)
        return [self.c.foto(descarta=2) for _ in range(n)]

    def ganho(self, eixo):
        """px que a ponta anda na imagem por grau da junta, na pose de referência"""
        q = {"j1": REF[0], "j2": REF[1]}; q[eixo] += PASSO_GANHO
        self.r.ir_juntas(q["j1"], q["j2"], *LENTO); time.sleep(0.8)
        p = ponta_mediana([self.c.foto(descarta=2) for _ in range(N_FOTOS)], esperado=self.ref_px)
        self.fotos_na_ref(n=0)
        return (np.subtract(p, self.ref_px)) / PASSO_GANHO

    def junta(self, eixo, rpm, n=VAI_VOLTA):
        a, b = CURSO[eixo]
        v = vel(eixo, rpm)
        a_ = acel(v, b - a) * self.acel_fator
        vmax = {"j1": v, "j2": v}; amax = {"j1": a_, "j2": a_}
        fixo = {"j1": REF[0], "j2": REF[1]}
        self.r.ir_juntas(**{**fixo, eixo: a}, vmax=LENTO[0], amax=LENTO[1])
        t0 = time.time()
        for _ in range(n):
            T1 = self.r.ir_juntas(**{**fixo, eixo: b}, vmax=vmax, amax=amax)
            T2 = self.r.ir_juntas(**{**fixo, eixo: a}, vmax=vmax, amax=amax)
        print("  %s: %d vai-e-volta de %.0f° em %.1f s (%.2f s por trecho, %.0f °/s, %.0f °/s²)"
              % (eixo, n, b - a, time.time() - t0, (T1 + T2) / 2, v, a_))

    def z(self, rpm, n=VAI_VOLTA):
        a, b = CURSO["z"]
        f = vel("z", rpm) / EIXOS["z"]["v"]
        self.r.ir("z", a)
        for _ in range(n):
            self.r.ir("z", b, fator=f); self.r.ir("z", a, fator=f)

    def erro_juntas(self, eixo):
        """(px, graus perdidos, px que a câmera andou), já descontando o movimento da câmera"""
        fs = self.fotos_na_ref()
        M = None
        for f in fs:                         # alguém passando na frente do tabuleiro numa foto não derruba o teste
            try:
                M = mov_camera(self.ref_f, f); break
            except RuntimeError:
                continue
        if M is None:
            raise RuntimeError("tabuleiro não encontrado em nenhuma das %d fotos" % len(fs))
        esp = aplica(M, self.ref_px)
        p = ponta_mediana(fs, esperado=esp)
        if p is None:                        # perdeu muito: o hexágono mais próximo do previsto, como estimativa
            h = acha_ponta(fs[0], perto=esp)
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

    def teste(self, eixos=("j1", "j2", "z"), degraus=DEGRAUS):
        seguro = {}
        for eixo in eixos:
            if eixo == "z":
                print("Z referenciado no fim de curso: %+.2f mm do que a placa achava" % self.erro_z())
            base = None
            for rpm in degraus:
                print("%s a %d rpm" % (eixo, rpm))
                if eixo == "z":
                    try:
                        self.z(rpm); bateu = ""
                    except MovimentoAbortado as ex:      # perdeu tanto que chegou num fim de curso
                        bateu = "  (%s)" % ex
                    e = self.erro_z(); ok = abs(e) <= LIMITE_Z_MM and not bateu
                    print("  Z: fim de curso a %+.2f mm do esperado%s" % (e, bateu))
                else:
                    self.junta(eixo, rpm); e, graus, cam = self.erro_juntas(eixo)
                    base = graus if base is None else base
                    ok = abs(graus - base) <= LIMITE_GRAUS
                    print("  ponta a %.1f px da referência: %s em %+.2f° (%+.2f° além da base)%s" % (
                        e, eixo, graus, graus - base, "  (câmera andou %.0f px, descontado)" % cam if cam > 3 else ""))
                if not ok:
                    print("  PERDEU PASSO: %s fica em %s rpm" % (eixo, seguro.get(eixo, "<%d" % degraus[0])))
                    if eixo != "z":              # a placa passa a saber onde a junta está de verdade
                        self.r.definir(eixo, self.r.posicao(eixo) + graus - base)
                        print("  %s corrigida em %+.2f°" % (eixo, graus - base))
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
    ap.add_argument("--degraus", default=",".join(map(str, DEGRAUS)), help="teste: rpm de cada degrau")
    ap.add_argument("--acel-fator", type=float, default=1.0, help="multiplica a aceleração das juntas")
    a = ap.parse_args()
    d = Demo(a.acel_fator)
    try:
        if a.modo == "teste":
            print("rpm seguras:", d.teste(a.eixos.split(","), [float(v) for v in a.degraus.split(",")]))
        else:
            d.show(a.rpm, a.voltas)
    except BaseException:
        d.r.parar(); raise
    finally:
        d.fechar()
