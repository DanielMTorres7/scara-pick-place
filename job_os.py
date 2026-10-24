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
MAX_FOTOS_TODAS = 10    # modo "todas": uma caixa que nunca sai da mesa (pega falhando) não prende o braço em laço


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
        self.encerrando = False     # decidiu sair (cancelada/concluída/erro): o servidor espera e aceita outra OS
        # "todas" (botão "separar tudo" do sistema): sem lista nem quantidade, pega o que detectar até a mesa esvaziar
        self.todas = bool(pedido.get("todas"))
        self._mesa_vazia = False
        self._fotos = 0

    @property
    def os(self):
        return self.pedido["os"]

    def _total(self):
        return sum(self.feitos.values())

    def _pendentes(self):
        if self.todas:                 # qualquer caixa, enquanto a última foto ainda deu alguma para pegar
            return [] if self._mesa_vazia else [{"nome": "", "faltam": 10 ** 6}]
        return pendentes(self.itens, self.quantidade, self.feitos)

    def _evento(self, tipo, **extra):
        try:
            est = self.sistema.evento(tipo, self._total(), **extra)
        except SistemaIndisponivel as ex:
            print("OS %s: sistema fora (%s); estaciono e espero" % (self.os, ex))
            return "indisponivel"
        self.encerrando = est in FIM
        return est

    def _estado(self):
        try:
            est = self.sistema.estado()
        except SistemaIndisponivel:
            return "indisponivel"
        self.encerrando = est in FIM
        return est

    def _espera(self):
        """consulta o sistema até a OS voltar a rodar ou acabar"""
        while True:
            self.dormir(self.espera_pausa)
            est = self._estado()
            if est not in ("paused", "indisponivel"):
                return est

    def _ciclo(self, ex):
        """uma foto da mesa e as caixas que ela permite pegar; devolve o último estado recebido do sistema"""
        caixas = ex.preparar()
        est = self._estado()            # a foto e o Gemini levam segundos: a OS pode ter mudado
        if est != "running":
            ex.estacionar()
            return est
        livres = list(caixas)
        print("OS %s: %d caixas na mesa, %d separadas" % (self.os, len(livres), self._total()))
        i = 0
        while True:
            fila = escolhe_caixas(livres, self._pendentes())
            if not fila:
                break
            caixa, nome = fila[0]
            livres = [k for k in livres if k is not caixa]   # pega ou não, essa caixa sai da mesa da vez
            try:
                ex.pegar(caixa, i)
            except CaixaInalcancavel as e:
                print("   caixa %s pulada: %s" % (caixa.get("nome", ""), e))
                continue
            i += 1
            self.feitos[nome] = self.feitos.get(nome, 0) + 1
            self.progresso.salva(self.os, self.feitos)
            est = self._evento("unit")
            if est != "running":
                break
        ex.estacionar()
        if self.todas:
            self._fotos += 1
            self._mesa_vazia = i == 0 or self._fotos >= MAX_FOTOS_TODAS
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
                if est == "running":
                    pend = self._pendentes()
                    if self.todas and pend:
                        continue                # "separar tudo": a mesa ainda tinha caixas, foto de novo
                    if not pend:
                        est = self._evento("concluida")
                        if est != "indisponivel":
                            print("OS %s concluída: %d caixas" % (self.os, self._total()))
                            self.encerrando = True
                            return
                    else:
                        print("OS %s: faltando %s" % (self.os, pend))
                        est = self._evento("faltando", faltando=pend)
                # só volta a pegar depois que o sistema confirmar o total com a OS rodando
                while est != "running":
                    if est in FIM:
                        return
                    if self._espera() in FIM:
                        return
                    est = self._evento("unit")
        except Exception as e:
            print("OS %s: ERRO %s" % (self.os, e))
            self.encerrando = True
            ex.parar()
            self._erro(e)
        finally:
            self.encerrando = True
            ex.fechar()

    def _erro(self, e):
        self.encerrando = True
        try:
            self.sistema.evento("erro", self._total(), mensagem=str(e))
        except SistemaIndisponivel:
            pass
