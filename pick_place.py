"""Simulação de pick and place: acha as caixas de remédio e a caixa coletora pela câmera; em cada caixa de remédio
desce, "pega", sobe acima da coletora e "solta" dentro dela. A ventosa ainda não está ligada: as caixas não se
movem, só o braço faz o ciclo.

Alturas (acima da mesa) e o Z correspondente: z = altura + Z_TOQUE_MESA (-114).

Uso: python pick_place.py [--nome micpure] [--z-pega -90]     (com --nome, o Gemini lê os nomes e só pega as caixas desse remédio)
"""
import json
import math
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from cam import Cam, acha_indice
from cameras import CAMERAS, fotos, modelos, ponta_xy, ver_caixas
from correcoes import MapaCorrecoes
from homing import HomingFalhou, homing_j1
from job_os import CaixaInalcancavel
from modelo import ALTURA_CAIXA, Z_TOQUE_MESA
from scara import ACEL_SEGURA, EIXOS, SUAVE, VEL_SEGURA, Z_CHAVE, Scara, juntas_em, plano_juntas, tempo_ate
from selecao import mesmo_nome

ALTURA_COLETORA = 125.0   # mm (medido)
FOLGA_SOLTA = 10.0        # fundo da caixa de remédio fica 1 cm acima da borda ao soltar
FOLGA_PASSA = 34.0        # caixa pendurada passa 3,4 cm acima da borda
Z_ALTO = Z_TOQUE_MESA + ALTURA_COLETORA + ALTURA_CAIXA + FOLGA_PASSA      # +75: deslocamentos
Z_SOLTA = Z_TOQUE_MESA + ALTURA_COLETORA + ALTURA_CAIXA + FOLGA_SOLTA     # +51: solta dentro da coletora
Z_PEGA = -87.0            # ventosa encosta numa caixa de 30 mm em -84; 3 mm a mais assenta (medido); chave de baixo
                          # em -91,7
PARQUE = CAMERAS[0][2]    # repouso: a pose da foto da C920
LARGURA_BRACO = 50.0      # mm de folga entre o braço (baixo) e a coletora
PAUSA_VENTOSA = 0.5
# sem válvula e com a mangueira longa a caixa só cai 2-3 s depois de a bomba desligar: desliga a bomba SOLTA_ANTES s antes
# de chegar sobre a coletora e espera PAUSA_SOLTA. 23/10: 2 s antes caía na chegada, ainda balançando, quase fora; 1 s
# antes cai ~1 s depois de parar; 1,5 s de espera sai de cima logo depois de ela cair
SOLTA_ANTES = 1.0
PAUSA_SOLTA = 1.5
VZ, AZ = 120.0, 1500.0     # Z: mm/s e mm/s² de pico, rampa em S. 23/10, Z no DM556 (2,1 A), com a ventosa, fonte
                           # 25,6 V, 5 ciclos de 121 mm conferidos na chave de cima: 160/700 e 120/2000 sem perda;
                           # 200 mm/s perde até a 450 (o limite é a velocidade, ~1500 rpm)
AZ_MEDIA = AZ * 2 / math.pi   # aceleração média da rampa em S (cossenoidal): é a que vale para o tempo do movimento
COMPRESSAO_PEGA = 3.0      # mm: Z_PEGA fica isso abaixo do encosto na caixa
FOLGA_CORRECAO = 10.0      # mm: a correção das juntas termina com a ventosa pelo menos isso acima da caixa
T_CORRECAO = 0.6           # s: foto + ponta + movimento curto das juntas (o Z continua descendo nesse tempo)
MAX_CORRECAO = 25.0        # mm: erro maior que isso na mira é medida errada (a calibração erra < ~16 mm)
ATRASO_TJ = 0.3            # s: a trajetória das juntas começa depois do envio inicial; o Z que espera o braço sair
                          # da coletora ganha essa folga
ARQ_CORRECOES = Path(__file__).resolve().parent / "correcoes_mira.json"   # desvios aprendidos pela mira
COLETORA_FIXA = Path(__file__).resolve().parent / "coletora.json"   # se existir, a coletora não é detectada
XADREZ_PX = 81              # dilatação do verde: um pouco mais que um quadrado do tabuleiro (~40 px) para cada lado
# relé da bomba (sem válvula): 1 liga a bomba e a ventosa puxa, 0 desliga. Em repouso fica desligada;
# liga ao descer para pegar e desliga em cima da coletora para soltar a caixa.
RELE_REPOUSO, RELE_PEGA = 0, 1


class ColetoraForaDoAlcance(RuntimeError):
    """nenhum ponto da boca da coletora é alcançável: é a coletora que está mal posicionada, não falta remédio"""


def pontos_alcancaveis(m, solta):
    """pontos de soltura (mm) que o braço alcança dentro dos limites das juntas"""
    ok = [p for p in solta if m.ik_todas(*p)]
    if not ok:
        cx, cy = np.mean(solta, axis=0)
        raise ColetoraForaDoAlcance(
            "coletora fora do alcance do braço: a boca está a %.0f mm do eixo do J1 (o braço alcança de ~220 a "
            "500 mm); mude a coletora de lugar" % math.hypot(cx, cy))
    return ok


def acha_coletora(f):
    """caixa de MDF (cor de madeira): maior região cor de madeira -> retângulo e polígono (px).
    A madeira perto de verde é o tabuleiro de xadrez (encostado na coletora): sai antes de juntar as regiões."""
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (8, 50, 80), (25, 200, 255))
    verde = cv2.dilate(cv2.inRange(hsv, (35, 60, 80), (85, 255, 255)), np.ones((XADREZ_PX, XADREZ_PX), np.uint8))
    m[verde > 0] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 50000:
        return None
    r = cv2.minAreaRect(c)
    return {"rect": r, "cantos": cv2.boxPoints(r)}


def coletora_fixa(arq=COLETORA_FIXA):
    """coletora com posição fixa (cantos da boca em px de uma câmera), ou None para detectar pela cor"""
    try:
        d = json.load(open(arq))
    except FileNotFoundError:
        return None
    cantos = np.float32(d["cantos_px"])
    return {"cam": d["cam"], "cantos": cantos, "rect": cv2.minAreaRect(cantos)}


def obstaculo_mm(m, cantos_px, altura):
    """polígono (mm) ocupado por um objeto de `altura` cujos cantos aparecem em `cantos_px`: fecho do topo e da base"""
    topo = [m.pixel_para_robo(u, v, m.z_do_plano(altura)) for u, v in cantos_px]
    base = [m.pixel_para_robo(u, v, m.z_do_plano(0)) for u, v in cantos_px]
    return topo, cv2.convexHull(np.float32(topo + base))


def pode_corrigir(z, z_pega, vz=EIXOS["z"]["v"]):
    """com o Z em `z` descendo a vz até z_pega, ainda dá para fotografar e corrigir as juntas antes de encostar?"""
    return z - vz * T_CORRECAO >= z_pega + COMPRESSAO_PEGA + FOLGA_CORRECAO


def instante_soltar(T, tz, atraso_j, atraso_z, antes):
    """s desde o começo do movimento até desligar a bomba: `antes` s antes da chegada (juntas e Z, o último)"""
    return max(0.0, round(max(atraso_j + T, atraso_z + tz) - antes, 6))


def t_saida(livre, traj, T, dt=0.02):
    """instante a partir do qual o braço fica livre da coletora até o fim da trajetória (0 se sempre livre)"""
    t, ultimo_preso = 0.0, None
    while t <= T + 1e-9:
        q = traj(t)
        if not livre(q["j1"], q["j2"]):
            ultimo_preso = t
        t += dt
    return 0.0 if ultimo_preso is None else min(ultimo_preso + dt, T)


def t_entrada(livre, traj, T, dt=0.02):
    """primeiro instante em que o braço fica sobre a coletora (None se nunca)"""
    t = 0.0
    while t <= T + 1e-9:
        q = traj(t)
        if not livre(q["j1"], q["j2"]):
            return t
        t += dt
    return None


def braco_livre(m, obstaculo, j1, j2):
    """braço (base -> cotovelo -> ponta) a mais de LARGURA_BRACO do polígono do obstáculo (mm); vale com o braço baixo"""
    if obstaculo is None:
        return True
    cot = m.cotovelo(j1)
    pon = m.fk(j1, j2)
    for a, b in (((0.0, 0.0), cot), (cot, pon)):
        for t in np.linspace(0, 1, 40):
            p = (float(a[0] + (b[0] - a[0]) * t), float(a[1] + (b[1] - a[1]) * t))
            if cv2.pointPolygonTest(obstaculo, p, True) > -LARGURA_BRACO:
                return False
    return True


BOCA_MM = (300.0, 500.0)    # comprimento da boca da coletora (detecções certas de 23/10: 368 a 460 mm)
LARGURA_MIN_MM = 150.0


def confere_coletora(comp, larg):
    """a coletora achada tem tamanho de coletora? (23/10: a borda de madeira da mesa, 644 x ~40 mm, passou por
    coletora e o braço desceu nas caixas de dentro da coletora de verdade)"""
    if not (BOCA_MM[0] <= comp <= BOCA_MM[1]) or larg < LARGURA_MIN_MM:
        raise RuntimeError("coletora com %.0f x %.0f mm não parece a coletora (boca %.0f-%.0f mm): nada se move; "
                           "confira a foto fotos/pp_plano_*.jpg e o coletora.json" % (comp, larg, *BOCA_MM))


def coletora_mm(ms, arq=COLETORA_FIXA):
    """polígono (mm) ocupado pela coletora fixa, ou None se não houver coletora.json"""
    col = coletora_fixa(arq)
    return None if col is None else obstaculo_mm(ms[col["cam"]], col["cantos"], ALTURA_COLETORA)[1]


def fora_da_coletora(caixas, hull):
    """caixas (com "xy" em mm) fora do polígono da coletora: as de dentro já foram separadas"""
    return [k for k in caixas if cv2.pointPolygonTest(hull, tuple(map(float, k["xy"])), False) < 0]


VISAO = Path(__file__).resolve().parent.parent / "only-vision"
ENV_BRACO = Path(__file__).resolve().parent / ".env"   # a GEMINI_API_KEY pode ficar aqui ou no .env do only-vision


def nomes_gemini(f, caixas):
    """lê o nome de cada caixa com o Gemini (only-vision) e associa à caixa do OpenCV mais próxima"""
    sys.path.insert(0, str(VISAO))
    from dotenv import load_dotenv
    load_dotenv(VISAO / ".env")
    load_dotenv(ENV_BRACO)
    import vision_remedios as vr
    g = vr.AnalisadorGemini(vr.os.getenv("GEMINI_MODEL", "gemini-robotics-er-2-preview"))
    t = time.time()
    lidas = g.detectar(f)
    if isinstance(lidas, tuple):          # versões antigas do only-vision devolviam (caixas, extra)
        lidas = lidas[0]
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
    def __init__(self, com_nomes=True):
        self.ms = modelos()                 # uma calibração por câmera; a cinemática (o2) é a da C920
        self.m = self.ms[CAMERAS[0][0]]
        self.r = Scara(fator_vel=1.0)
        self.r.placas["z"].cmd("rampa", s=1)   # Z em curva S (só na RAM da placa): sem tranco na ventosa/caixa
        self.cams = {nome: Cam(idx=acha_indice(nome), nome=nome) for nome, _, _ in CAMERAS}   # nome: reabre se cair da USB
        self.obstaculo = None      # polígono da coletora em mm (referencial do robô)
        self.z_pega = Z_PEGA
        self.correcoes = MapaCorrecoes(ARQ_CORRECOES)
        self._homing_feito = False     # Z (chave) e J1 (visão, sem fim de curso) conferidos uma vez por execução
        self.com_nomes = com_nomes  # lê os nomes das caixas com o Gemini (só precisa quando a OS pede remédios)
        self._solta = []

    def fechar(self):
        """sempre deixa a bomba desligada (o relé mantém o estado depois que a porta fecha), mesmo após erro;
        o Scara corta a energia (bomba inclusive) ao fechar"""
        try:
            self.r.bomba(RELE_REPOUSO)
        except Exception as ex:
            print("bomba: não foi possível desligar o relé (%s)" % ex)
        for c in self.cams.values():
            c.fechar()
        self.r.fechar()

    # ---- colisão (só vale com o braço baixo: no alto ele passa por cima da coletora) ----
    def livre(self, j1, j2):
        return braco_livre(self.m, self.obstaculo, j1, j2)

    def mira(self, x, y, cmd, tol_mm=2.0):
        """com a ponta parada em cima de (x, y), mede o erro pela câmera que a vê melhor e devolve as juntas
        corrigidas e o desvio medido (mm), sem mover (a correção vai junto com a descida). Medida absurda é
        refeita uma vez; se continuar absurda (outra coisa azul confundida com a ponta), segue sem corrigir."""
        z = lambda: self.r.posicao("z")    # lido logo depois da foto: o Z pode estar descendo
        for _ in range(2):
            v = ponta_xy(self.cams, self.ms, (x, y), z)   # com o desvio aprendido, a ponta está na caixa
            if v is None:
                print("   ponta não encontrada: sem correção")
                return cmd, None
            e = math.hypot(x - v[1], y - v[2])
            if e <= MAX_CORRECAO:
                break
            print("   erro %.1f mm (%s) não confere: medindo de novo" % (e, v[0]))
        else:
            print("   medida da ponta incoerente: sem correção")
            return cmd, None
        desvio = (x - v[1], y - v[2])
        if e <= tol_mm:
            print("   erro %.1f mm (%s): sem correção" % (e, v[0]))
            return cmd, desvio
        xa, ya = self.m.fk(*cmd)
        try:
            novo = self.m.ik(xa + desvio[0], ya + desvio[1], ref=cmd, livre=self.livre)
        except ValueError:
            print("   erro %.1f mm (%s): correção fora do alcance, segue sem corrigir" % (e, v[0]))
            return cmd, desvio
        print("   erro %.1f mm (%s): corrige descendo" % (e, v[0]))
        return novo, desvio

    def checar_eventos(self):
        """para tudo se uma placa reiniciou o TMC, perdeu o 24 V ou bateu num fim de curso no meio do ciclo"""
        for n, p in self.r.placas.items():
            ruins = [e for e in p.eventos if any(t in e for t in ("TMC", "FIM", "24 V", "EMERG", "erro"))]
            p.eventos.clear()
            if ruins:
                raise RuntimeError("placa %s: %s -- posição pode estar errada, rode diagnostico.py" % (n, ruins))

    def planejar(self, fs):
        """fs: {câmera: (foto, pose, z)}. Coletora do coletora.json ou da primeira câmera que a acha; caixas de
        todas as câmeras, fora dela"""
        col = coletora_fixa()
        if col is None:
            for nome, _, _ in CAMERAS:
                col = acha_coletora(fs[nome][0])
                if col is not None:
                    col["cam"] = nome
                    break
        if col is None:
            raise RuntimeError("caixa coletora não encontrada")
        topo, self.obstaculo = obstaculo_mm(self.ms[col["cam"]], col["cantos"], ALTURA_COLETORA)
        # pontos de soltura: ao longo do eixo maior da boca, até 30% do comprimento para cada lado
        cx, cy = np.mean(topo, axis=0)
        lados = [np.subtract(topo[(i + 1) % 4], topo[i]) for i in range(4)]
        eixo = max(lados, key=lambda v: np.hypot(*v))
        comp = float(np.hypot(*eixo))
        confere_coletora(comp, float(min(np.hypot(*v) for v in lados)))
        u = eixo / comp
        caixas = fora_da_coletora(ver_caixas(fs, self.ms), self.obstaculo)
        for k in caixas:
            k["centro"] = k["xy"]           # mm, referencial do robô (selecao ordena por ele)
        n = max(len(caixas), 1)
        ts = np.linspace(-0.3 * comp, 0.3 * comp, n) if n > 1 else [0.0]
        solta = [(float(cx + u[0] * t), float(cy + u[1] * t)) for t in ts]
        return col, caixas, solta, (cx, cy, comp)

    def nomes(self, fs, caixas):
        """nome de cada caixa pelo Gemini, uma chamada por câmera que viu alguma; vale o primeiro nome lido"""
        for nome, (f, _, _) in fs.items():
            obs = [dict(o, centro=o["px"]) for k in caixas for o in k["obs"] if o["cam"] == nome]
            if obs:
                nomes_gemini(f, obs)
                for o, lida in zip([o for k in caixas for o in k["obs"] if o["cam"] == nome], obs):
                    o["nome"] = lida["nome"]
        for k in caixas:
            k["nome"] = next((o["nome"] for o in k["obs"] if o.get("nome")), "")

    # ---- executor da OS (job_os.JobOS): preparar -> pegar(caixa) por caixa -> estacionar ----
    def referenciar(self):
        """Z e J2 pelas chaves e J1 pela câmera (levado ao 0 corrigido); o primeiro preparar e o botão "Referenciar
        braço" do sistema"""
        r = self.r
        # Z pela chave de cima (está a ~25 mm daqui: uma perda de passo só aparece quando bate numa chave)
        r.referenciar_z(vbusca=20.0)
        r.definir("z", Z_CHAVE)
        self.ir_z(Z_ALTO)              # sai de cima da chave: o homing do J1 fotografa a ponta nessa altura
        r.referenciar_j2()
        # J1: o alinhamento à mão é só o ponto de partida; a câmera tem que confirmar (com o anel do rolamento) e
        # corrigir. Sem confirmar, nada se move (23/10: seguir sem conferir levou o J1 além dos limites depois de a
        # placa do braço reiniciar com a contagem zerada)
        try:
            homing_j1(r, self.cams, self.ms, VEL_SEGURA, ACEL_SEGURA)
        except HomingFalhou as ex:
            raise HomingFalhou("%s: alinhe o J1 à mão (reto, 0°) e rode de novo" % ex) from ex
        r.ir_juntas(0.0, r.posicao("j2"), vmax=VEL_SEGURA, amax=ACEL_SEGURA)   # J1 no 0 corrigido: confere reto
        self._homing_feito = True

    def preparar(self):
        """sobe, referencia o Z e o J2 pelas chaves e confere o J1 pela visão (só na primeira vez), fotografa a mesa com cada
        câmera e planeja: devolve as caixas de remédio (com "nome" se com_nomes)"""
        r, m = self.r, self.m
        self.r.bomba(RELE_REPOUSO)        # percurso começa com a bomba desligada
        if r.posicao("z") < Z_ALTO:
            self.ir_z(Z_ALTO)
        if not self._homing_feito:
            self.referenciar()
        for p in r.placas.values():
            p.eventos.clear()
        fs = fotos(r, self.cams, "fotos/pp_mesa")
        col, caixas, solta, (cx, cy, comp) = self.planejar(fs)
        self._solta = pontos_alcancaveis(m, solta)
        if self.com_nomes:
            self.nomes(fs, caixas)
        else:
            for k in caixas:
                k["nome"] = ""
        for k in caixas:
            print("   caixa (%.0f, %.0f) mm, vista por %s: %s" % (*k["xy"], "+".join(k["cams"]), k["nome"] or "?"))
        print("coletora (%s): centro (%.0f, %.0f) mm, boca %.0f mm; %d caixas de remédio" % (
            col["cam"], cx, cy, comp, len(caixas)))
        for nome, (f, _, _) in fs.items():
            mc = self.ms[nome]
            vis = f.copy()
            if nome == col["cam"]:
                cv2.drawContours(vis, [np.int32(col["cantos"])], -1, (0, 165, 255), 3)
            for k in caixas:
                for o in k["obs"]:
                    if o["cam"] == nome:
                        cv2.drawContours(vis, [np.int32(o["cantos"])], -1, (0, 255, 0), 3)
            for xs, ys in self._solta:
                a, b = mc.robo_para_pixel(xs, ys, mc.z_do_plano(ALTURA_COLETORA))[:2]
                cv2.drawMarker(vis, (int(a), int(b)), (255, 0, 255), cv2.MARKER_SQUARE, 50, 3)
            cv2.imwrite("fotos/pp_plano_%s.jpg" % nome, vis)
        return caixas

    def ir_z(self, z, esperar=True):
        """Z na velocidade/aceleração testadas com a ventosa (VZ, AZ)"""
        self.r.ir("z", z, fator=VZ / EIXOS["z"]["v"], acel=AZ, esperar=esperar)

    def juntas_e_z(self, alvo, z_alvo, durante=None, folga_fim=0.0, antes_de_chegar=None):
        """J1+J2 e Z ao mesmo tempo (placas diferentes). Descendo: o Z só começa com o braço fora da coletora e,
        se der, termina `folga_fim` s depois das juntas. Subindo: as juntas esperam o necessário para o braço só
        chegar sobre a coletora com o Z já em z_alvo. `durante()` roda com as juntas já no alvo e o Z ainda andando.
        `antes_de_chegar` = (s, fn): fn() roda s segundos antes da chegada (desligar a bomba para soltar)."""
        r = self.r
        pos = r.posicoes()
        ini, fim = {"j1": pos["j1"], "j2": pos["j2"]}, {"j1": alvo[0], "j2": alvo[1]}
        T, f = plano_juntas(ini, fim, VEL_SEGURA, ACEL_SEGURA, SUAVE)
        traj = lambda t: juntas_em(ini, fim, T, f, SUAVE, t)
        dz = z_alvo - pos["z"]
        tz = tempo_ate(dz, dz, VZ, AZ_MEDIA)
        livre = (lambda j1, j2: True) if self.obstaculo is None else self.livre
        if dz < 0:
            ts = t_saida(livre, traj, T)
            atraso_z, atraso_j = max(ts + ATRASO_TJ if ts > 0 else 0.0, T - tz + folga_fim), 0.0
        else:
            te = t_entrada(livre, traj, T)
            atraso_z, atraso_j = 0.0, (0.0 if te is None else max(0.0, tz - te))
        print("   juntas %.2f s, Z %+.0f mm em %.2f s; atraso Z %.2f s, atraso juntas %.2f s" % (T, dz, tz, atraso_z, atraso_j))
        z_vai = lambda: self.ir_z(z_alvo, esperar=False)
        ta = None
        if antes_de_chegar:
            ta = threading.Timer(instante_soltar(T, tz, atraso_j, atraso_z, antes_de_chegar[0]), antes_de_chegar[1])
            ta.start()
        tm = threading.Timer(atraso_z, z_vai) if atraso_z > 0 else None
        if tm:
            tm.start()
        else:
            z_vai()
        try:
            time.sleep(atraso_j)
            r.ir_juntas(*alvo, vmax=VEL_SEGURA, amax=ACEL_SEGURA)
            if durante:
                if tm:
                    tm.join()           # o Z precisa já ter partido
                durante()
        finally:
            if tm:
                tm.join()
            if ta:
                ta.join()
        r.esperar("z")
        if abs(r.posicao("z") - z_alvo) > 0.05:
            raise RuntimeError("Z parou em %.2f, alvo %.2f: %s" % (r.posicao("z"), z_alvo, r.placas["z"].eventos[-3:]))

    def mira_descendo(self, x, y, cmd):
        """com as juntas em cima da caixa e o Z descendo: confere pela câmera e corrige, se ainda der tempo"""
        if not pode_corrigir(self.r.posicao("z"), self.z_pega, VZ):
            print("   Z já baixo demais para conferir: segue sem corrigir")
            return cmd
        novo, desvio = self.mira(x, y, cmd)
        if desvio is not None:
            self.correcoes.aprender((x, y), desvio)
            self.correcoes.salvar()
        if novo != cmd:
            self.r.ir_juntas(*novo, vmax=VEL_SEGURA, amax=ACEL_SEGURA)
        return novo

    def pegar(self, k, i):
        """um ciclo, com o Z andando junto com as juntas: vai até a caixa, confere pela câmera (se o lugar ainda não é
        confiável), pega e solta no ponto i da coletora (fica lá em cima; o próximo ciclo sai de lá)"""
        r, m = self.r, self.m
        x, y = k["xy"]
        aprendido = self.correcoes.prever((x, y))       # desvio já medido perto daqui: vai certo de primeira
        pos = r.posicoes()
        try:
            cmd = m.ik(x + aprendido[0], y + aprendido[1], ref=(pos["j1"], pos["j2"]), livre=self.livre)
        except ValueError as ex:
            raise CaixaInalcancavel("(%.0f, %.0f) mm: %s" % (x, y, ex)) from ex
        cmd_solta = m.ik(*self._solta[i % len(self._solta)], ref=cmd)   # já filtrado em preparar()
        print("caixa %d %s: (%.1f, %.1f) mm, juntas (%.1f, %.1f)" % (i + 1, k.get("nome", ""), x, y, *cmd))
        t = time.time()
        if self.correcoes.confiavel((x, y)):
            print("   lugar conhecido (última mira acertou): desce direto")
            self.correcoes.pulou((x, y))
            self.correcoes.salvar()
            self.r.bomba(RELE_PEGA)        # vai pegar: liga a bomba, ventosa puxa
            self.juntas_e_z(cmd, self.z_pega)
        else:
            # sem parar: foto quando as juntas chegam (o Z ainda desce) e correção enquanto o Z termina
            self.r.bomba(RELE_PEGA)
            final = [cmd]
            self.juntas_e_z(cmd, self.z_pega, durante=lambda: final.__setitem__(0, self.mira_descendo(x, y, cmd)),
                            folga_fim=T_CORRECAO + 0.5)
            cmd = final[0]
        time.sleep(PAUSA_VENTOSA)
        # a bomba desliga ainda a caminho da coletora: sem válvula o vácuo demora a acabar
        self.juntas_e_z(cmd_solta, Z_SOLTA, antes_de_chegar=(SOLTA_ANTES, lambda: self.r.bomba(RELE_REPOUSO)))
        self.r.bomba(RELE_REPOUSO)     # garante desligada mesmo se o movimento foi curto
        time.sleep(PAUSA_SOLTA)
        self.checar_eventos()
        print("   ciclo %.1f s" % (time.time() - t))

    def estacionar(self):
        if self.r.posicao("z") < Z_ALTO:
            self.ir_z(Z_ALTO)
        self.r.ir_juntas(*PARQUE, vmax=VEL_SEGURA, amax=ACEL_SEGURA)

    def parar(self):
        self.r.parar()

    def rodar(self, nome=None, alvo_px=None, ordem=None):
        self.com_nomes = bool(nome or ordem) and not alvo_px
        caixas = self.preparar()
        if alvo_px:                           # caixa indicada à mão (ex.: cortada na borda da imagem)
            xy = self.m.caixa_para_robo(*alvo_px)     # pixel da C920
            caixas = [{"xy": xy, "centro": xy, "nome": nome or "", "cams": [CAMERAS[0][0]], "obs": []}]
        elif ordem:                           # todas as caixas dos remédios da lista, na ordem da lista
            pos_lista = lambda k: next((i for i, n in enumerate(ordem) if mesmo_nome(n, k["nome"])), None)
            caixas = sorted([k for k in caixas if pos_lista(k) is not None], key=pos_lista)
            if not caixas:
                print("nenhuma caixa da lista encontrada: o braço não se move")
                return
        elif nome:
            caixas = [k for k in caixas if mesmo_nome(nome, k["nome"])]
            if not caixas:
                print("nenhuma caixa de %s encontrada: o braço não se move" % nome)
                return
        t0 = time.time()
        feitas = 0
        for k in (caixas if ordem else sorted(caixas, key=lambda k: k["centro"][1])):
            try:
                self.pegar(k, feitas)
            except CaixaInalcancavel as ex:
                print("caixa pulada (%s)" % ex)
                continue
            feitas += 1
        self.r.ir_juntas(*PARQUE, vmax=VEL_SEGURA, amax=ACEL_SEGURA)
        print("%d caixas, total %.1f s" % (feitas, time.time() - t0))


if __name__ == "__main__":
    pp = PickPlace()
    try:
        nome = sys.argv[sys.argv.index("--nome") + 1] if "--nome" in sys.argv else None
        alvo = tuple(float(v) for v in sys.argv[sys.argv.index("--alvo-px") + 1].split(",")) if "--alvo-px" in sys.argv else None
        ordem = sys.argv[sys.argv.index("--ordem") + 1].split(",") if "--ordem" in sys.argv else None
        if "--z-pega" in sys.argv:
            pp.z_pega = float(sys.argv[sys.argv.index("--z-pega") + 1])
        pp.rodar(nome, alvo, ordem)
    except Exception as ex:
        print("ERRO", ex)
        pp.r.parar()
        raise
    finally:
        pp.fechar()
