"""Demo de velocidade: sobe a rpm dos motores em degraus e confere pela câmera/fim de curso se perdeu passo.

python demo.py teste                 # J1, J2 e Z a 300 -> 600 -> 900 rpm; para no 1º degrau que perder passo
python demo.py show --rpm 600        # vai e volta J1+J2 e sobe e desce o Z na rpm escolhida (a que passou no teste)
"""
import argparse
import math
import time

from cam import Cam
from ponta import ponta_precisa
from scara import EIXOS, Scara, Z_CHAVE

RED = {"j1": 14, "j2": 12}       # redução das juntas
PASSO_Z = 8.0                    # mm por volta do fuso
DEGRAUS = (300, 600, 900)        # rpm no motor
CURSO = {"j1": (-60.0, 60.0), "j2": (-60.0, 100.0), "z": (-90.0, 40.0)}   # longe dos extremos (cabos)
REF = (0.0, 80.0, -40.0)         # pose em que a câmera confere a ponta
LENTO = ({"j1": 30.0, "j2": 40.0}, {"j1": 60.0, "j2": 60.0})
LIMITE_PX = 8.0                  # ~4 mm: acima disso a junta perdeu passo
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


class Demo:
    def __init__(self):
        self.r = Scara(); self.c = Cam()
        for p in ("braco", "z"):
            self.r.energizar(p)
        self.ref_px = self.ponta_na_ref()
        print("referência da ponta:", self.ref_px)

    def ponta_na_ref(self, esperado=None):
        self.r.ir("z", REF[2])
        self.r.ir_juntas(REF[0], REF[1], *LENTO)
        time.sleep(0.5)
        p = ponta_precisa(self.c.foto(), esperado=esperado)
        if p is None:
            raise RuntimeError("ponta não encontrada na pose de referência")
        return p

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

    def erro_juntas(self):
        p = self.ponta_na_ref(esperado=self.ref_px)
        return math.dist(p, self.ref_px)

    def erro_z(self):
        zc = self.r.referenciar_z(vbusca=20.0)
        self.r.definir("z", Z_CHAVE)
        return zc - Z_CHAVE

    def teste(self):
        seguro = {}
        for eixo in ("j1", "j2", "z"):
            for rpm in DEGRAUS:
                print("%s a %d rpm" % (eixo, rpm))
                if eixo == "z":
                    self.z(rpm); e = self.erro_z(); ok = abs(e) <= LIMITE_Z_MM
                    print("  Z: fim de curso a %+.2f mm do esperado" % e)
                else:
                    self.junta(eixo, rpm); e = self.erro_juntas(); ok = e <= LIMITE_PX
                    print("  ponta a %.1f px da referência" % e)
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
        print("ponta a %.1f px da referência" % self.erro_juntas())

    def fechar(self):
        self.c.fechar(); self.r.fechar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=("teste", "show"))
    ap.add_argument("--rpm", type=float, default=600)
    ap.add_argument("--voltas", type=int, default=3)
    a = ap.parse_args()
    d = Demo()
    try:
        if a.modo == "teste":
            print("rpm seguras:", d.teste())
        else:
            d.show(a.rpm, a.voltas)
    except BaseException:
        d.r.parar(); raise
    finally:
        d.fechar()
