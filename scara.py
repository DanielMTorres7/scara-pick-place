"""Controle do SCARA pelas placas ScaraNode (firmware "painel" no.py, JSON por linha na USB).

Placa 801c (modo "dois"): J1 no DM556, J2 no TMC2209 (1/16, 1,35 A).   Placa 5b1c (modo "tmc"): Z no TMC2209 (1/16, 1,35 A).
Movimentos ponto a ponto, um eixo por vez, com velocidade limitada por FATOR_VEL.
"""
import base64
import json
import math
import struct
import time
from pathlib import Path

import serial
import serial.tools.list_ports

from reles import Reles

UID_BRACO = "504446688896801c"
UID_Z = "5044466888c15b1c"

# passos por unidade (grau ou mm), canal e limites — vindos do config.json das placas
EIXOS = {
    "j1": {"placa": "braco", "k": "dm556", "passos_un": 3200 * 14 / 360, "min": -130, "max": 130, "v": 30, "a": 60},
    "j2": {"placa": "braco", "k": "tmc", "passos_un": 200 * 16 * 12 / 360, "min": -128, "max": 128, "v": 45, "a": 90},
    "z": {"placa": "z", "k": "dm556", "passos_un": 3200 / 8, "min": -106, "max": 99, "v": 45, "a": 150},   # DM556 (3200 passos/volta, inv_dir na placa); 45 mm/s até refazer o teste de velocidade
}

FATOR_VEL = 0.2   # fração da velocidade/aceleração configurada nos movimentos de um eixo só (ir)
Z_CURSO = 191.7        # mm entre a chave de cima e a de baixo (medido no DM556, 23/10)
FOLGA_BUSCA_Z = 12.0   # mm: o referenciamento do Z procura a chave só até isso além de onde ela deveria estar
RECUO_MAX_Z = 10.0     # mm: recuo máximo esperando a chave soltar; com o DIR falhando o "recuo" sobe (23/10)
Z_CHAVE = 100.31  # posição do Z (referencial da calibração) em que o fim de curso de cima aciona
J2_CHAVE = 130.5  # J2 nas chaves: FIM2 (lado do xadrez) em +130,5°, FIM1 em -130,5° (medido 2026-10-22)
Z_TOQUE_MESA = -114.0   # ventosa encosta na mesa (medido: encosta numa caixa de 30 mm em -84; mesa erguida 6 mm em 23/10)

# movimento conjunto J1+J2 (trajetória sincronizada): limites em grau/s e grau/s²
VEL_JUNTAS = {"j1": 900 / 60 * 360 / 14, "j2": 900 / 60 * 360 / 12}   # 900 rpm nos motores (J2 em 1/16: a 1/32 o limite da trajetória era 800)
VEL_PONTA = 3000.0  # mm/s: teto da velocidade da ponta (cartesiana)
L1, L2, O2 = 300.0, 200.0, 1.35  # braço (mm) e zero do J2 (calibracao_braco.json e calibracao_XWF.json: 1,28 e 1,41; lugar novo, 23/10)
ACEL_JUNTAS = {"j1": 60.0, "j2": 60.0}   # °/s²: reduzida depois da bomba montada no antebraço (antes 120 testado sem bomba)
VEL_SEGURA = {"j1": 400 / 60 * 360 / 14, "j2": 400 / 60 * 360 / 12}   # °/s: 400 rpm nos motores (gargalo DM556)
ACEL_SEGURA = {"j1": 200.0, "j2": 150.0}   # °/s²: combinado seguro medido com a curva S 0,5 (movimentos rápidos)
SUAVE = 0.5        # curva S: fração da rampa com aceleração variando (0 = trapézio, 1 = S completa). 0,5 deixou o J1
                   # aguentar 250 °/s² de pico (trapézio: 150) com o mesmo tempo de movimento ou menos
DT = 0.01          # s por segmento (igual ao painel)
FREQ = 10_000_000  # relógio do gerador de passos da placa
TJ_DMIN = 50


class MovimentoAbortado(RuntimeError):
    """a placa parou o eixo antes do alvo (24 V, fim de curso, emergência...)"""


def perfil_sincrono(deltas, vmax, amax, suave=0.0):
    """perfil com a mesma forma no tempo para todas as juntas (começam e terminam juntas).
    Devolve (T, f): duração total e fração de aceleração (ta = f*T). Com curva S (`suave`) a aceleração
    de pico é maior que a média da rampa, então a rampa se alonga para o pico não passar de amax."""
    k_s = 1 - suave / 2
    melhor = None
    for i in range(1, 51):
        f = i / 100.0
        T = 0.0
        for k, d in deltas.items():
            d = abs(d)
            if d == 0:
                continue
            T = max(T, math.sqrt(d / (amax[k] * f * (1 - f) * k_s)), d / (vmax[k] * (1 - f)))
        if melhor is None or T < melhor[0]:
            melhor = (T, f)
    return melhor


def s_trapezio(t, T, f):
    """posição normalizada (0..1) do trapézio de duração T e aceleração em f*T"""
    ta = f * T
    v = 1.0 / (T - ta)
    a = v / ta
    if t <= 0:
        return 0.0
    if t >= T:
        return 1.0
    if t < ta:
        return 0.5 * a * t * t
    if t <= T - ta:
        return 0.5 * a * ta * ta + v * (t - ta)
    u = T - t
    return 1.0 - 0.5 * a * u * u


def s_curva(t, T, f, suave=0.0):
    """posição normalizada (0..1) com rampa de duração f*T em que a aceleração sobe e desce linearmente
    durante `suave`/2 da rampa em cada ponta (tranco limitado); suave = 0 é o trapézio"""
    if suave <= 0:
        return s_trapezio(t, T, f)
    if t <= 0:
        return 0.0
    if t >= T:
        return 1.0
    if t > T / 2:
        return 1.0 - s_curva(T - t, T, f, suave)
    ta = f * T
    tj = suave * ta / 2
    v = 1.0 / (T - ta)              # rampa simétrica: anda v*ta/2, como no trapézio
    a = v / (ta - tj)               # aceleração de pico
    if t >= ta:
        return v * ta / 2 + v * (t - ta)
    if t <= tj:
        return a * t ** 3 / (6 * tj)
    if t <= ta - tj:
        u = t - tj
        return a * tj * tj / 6 + a * tj / 2 * u + a * u * u / 2
    u = ta - t
    return v * ta / 2 - v * u + a * u ** 3 / (6 * tj)


def plano_juntas(ini, alvo, vmax=None, amax=None, suave=SUAVE):
    """(T, f) do movimento conjunto de `ini` a `alvo` ({"j1", "j2"} em graus): perfil síncrono, esticado se a
    ponta passar de VEL_PONTA. T = 0 se já está no alvo."""
    deltas = {k: alvo[k] - ini[k] for k in ("j1", "j2")}
    if all(abs(d) < 1e-3 for d in deltas.values()):
        return 0.0, 0.5
    T, f = perfil_sincrono(deltas, vmax or VEL_JUNTAS, amax or ACEL_JUNTAS, suave)
    def ponta(t):
        q = juntas_em(ini, alvo, T, f, suave, t)
        a = math.radians(q["j1"])
        b = a + math.radians(q["j2"] + O2)
        return L1 * math.cos(a) + L2 * math.cos(b), L1 * math.sin(a) + L2 * math.sin(b)
    vp = max(math.dist(ponta(t), ponta(t + DT)) / DT for t in [i * DT for i in range(int(T / DT) + 1)])
    if vp > VEL_PONTA:
        T *= vp / VEL_PONTA
    return T, f


def juntas_em(ini, alvo, T, f, suave, t):
    """posição das juntas no instante t do movimento planejado por plano_juntas"""
    s = s_curva(min(max(t, 0.0), T), T, f, suave) if T > 0 else 1.0
    return {k: ini[k] + (alvo[k] - ini[k]) * s for k in ("j1", "j2")}


def tempo_ate(total, d, v, a):
    """instante (s) em que um movimento trapezoidal de `total` (v, a) já percorreu `d`"""
    total, d = abs(total), min(abs(d), abs(total))
    da = v * v / (2 * a)                       # distância de cada rampa
    if 2 * da > total:                         # triângulo: não chega a v
        da, v = total / 2, math.sqrt(a * total)
    ta = v / a
    if d <= da:
        return math.sqrt(2 * d / a)
    if d <= total - da:
        return ta + (d - da) / v
    T = 2 * ta + (total - 2 * da) / v
    return T - math.sqrt(2 * (total - d) / a)


def codifica(q, spu, p0, freq=FREQ, dmin=TJ_DMIN):
    """ângulos a cada DT -> palavras do _traj (no.py): d | DIR << 20 | n << 21 (cópia do codifica do robo.html)"""
    Tc = round(DT * freq)
    w = []
    A, prev, dirb = 0, p0, 1
    for m, qm in enumerate(q):
        alvo = round(qm * spu)
        n = alvo - prev
        prev = alvo
        t = (m + 1) * Tc - A
        if n == 0:
            d = min(max(t - 9, 1), 0xFFFFF)
            A += d + 9
            w.append(dirb * 0x100000 + d)
            continue
        an = abs(n)
        dirb = 1 if n > 0 else 0
        if an > 2047:
            raise ValueError("junta rápida demais (%d passos em %g ms)" % (an, DT * 1000))
        d = min(0xFFFFF, round(((t - 5) / an - 8) / 2))
        if d < dmin:
            raise ValueError("junta rápida demais: %d passos/s" % round(an / DT))
        A += 5 + an * (2 * d + 8)
        w.append(an * 0x200000 + dirb * 0x100000 + d)
    return w, prev


class PlacaTravada(TimeoutError):
    """a placa parou de responder (RP2040 travado: 23/10, depois do relé da bomba/potência mudar)"""

    def __init__(self, nome, serie, comando):
        super().__init__("placa %s (%s) não responde a %s" % (nome, serie, comando))
        self.nome, self.serie = nome, serie


def _escreve_sysfs(arq, v):
    with open(arq, "w") as f:
        f.write(v)


def reinicia_porta_usb(serie, raiz=Path("/sys/bus/usb/devices"), espera=2.0):
    """desliga e religa a porta do hub em que está a placa `serie` (hub com power switching por porta, arquivo
    disable liberado pela regra udev 52-uhubctl.rules). False se ela não está atrás de um hub ou não foi achada."""
    for d in raiz.glob("*"):
        try:
            if (d / "serial").read_text().strip().lower() != serie.lower():
                continue
        except OSError:
            continue
        if "." not in d.name:
            return False                              # porta da própria máquina: sem como cortar a energia
        hub, porta = d.name.rsplit(".", 1)
        arq = raiz / ("%s:1.0" % hub) / ("%s-port%s" % (hub, porta)) / "disable"
        _escreve_sysfs(arq, "1")
        time.sleep(espera)
        _escreve_sysfs(arq, "0")
        return True
    return False


class Placa:
    def __init__(self, porta, serie=None, papel=None):
        self.serie, self.papel = serie, papel or porta
        self.s = serial.Serial(porta, 115200, timeout=0.2)
        time.sleep(0.2)
        self.s.reset_input_buffer()
        self.id = 0
        self.eventos = []

    def cmd(self, c, timeout=3.0, **kw):
        self.id += 1
        m = {"c": c, "id": self.id, **kw}
        self.s.write((json.dumps(m) + "\n").encode())
        fim = time.time() + timeout
        while time.time() < fim:
            linha = self.s.readline().decode(errors="replace").strip()
            if not linha.startswith("{"):
                continue
            try:
                r = json.loads(linha)
            except ValueError:
                continue
            if r.get("ev"):
                self.eventos += r["ev"]
                for e in r["ev"]:
                    print("[placa]", e)
            if r.get("id") == self.id:
                if not r.get("ok"):
                    raise RuntimeError("%s: %s" % (c, r.get("erro")))
                return r
        raise PlacaTravada(self.papel, self.serie, c)

    def reiniciar(self, timeout=10.0):
        """reinicia o MicroPython da placa (Ctrl-C para o firmware, Ctrl-D faz o soft reset, que também zera a PIO)
        e espera o firmware voltar a responder. A contagem dos eixos zera."""
        self.s.write(b"\r\x03\x03")
        time.sleep(0.2)
        self.s.write(b"\x04")
        time.sleep(1.0)
        self.s.reset_input_buffer()
        fim = time.time() + timeout
        while True:
            try:
                return self.cmd("ping", timeout=1.0)
            except (TimeoutError, RuntimeError):
                if time.time() > fim:
                    raise TimeoutError("a placa não voltou depois do reinício")

    def fechar(self):
        self.s.close()


def acha_portas():
    portas = {}
    for p in serial.tools.list_ports.comports():
        sn = (p.serial_number or "").lower()
        if sn == UID_BRACO:
            portas["braco"] = p.device
        elif sn == UID_Z:
            portas["z"] = p.device
    return portas


class Scara:
    def __init__(self, fator_vel=FATOR_VEL):
        portas = acha_portas()
        if set(portas) != {"braco", "z"}:
            raise RuntimeError("placas encontradas: %s" % portas)
        self.reles = Reles()   # no boot dos relés tudo fica desligado: a energia liga aqui e corta no fechar
        try:
            self.reles.energizar()
            self.placas = {n: Placa(p) for n, p in portas.items()}
            for n, pl in self.placas.items():         # para PlacaTravada dizer qual placa e achar a porta dela no hub
                pl.serie, pl.papel = {"braco": UID_BRACO, "z": UID_Z}[n], n
            self.fator_vel = fator_vel
            # fins de curso (só na RAM da placa): Z cima = FIM1 bloqueia a subida, baixo = FIM2 a descida;
            # J2: FIM1 no lado -, FIM2 no lado +
            # 23/10: com a placa do Z ligada havia horas a chave de cima deixou de parar o motor (a placa achava que
            # tinha parado e o Z seguia subindo); reiniciada, voltou a parar. Reinicia a cada abertura e referencia.
            self.placas["z"].reiniciar()
            self.placas["z"].cmd("fim", f1=1, f2=-1)
            self.placas["braco"].cmd("fim", f1=-1, f2=1)
            self._espera_tmc()
            self.definir("z", Z_CHAVE - Z_CURSO)       # contagem zerada: supõe o pior caso (lá embaixo)
            self.referenciar_z(vbusca=20.0)
            self.definir("z", Z_CHAVE)
        except Exception:
            self._corta_energia()
            raise

    def _espera_tmc(self, tentativas=20):
        """o religamento dos relés reinicia os TMC: espera todos responderem e descarta os avisos da partida
        (chegam atrasados e pareceriam uma queda do 24 V no meio do primeiro ciclo)"""
        for _ in range(tentativas):
            if all(p.cmd("st").get("tmci", {"ok": True}).get("ok") for p in self.placas.values()):
                break
            time.sleep(0.2)
        for p in self.placas.values():
            p.eventos.clear()

    # ---- leitura ----
    def st(self, placa):
        return self.placas[placa].cmd("st")

    def posicao(self, eixo):
        e = EIXOS[eixo]
        pk = self.st(e["placa"])["pk"]
        return pk[e["k"]] / e["passos_un"]

    def posicoes(self):
        return {n: round(self.posicao(n), 3) for n in EIXOS}

    # ---- movimento ----
    def definir(self, eixo, valor):
        """diz à placa que o eixo está em `valor` (grau/mm) agora, sem mover"""
        e = EIXOS[eixo]
        self.placas[e["placa"]].cmd("zero", k=e["k"], p=int(round(valor * e["passos_un"])))

    def energizar(self, placa, v=True):
        self.placas[placa].cmd("en", v=1 if v else 0)

    def esperar(self, placa, timeout=120):
        fim = time.time() + timeout
        while time.time() < fim:
            s = self.st(placa)
            if not s["mov"]:
                return s
            time.sleep(0.1)
        self.parar()
        raise TimeoutError("movimento não terminou")

    def ir(self, eixo, alvo, fator=None, esperar=True, checar_limite=True, acel=None):
        """um eixo até `alvo`; `fator` escala velocidade e aceleração configuradas, `acel` (un/s²) fixa a aceleração"""
        e = EIXOS[eixo]
        if checar_limite and not (e["min"] <= alvo <= e["max"]):
            raise ValueError("%s=%.2f fora de [%s, %s]" % (eixo, alvo, e["min"], e["max"]))
        f = self.fator_vel if fator is None else fator
        pl = self.placas[e["placa"]]
        n0 = len(pl.eventos)
        pl.cmd("ir", k=e["k"], p=int(round(alvo * e["passos_un"])),
               v=e["v"] * f * e["passos_un"], a=(e["a"] * f if acel is None else acel) * e["passos_un"])
        if esperar:
            p = self.esperar(e["placa"])["pk"][e["k"]]
            if p != int(round(alvo * e["passos_un"])):
                raise MovimentoAbortado("%s parou em %.2f, alvo %.2f: %s" % (
                    eixo, p / e["passos_un"], alvo, "; ".join(pl.eventos[n0:]) or "sem evento"))

    def ir_juntas(self, j1, j2, vmax=None, amax=None, suave=SUAVE):
        """J1 e J2 juntos (trajetória sincronizada na placa do braço), perfil trapezoidal"""
        alvo = {"j1": j1, "j2": j2}
        for k, v in alvo.items():
            e = EIXOS[k]
            if not (e["min"] <= v <= e["max"]):
                raise ValueError("%s=%.2f fora de [%s, %s]" % (k, v, e["min"], e["max"]))
        pl = self.placas["braco"]
        pk = pl.cmd("st")["pk"]
        ini = {k: pk[EIXOS[k]["k"]] / EIXOS[k]["passos_un"] for k in alvo}
        deltas = {k: alvo[k] - ini[k] for k in alvo}
        if all(abs(d) < 1e-3 for d in deltas.values()):
            return 0.0
        T, f = plano_juntas(ini, alvo, vmax, amax, suave)
        N = max(1, math.ceil(T / DT))
        ws = []
        for k in ("j1", "j2"):
            q = [ini[k] + deltas[k] * s_curva((m + 1) * DT, T, f, suave) for m in range(N)]
            q[-1] = alvo[k]
            w, _ = codifica(q, EIXOS[k]["passos_un"], pk[EIXOS[k]["k"]])
            ws.append(w)
        ks = [EIXOS["j1"]["k"], EIXOS["j2"]["k"]]
        self.tid = getattr(self, "tid", 0) + 1
        r = pl.cmd("tjini", k=ks, tid=self.tid)
        b64 = lambda w: base64.b64encode(struct.pack("<%dI" % len(w), *w)).decode()
        i, iniciou, CH, PRE = 0, False, 120, 150
        try:
            while True:
                while i < N and r["livre"] >= min(CH, N - i):
                    m = min(CH, N - i, r["livre"])
                    fim = i + m >= N
                    go = not iniciou and i + m >= min(N, PRE)
                    r = pl.cmd("tj", w=[b64(ws[0][i:i + m]), b64(ws[1][i:i + m])], fim=fim, go=go, timeout=4)
                    i += m
                    iniciou = iniciou or go
                if i >= N and iniciou:
                    break
                time.sleep(0.12)
                r = pl.cmd("tj", timeout=3)
        except BaseException:
            pl.cmd("parar")        # senão a trajetória fica pendurada e a placa recusa os próximos comandos
            raise
        while True:
            s = pl.cmd("st")
            if not s.get("tj"):
                tjf = s.get("tjf") or {}
                if tjf.get("tid") != self.tid or not tjf.get("ok"):
                    raise RuntimeError("trajetória interrompida: %s" % tjf.get("msg"))
                return T
            time.sleep(0.1)

    def _referenciar(self, eixo, chave, sinal, vbusca, recuo, vfina, curso):
        """anda no sentido `sinal` até a chave (a PIO para no ato), recua e aproxima devagar.
        Devolve a posição (no referencial atual) em que a chave aciona."""
        e = EIXOS[eixo]
        pl = self.placas[e["placa"]]
        spu = e["passos_un"]
        for v, dist in ((vbusca, curso), (vfina, None)):
            if dist is None:
                dist = self._sai_da_chave(eixo, chave, sinal, recuo) + 2
                pl.cmd("mover", k=e["k"], n=int(sinal * dist * spu), v=v * spu, a=20 * spu)
            else:
                try:
                    pl.cmd("mover", k=e["k"], n=int(sinal * dist * spu), v=v * spu, a=20 * spu)
                except RuntimeError as ex:      # já na chave: a placa recusa ("FIM1 acionado bloqueia esse sentido")
                    if "FIM" + chave[-1] not in str(ex):
                        raise
            s = self.esperar(e["placa"], timeout=dist / v + 30)
            if not s[chave]:
                raise RuntimeError("%s andou %.0f sem acionar o fim de curso" % (eixo, dist))
        return self.posicao(eixo)

    def _sai_da_chave(self, eixo, chave, sinal, recuo, passo=1.0, maximo=RECUO_MAX_Z):
        """recua `recuo` e segue de `passo` em `passo` até a chave soltar (folga da alavanca); devolve quanto recuou.
        Se não solta em `maximo`, para: com o DIR do driver falhando o recuo vira subida contra o topo"""
        placa = EIXOS[eixo]["placa"]
        andado = recuo
        self.ir(eixo, self.posicao(eixo) - sinal * recuo, checar_limite=False)
        while self.st(placa)[chave]:
            if andado >= maximo:
                raise RuntimeError("%s recuou %.0f e a chave não soltou" % (eixo, andado))
            self.ir(eixo, self.posicao(eixo) - sinal * passo, checar_limite=False)
            andado += passo
        return andado

    def referenciar_z(self, vbusca=4.0, recuo=6.0, vfina=1.0, curso=None):
        """sobe o Z até o fim de curso de cima (FIM1); devolve a posição (mm) em que a chave aciona.
        Sem `curso`, busca só até FOLGA_BUSCA_Z além de onde a chave deveria estar (se ela falhar, o Z não sobe
        contra o topo); passe `curso` quando a contagem pode estar muito errada (perda de passo)."""
        if curso is None:
            curso = max(Z_CHAVE - self.posicao("z"), 0.0) + FOLGA_BUSCA_Z
        return self._referenciar("z", "f1", 1, vbusca, recuo, vfina, curso)

    def referenciar_j2(self, vbusca=10.0, recuo=3.0, vfina=2.0, curso=280.0):
        """gira o J2 até a chave do lado + (FIM2), define J2 = J2_CHAVE ali e sai de cima dela
        (com a chave acionada a placa não começa trajetória)"""
        self._referenciar("j2", "f2", 1, vbusca, recuo, vfina, curso)
        self.definir("j2", J2_CHAVE)
        self.ir("j2", EIXOS["j2"]["max"], fator=vfina / EIXOS["j2"]["v"])

    def mover(self, eixo, delta, **kw):
        self.ir(eixo, self.posicao(eixo) + delta, **kw)

    def parar(self):
        for p in self.placas.values():
            try:
                p.cmd("parar")
            except Exception as ex:
                print("parar:", ex)

    def emergencia(self):
        for p in self.placas.values():
            try:
                p.cmd("emerg")
            except Exception as ex:
                print("emerg:", ex)

    def soltar(self):
        for p in self.placas.values():
            p.cmd("en", v=0)

    def bomba(self, v):
        """bomba de vácuo: 1 liga (ventosa puxa), 0 desliga"""
        self.reles.ligar("bomba", v)

    def recuperar(self, ex):
        """placa travada: corta a energia dos motores e reinicia a porta USB dela (a contagem dela zera)"""
        try:
            self.reles.desenergizar()
        except Exception as e:
            print("recuperar: não cortou pelos relés (%s): CORTE NA MÃO" % e)
        if reinicia_porta_usb(ex.serie):
            print("placa %s reiniciada pela porta do hub: referencie de novo antes de mover" % ex.nome)
        else:
            print("placa %s fora do hub: desconecte e reconecte o USB dela" % ex.nome)

    def _corta_energia(self):
        try:
            self.reles.desenergizar()
        finally:
            self.reles.fechar()

    def fechar(self):
        try:
            for p in self.placas.values():
                p.fechar()
        finally:
            self._corta_energia()
