"""Executa uma OS do EMR no braço: foto da mesa -> fila de caixas pedidas -> pega uma a uma, avisando o sistema a
cada caixa solta na coletora. A resposta de cada aviso traz o estado da OS no sistema, que manda:
running = segue; paused = estaciona e espera retomar (nova foto); cancelled/completed = estaciona e encerra.
Faltou caixa na mesa -> avisa "faltando" (o sistema pausa) e espera. Erro -> para os motores, avisa e encerra.

O hardware entra por um Executor (PickPlace): preparar() -> caixas com "nome"/"centro", pegar(caixa, i),
estacionar(), parar(), fechar().
"""
import time

from progresso import reconcilia
from selecao import escolhe_caixas, pendentes
from sistema import SistemaIndisponivel

FIM = ("cancelled", "completed")


class CaixaInalcancavel(ValueError):
    """a caixa está fora do alcance do braço (ou só alcançável batendo na coletora): fica para o "faltando" """


class JobOS:
    def __init__(self, pedido, executor_factory, sistema, progresso, espera_pausa=2.0, dormir=time.sleep):
        self.pedido = pedido
        self.factory = executor_factory
        self.sistema = sistema
        self.progresso = progresso
        self.espera_pausa = espera_pausa
        self.dormir = dormir
        self.itens = pedido["itens"]
        self.quantidade = pedido["quantidade"]
        self.feitos = {}

    @property
    def os(self):
        return self.pedido["os"]

    def _total(self):
        return sum(self.feitos.values())

    def _pendentes(self):
        return pendentes(self.itens, self.quantidade, self.feitos)

    def _evento(self, tipo, **extra):
        try:
            return self.sistema.evento(tipo, self._total(), **extra)
        except SistemaIndisponivel as ex:
            print("OS %s: sistema fora (%s); estaciono e espero" % (self.os, ex))
            return "indisponivel"

    def _espera(self):
        """consulta o sistema até a OS voltar a rodar ou acabar"""
        while True:
            self.dormir(self.espera_pausa)
            try:
                est = self.sistema.estado()
            except SistemaIndisponivel:
                continue
            if est != "paused":
                return est

    def _ciclo(self, ex):
        """uma foto da mesa e as caixas que ela permite pegar; devolve o último estado recebido do sistema"""
        est = "running"
        fila = escolhe_caixas(ex.preparar(), self._pendentes())
        print("OS %s: %d caixas na fila, %d separadas" % (self.os, len(fila), self._total()))
        for i, (caixa, nome) in enumerate(fila):
            try:
                ex.pegar(caixa, i)
            except CaixaInalcancavel as e:
                print("   caixa %s pulada: %s" % (caixa.get("nome", ""), e))
                continue
            self.feitos[nome] = self.feitos.get(nome, 0) + 1
            self.progresso.salva(self.os, self.feitos)
            est = self._evento("unit")
            if est != "running":
                break
        ex.estacionar()
        return est

    def rodar(self):
        p = self.pedido
        self.feitos = reconcilia(self.itens, self.quantidade, p["separadas"], self.progresso.carrega(self.os))
        try:
            ex = self.factory()
        except Exception as e:
            print("OS %s: ERRO ao abrir o braço: %s" % (self.os, e))
            self._erro(e)
            return
        try:
            while True:
                est = self._ciclo(ex) if self._pendentes() else "running"
                if est in FIM:
                    return
                if est == "running":
                    pend = self._pendentes()
                    if not pend:
                        est = self._evento("concluida")
                        if est != "indisponivel":
                            print("OS %s concluída: %d caixas" % (self.os, self._total()))
                            return
                    else:
                        print("OS %s: faltando %s" % (self.os, pend))
                        est = self._evento("faltando", faltando=pend)
                        if est in FIM:
                            return
                if est != "running" and self._espera() in FIM:
                    return
                if self._evento("unit") in FIM:     # retomou: confirma o total (cobre um aviso perdido)
                    return
        except Exception as e:
            print("OS %s: ERRO %s" % (self.os, e))
            ex.parar()
            self._erro(e)
        finally:
            ex.fechar()

    def _erro(self, e):
        try:
            self.sistema.evento("erro", self._total(), mensagem=str(e))
        except SistemaIndisponivel:
            pass
