"""Correções aprendidas da mira: o desvio sistemático (mm) entre onde o modelo manda a ponta e onde a câmera a vê,
por ponto da mesa. Aplicado antes do primeiro movimento, a mira passa a só confirmar (sem segundo movimento).

Lugar confiável (última medida, já corrigida, errou <= CONFIAVEL_MM): a mira pode ser pulada, até MAX_PULOS vezes
seguidas; depois confere de novo.

Arquivo JSON: [{"xy": [x, y], "d": [dx, dy], "ultimo": mm, "pulos": n}, ...] no referencial do robô.
"""
import json
import math

RAIO = 120.0        # mm: só pontos aprendidos até essa distância influenciam
MESMO_PONTO = 15.0  # mm: medida nova tão perto de uma antiga a substitui
MAX_PONTOS = 300
CONFIAVEL_MM = 2.0  # última medida (com a correção aplicada) até isso: dá para pular a mira ali
MAX_PULOS = 5       # pulos seguidos num lugar antes de conferir de novo
GANHO = 0.5         # fração do desvio medido somada ao que já se sabia do lugar (filtra o ruído da medida)


class MapaCorrecoes:
    def __init__(self, arq):
        self.arq = arq
        try:
            self.pontos = json.load(open(arq))
        except FileNotFoundError:
            self.pontos = []

    def prever(self, xy):
        """desvio (dx, dy) para somar ao alvo: média dos vizinhos ponderada por 1/d²"""
        soma, sx, sy = 0.0, 0.0, 0.0
        for p in self.pontos:
            d = math.dist(p["xy"], xy)
            if d > RAIO:
                continue
            w = 1.0 / max(d, 1.0) ** 2
            soma += w
            sx += w * p["d"][0]
            sy += w * p["d"][1]
        return (sx / soma, sy / soma) if soma else (0.0, 0.0)

    def aprender(self, xy, desvio):
        """`desvio`: o que ainda sobrou com a correção aprendida aplicada. Lugar novo aprende tudo; conhecido, só
        GANHO dele"""
        conhecido = any(math.dist(p["xy"], xy) <= RAIO for p in self.pontos)
        base = self.prever(xy)
        g = GANHO if conhecido else 1.0
        self.registrar(xy, (base[0] + g * desvio[0], base[1] + g * desvio[1]))
        self.pontos[-1]["ultimo"] = round(math.hypot(*desvio), 2)
        self.pontos[-1]["pulos"] = 0

    def _no_lugar(self, xy):
        perto = [p for p in self.pontos if math.dist(p["xy"], xy) <= MESMO_PONTO]
        return min(perto, key=lambda p: math.dist(p["xy"], xy)) if perto else None

    def confiavel(self, xy):
        """a última medida aqui (com a correção aplicada) acertou e ainda não foi pulada demais"""
        p = self._no_lugar(xy)
        return p is not None and p.get("ultimo", 99.0) <= CONFIAVEL_MM and p.get("pulos", 0) < MAX_PULOS

    def pulou(self, xy):
        p = self._no_lugar(xy)
        if p is not None:
            p["pulos"] = p.get("pulos", 0) + 1

    def registrar(self, xy, d):
        self.pontos = [p for p in self.pontos if math.dist(p["xy"], xy) > MESMO_PONTO]
        self.pontos.append({"xy": [round(float(xy[0]), 1), round(float(xy[1]), 1)],
                            "d": [round(float(d[0]), 2), round(float(d[1]), 2)]})
        self.pontos = self.pontos[-MAX_PONTOS:]

    def salvar(self):
        json.dump(self.pontos, open(self.arq, "w"), indent=1)
