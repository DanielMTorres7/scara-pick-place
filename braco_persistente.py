"""Braço aberto entre as OS do servidor: só a primeira OS abre o PickPlace (reinicia o Z, referencia Z e J2, homing do
J1); as seguintes reaproveitam a mesma instância, com os motores energizados segurando a posição. OS que termina bem só
desliga a bomba; OS com erro (o JobOS chama parar()) fecha tudo e a próxima abre e referencia de novo."""
import threading

RELE_REPOUSO = 0   # = pick_place.RELE_REPOUSO (sem importar o pick_place, que puxa OpenCV e câmeras)


class _Executor:
    """o que o JobOS usa (preparar/pegar/estacionar/parar/fechar), em cima do PickPlace guardado"""

    def __init__(self, braco, pp):
        self._braco, self._pp, self._falhou = braco, pp, False

    def __getattr__(self, nome):                   # preparar, pegar, estacionar
        return getattr(self._pp, nome)

    def parar(self):
        self._falhou = True
        self._pp.parar()

    def fechar(self):
        if self._falhou:
            self._braco._descarta(self._pp)
            return
        try:
            self._pp.r.bomba(RELE_REPOUSO)
        except Exception as ex:                    # relé mudo: fecha tudo (corta a energia) e a próxima OS reabre
            print("bomba: não desligou (%s): fechando o braço" % ex)
            self._braco._descarta(self._pp)


class BracoPersistente:
    def __init__(self, fabrica):
        self._fabrica, self._pp, self._trava = fabrica, None, threading.Lock()

    def executor(self, com_nomes):
        with self._trava:
            if self._pp is None:
                self._pp = self._fabrica()
            self._pp.com_nomes = com_nomes
            return _Executor(self, self._pp)

    def _descarta(self, pp):
        with self._trava:
            if self._pp is pp:
                self._pp = None
        pp.fechar()

    def encerrar(self):
        """servidor saindo: fecha o braço aberto (bomba, câmeras, energia)"""
        with self._trava:
            pp, self._pp = self._pp, None
        if pp is not None:
            pp.fechar()
