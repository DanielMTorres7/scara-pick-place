"""Demo de velocidade: sobe a rpm dos motores em degraus e confere pela câmera/fim de curso se perdeu passo.

python demo.py teste [--eixos j2,z]  # J1, J2 e Z a 300 -> 600 -> 900 rpm; para no 1º degrau que perder passo
python demo.py show --rpm 900        # poses com J1+J2 e Z, na rpm pedida limitada pelos LIMITES medidos
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


# medido em 2026-10-20 (demo.py teste, 5 ciclos, perda < 0,5° / 0,1 mm): rpm no motor e °/s² (Z: só rpm).
# J2 sozinho aguenta 500 °/s², mas a reação arrasta o J1 (-0,85° em 5 ciclos). Com as duas juntas juntas
# (show, 3 voltas): 150/300 °/s² perdeu 3,45° no J1; 100/200 °/s² perdeu 0,44°.
LIMITES = {"j1": (300, 100.0), "j2": (400, 200.0), "z": (500, None)}


def limita(eixo, rpm, curso):
    """(velocidade, aceleração) da junta para `rpm`, sem passar dos limites medidos"""
    rmax, amax = LIMITES[eixo]
    v = vel(eixo, min(rpm, rmax))
    return v, min(acel(v, curso), amax)


def perdas(erro, g):
    """erro da ponta (px) -> graus perdidos em cada junta: erro = g_j1·Δj1 + g_j2·Δj2"""
    d = np.linalg.solve(np.column_stack([g["j1"], g["j2"]]), np.asarray(erro, float))
    return {"j1": float(d[0]), "j2": float(d[1])}


XADREZ = (5, 6)                  # cantos internos visíveis do tabuleiro da mesa (os cabos tapam o resto)


def cantos_xadrez(f):
    """cantos internos do tabuleiro verde/marrom (px) ou None"""
    m = cv2.inRange(cv2.cvtColor(f, cv2.COLOR_BGR2HSV), (40, 60, 60), (90, 255, 255))
    g = 255 - cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    ok, c = cv2.findChessboardCornersSB(g, XADREZ, flags=cv2.CALIB_CB_ACCURACY)   # EXHAUSTIVE é aleatório: falhava ~30%
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
    def __init__(self, acel_fator=1.0, suave=0.0):
        self.acel_fator, self.suave = acel_fator, suave
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

    def junta(self, eixo, rpm, n=VAI_VOLTA, acel_abs=None):
        a, b = CURSO[eixo]
        v = vel(eixo, rpm)
        a_ = acel_abs if acel_abs is not None else acel(v, b - a) * self.acel_fator
        vmax = {"j1": v, "j2": v}; amax = {"j1": a_, "j2": a_}
        fixo = {"j1": REF[0], "j2": REF[1]}
        self.r.ir_juntas(**{**fixo, eixo: a}, vmax=LENTO[0], amax=LENTO[1])
        t0 = time.time()
        for _ in range(n):
            T1 = self.r.ir_juntas(**{**fixo, eixo: b}, vmax=vmax, amax=amax, suave=self.suave)
            T2 = self.r.ir_juntas(**{**fixo, eixo: a}, vmax=vmax, amax=amax, suave=self.suave)
        print("  %s: %d vai-e-volta de %.0f° em %.1f s (%.2f s por trecho, %.0f °/s, %.0f °/s²)"
              % (eixo, n, b - a, time.time() - t0, (T1 + T2) / 2, v, a_))

    def z(self, rpm, n=VAI_VOLTA):
        a, b = CURSO["z"]
        f = vel("z", rpm) / EIXOS["z"]["v"]
        self.r.ir("z", a)
        for _ in range(n):
            self.r.ir("z", b, fator=f); self.r.ir("z", a, fator=f)

    def erro_juntas(self):
        """(px, {junta: graus perdidos}, px que a câmera andou), já descontando o movimento da câmera"""
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
        g = {k: M[:, :2] @ v for k, v in self.g.items()}
        return float(np.hypot(*erro)), perdas(erro, g), math.dist(esp, self.ref_px)

    def erro_z(self):
        zc = self.r.referenciar_z(vbusca=20.0)
        self.r.definir("z", Z_CHAVE)
        return zc - Z_CHAVE

    def teste(self, eixos=("j1", "j2", "z"), degraus=DEGRAUS, acels=None):
        """sobe a rpm em `degraus`; com `acels`, fica na rpm de degraus[0] e sobe a aceleração (°/s²)"""
        etapas = [(rpm, None) for rpm in degraus] if not acels else [(degraus[0], a) for a in acels]
        seguro = {}
        for eixo in eixos:
            if eixo == "z":
                print("Z referenciado no fim de curso: %+.2f mm do que a placa achava" % self.erro_z())
            base = None
            for rpm, a_ in etapas:
                print("%s a %d rpm%s" % (eixo, rpm, "" if a_ is None else ", %.0f °/s²" % a_))
                if eixo == "z":
                    try:
                        self.z(rpm); bateu = ""
                    except MovimentoAbortado as ex:      # perdeu tanto que chegou num fim de curso
                        bateu = "  (%s)" % ex
                    e = self.erro_z(); ok = abs(e) <= LIMITE_Z_MM and not bateu
                    print("  Z: fim de curso a %+.2f mm do esperado%s" % (e, bateu))
                else:
                    self.junta(eixo, rpm, acel_abs=a_); e, d, cam = self.erro_juntas()
                    base = d if base is None else base
                    alem = {k: d[k] - base[k] for k in d}      # a outra junta também conta: a reação pode arrastá-la
                    ok = all(abs(v) <= LIMITE_GRAUS for v in alem.values())
                    print("  ponta a %.1f px da referência; além da base: %s%s" % (
                        e, ", ".join("%s %+.2f°" % kv for kv in alem.items()),
                        "  (câmera andou %.0f px, descontado)" % cam if cam > 3 else ""))
                if not ok:
                    print("  PERDEU PASSO: %s fica em %s" % (eixo, seguro.get(eixo, "abaixo do 1º degrau")))
                    if eixo != "z":              # a placa passa a saber onde as juntas estão de verdade
                        self.corrige(alem)
                    break
                seguro[eixo] = rpm if a_ is None else "%d rpm a %.0f °/s²" % (rpm, a_)
        return seguro

    def show(self, rpm, voltas):
        lim = {k: limita(k, rpm, CURSO[k][1] - CURSO[k][0]) for k in RED}
        vj = {k: v for k, (v, _) in lim.items()}; aj = {k: a * self.acel_fator for k, (_, a) in lim.items()}
        f = vel("z", min(rpm, LIMITES["z"][0])) / EIXOS["z"]["v"]
        print("show: %s, Z %.0f mm/s" % (", ".join("%s %.0f °/s %.0f °/s²" % (k, vj[k], aj[k]) for k in RED), f * EIXOS["z"]["v"]))
        for _ in range(voltas):
            for j1, j2 in SHOW:
                self.r.ir_juntas(j1, j2, vmax=vj, amax=aj, suave=self.suave)
                self.r.ir("z", CURSO["z"][0], fator=f); self.r.ir("z", REF[2], fator=f)
        e, d, cam = self.erro_juntas()
        print("ponta a %.1f px da referência: %s (câmera andou %.0f px, descontado)" % (
            e, ", ".join("%s %+.2f°" % kv for kv in d.items()), cam))
        if any(abs(v) > LIMITE_GRAUS for v in d.values()):
            self.corrige(d)
        return d

    def corrige(self, d):
        for k, v in d.items():
            self.r.definir(k, self.r.posicao(k) + v)
        print("  corrigido: %s" % ", ".join("%s %+.2f°" % kv for kv in d.items()))

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
    ap.add_argument("--acels", default="", help="teste: acelerações (°/s²) na rpm de --degraus[0]")
    ap.add_argument("--suave", type=float, default=0.0, help="curva S: 0 = trapézio, 1 = S completa")
    a = ap.parse_args()
    d = Demo(a.acel_fator, a.suave)
    try:
        if a.modo == "teste":
            print("seguro:", d.teste(a.eixos.split(","), [float(v) for v in a.degraus.split(",")],
                                     [float(v) for v in a.acels.split(",")] if a.acels else None))
        else:
            d.show(a.rpm, a.voltas)
    except BaseException:
        d.r.parar(); raise
    finally:
        d.fechar()
