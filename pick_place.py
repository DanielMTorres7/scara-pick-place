"""Simulação de pick and place: acha as caixas de remédio e a caixa coletora pela câmera; em cada caixa de remédio
desce, "pega", sobe acima da coletora e "solta" dentro dela. A ventosa ainda não está ligada: as caixas não se
movem, só o braço faz o ciclo.

Alturas (acima da mesa) e o Z correspondente: z = altura + Z_TOQUE_MESA (-135).

Uso: python pick_place.py [--nome micpure]     (com --nome, o Gemini lê os nomes e só pega as caixas desse remédio)
"""
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from bomba import Bomba
from caixa import acha_caixas
from cam import Cam
from modelo import ALTURA_CAIXA, Z_TOQUE_MESA, Modelo
from ponta import ponta_precisa
from scara import Scara
from selecao import mesmo_nome

ALTURA_COLETORA = 126.0   # mm (medido)
FOLGA_SOLTA = 10.0        # fundo da caixa de remédio fica 1 cm acima da borda ao soltar
FOLGA_PASSA = 34.0        # caixa pendurada passa 3,4 cm acima da borda
Z_ALTO = Z_TOQUE_MESA + ALTURA_COLETORA + ALTURA_CAIXA + FOLGA_PASSA      # +55: deslocamentos
Z_SOLTA = Z_TOQUE_MESA + ALTURA_COLETORA + ALTURA_CAIXA + FOLGA_SOLTA     # +31: solta dentro da coletora
Z_MIRA = -65.0            # altura em que a câmera confere a ponta em cima da caixa
Z_PEGA = -97.0            # o fim de curso de baixo aciona em ~-98,3 (ventosa ~7 mm acima de uma caixa de 30 mm)
PARQUE = (20.0, -110.0)   # braço recolhido, fora da área das caixas, para a foto
LARGURA_BRACO = 50.0      # mm de folga entre o braço (baixo) e a coletora
PAUSA_VENTOSA = 0.5
# relé da bomba: ligado = ventosa fechada (estado de partida); desliga para pegar, liga de novo para soltar
RELE_REPOUSO, RELE_PEGA = 1, 0


def acha_coletora(f):
    """caixa de MDF (cor de madeira): maior região cor de madeira -> retângulo e polígono (px)"""
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (8, 50, 80), (25, 200, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 50000:
        return None
    r = cv2.minAreaRect(c)
    return {"rect": r, "cantos": cv2.boxPoints(r)}


def obstaculo_mm(m, cantos_px, altura):
    """polígono (mm) ocupado por um objeto de `altura` cujos cantos aparecem em `cantos_px`: fecho do topo e da base"""
    topo = [m.pixel_para_robo(u, v, m.z_do_plano(altura)) for u, v in cantos_px]
    base = [m.pixel_para_robo(u, v, m.z_do_plano(0)) for u, v in cantos_px]
    return topo, cv2.convexHull(np.float32(topo + base))


VISAO = Path(__file__).resolve().parent.parent / "only-vision"


def nomes_gemini(f, caixas):
    """lê o nome de cada caixa com o Gemini (only-vision) e associa à caixa do OpenCV mais próxima"""
    sys.path.insert(0, str(VISAO))
    from dotenv import load_dotenv
    load_dotenv(VISAO / ".env")
    import vision_remedios as vr
    g = vr.AnalisadorGemini(vr.os.getenv("GEMINI_MODEL", "gemini-robotics-er-2-preview"))
    t = time.time()
    lidas, _ = g.detectar(f)
    h, w = f.shape[:2]
    print("Gemini (%s, %.0f s): %d caixas lidas (as de dentro da coletora são ignoradas)" % (g.modelo, time.time() - t, len(lidas)))
    for k in caixas:
        k["nome"] = ""
    for c in lidas:
        y, x = c["centro"]
        p = (x / 1000 * w, y / 1000 * h)
        if not caixas:
            break
        k = min(caixas, key=lambda k: math.dist(k["centro"], p))
        if math.dist(k["centro"], p) < 80:
            k["nome"] = c.get("nome", "")
    return caixas


class PickPlace:
    def __init__(self):
        self.m = Modelo()
        self.r = Scara(fator_vel=1.0)
        self.c = Cam()
        self.obstaculo = None      # polígono da coletora em mm (referencial do robô)
        self.bomba = Bomba()

    def fechar(self):
        self.c.fechar()
        self.r.fechar()
        self.bomba.fechar()

    # ---- colisão (só vale com o braço baixo: no alto ele passa por cima da coletora) ----
    def livre(self, j1, j2):
        if self.obstaculo is None:
            return True
        cot = self.m.cotovelo(j1)
        pon = self.m.fk(j1, j2)
        for a, b in (((0.0, 0.0), cot), (cot, pon)):
            for t in np.linspace(0, 1, 40):
                p = (float(a[0] + (b[0] - a[0]) * t), float(a[1] + (b[1] - a[1]) * t))
                if cv2.pointPolygonTest(self.obstaculo, p, True) > -LARGURA_BRACO:
                    return False
        return True

    def mira(self, x, y, cmd, tol_mm=2.0):
        """com a ponta em cima de (x, y), confere pela câmera e corrige uma vez"""
        z = self.r.posicao("z")
        p = ponta_precisa(self.c.foto(), esperado=self.m.robo_para_pixel(*self.m.fk(*cmd), z))
        if p is None:
            print("   ponta não encontrada: sem correção")
            return cmd
        xr, yr = self.m.pixel_para_robo(p[0], p[1], z)
        e = math.hypot(x - xr, y - yr)
        if e <= tol_mm:
            print("   erro %.1f mm: sem correção" % e)
            return cmd
        xa, ya = self.m.fk(*cmd)
        novo = self.m.ik(xa + x - xr, ya + y - yr, ref=cmd, livre=self.livre)
        self.r.ir_juntas(*novo)
        p = ponta_precisa(self.c.foto(), esperado=self.m.robo_para_pixel(*self.m.fk(*novo), z))
        if p is not None:
            xr, yr = self.m.pixel_para_robo(p[0], p[1], z)
            print("   erro %.1f mm -> %.1f mm depois da correção" % (e, math.hypot(x - xr, y - yr)))
        return novo

    def checar_eventos(self):
        """para tudo se uma placa reiniciou o TMC, perdeu o 24 V ou bateu num fim de curso no meio do ciclo"""
        for n, p in self.r.placas.items():
            ruins = [e for e in p.eventos if any(t in e for t in ("TMC", "FIM", "24 V", "EMERG", "erro"))]
            p.eventos.clear()
            if ruins:
                raise RuntimeError("placa %s: %s -- posição pode estar errada, rode diagnostico.py" % (n, ruins))

    def planejar(self, f):
        m = self.m
        col = acha_coletora(f)
        if col is None:
            raise RuntimeError("caixa coletora não encontrada")
        topo, self.obstaculo = obstaculo_mm(m, col["cantos"], ALTURA_COLETORA)
        # pontos de soltura: ao longo do eixo maior da boca, até 30% do comprimento para cada lado
        cx, cy = np.mean(topo, axis=0)
        lados = [np.subtract(topo[(i + 1) % 4], topo[i]) for i in range(4)]
        eixo = max(lados, key=lambda v: np.hypot(*v))
        comp = float(np.hypot(*eixo))
        u = eixo / comp
        caixas = [k for k in acha_caixas(f) if cv2.pointPolygonTest(np.float32(col["cantos"]), k["centro"], False) < 0]
        n = max(len(caixas), 1)
        ts = np.linspace(-0.3 * comp, 0.3 * comp, n) if n > 1 else [0.0]
        solta = [(float(cx + u[0] * t), float(cy + u[1] * t)) for t in ts]
        return col, caixas, solta, (cx, cy, comp)

    def rodar(self, nome=None, alvo_px=None, ordem=None):
        r, m = self.r, self.m
        self.bomba.rele(RELE_REPOUSO)        # percurso começa com o relé ligado
        if r.posicao("z") < Z_ALTO:
            r.ir("z", Z_ALTO)
        r.ir_juntas(*PARQUE)
        for p in r.placas.values():
            p.eventos.clear()
        f = self.c.foto("fotos/pp_mesa.jpg")
        col, caixas, solta, (cx, cy, comp) = self.planejar(f)
        if alvo_px:                           # caixa indicada à mão (ex.: cortada na borda da imagem)
            caixas = [{"centro": alvo_px, "nome": nome or "", "cantos": []}]
        elif ordem:                           # todas as caixas dos remédios da lista, na ordem da lista
            nomes_gemini(f, caixas)
            for k in caixas:
                print("   caixa px (%.0f, %.0f): %s" % (*k["centro"], k["nome"] or "?"))
            pos_lista = lambda k: next((i for i, n in enumerate(ordem) if mesmo_nome(n, k["nome"])), None)
            caixas = sorted([k for k in caixas if pos_lista(k) is not None], key=pos_lista)
            if not caixas:
                print("nenhuma caixa da lista encontrada: o braço não se move")
                return
        elif nome:
            nomes_gemini(f, caixas)
            for k in caixas:
                print("   caixa px (%.0f, %.0f): %s" % (*k["centro"], k["nome"] or "?"))
            caixas = [k for k in caixas if mesmo_nome(nome, k["nome"])]
            if not caixas:
                print("nenhuma caixa de %s encontrada: o braço não se move" % nome)
                return
        print("coletora: centro (%.0f, %.0f) mm, boca %.0f mm; %d caixas de remédio" % (cx, cy, comp, len(caixas)))
        vis = f.copy()
        cv2.drawContours(vis, [np.int32(col["cantos"])], -1, (0, 165, 255), 3)
        for k in caixas:
            if len(k["cantos"]):
                cv2.drawContours(vis, [np.int32(k["cantos"])], -1, (0, 255, 0), 3)
        for xs, ys in solta:
            a, b = m.robo_para_pixel(xs, ys, m.z_do_plano(ALTURA_COLETORA))
            cv2.drawMarker(vis, (int(a), int(b)), (255, 0, 255), cv2.MARKER_SQUARE, 50, 3)
        cv2.imwrite("fotos/pp_plano.jpg", vis)

        t0 = time.time()
        feitas = 0
        for k in (caixas if ordem else sorted(caixas, key=lambda k: k["centro"][1])):
            u_, v_ = k["centro"]
            x, y = m.pixel_para_robo(u_, v_, m.z_do_plano(ALTURA_CAIXA))
            pos = r.posicoes()
            try:
                cmd = m.ik(x, y, ref=(pos["j1"], pos["j2"]), livre=self.livre)
                cmd_solta = m.ik(*solta[feitas], ref=cmd)
            except ValueError as ex:
                print("caixa px (%.0f, %.0f): pulada (%s)" % (u_, v_, ex))
                continue
            print("caixa %d %s: px (%.0f, %.0f) -> (%.1f, %.1f) mm, juntas (%.1f, %.1f)" % (feitas + 1, k.get("nome", ""), u_, v_, x, y, *cmd))
            t = time.time()
            r.ir_juntas(*cmd)                 # no alto, por cima de tudo
            r.ir("z", Z_MIRA)
            cmd = self.mira(x, y, cmd)
            self.bomba.rele(RELE_PEGA)        # desceu para pegar: relé troca, ventosa puxa
            r.ir("z", Z_PEGA)
            time.sleep(PAUSA_VENTOSA)
            r.ir("z", Z_ALTO)
            r.ir_juntas(*cmd_solta)
            r.ir("z", Z_SOLTA)
            self.bomba.rele(RELE_REPOUSO)     # em cima da coletora: relé liga de novo, a caixa cai
            time.sleep(PAUSA_VENTOSA)
            r.ir("z", Z_ALTO)
            feitas += 1
            self.checar_eventos()
            print("   ciclo %.1f s" % (time.time() - t))
        r.ir_juntas(*PARQUE)
        print("%d caixas, total %.1f s" % (feitas, time.time() - t0))


if __name__ == "__main__":
    pp = PickPlace()
    try:
        nome = sys.argv[sys.argv.index("--nome") + 1] if "--nome" in sys.argv else None
        alvo = tuple(float(v) for v in sys.argv[sys.argv.index("--alvo-px") + 1].split(",")) if "--alvo-px" in sys.argv else None
        ordem = sys.argv[sys.argv.index("--ordem") + 1].split(",") if "--ordem" in sys.argv else None
        pp.rodar(nome, alvo, ordem)
    except Exception as ex:
        print("ERRO", ex)
        pp.r.parar()
        raise
    finally:
        pp.fechar()
