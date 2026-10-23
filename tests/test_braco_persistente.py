"""23/10: cada OS abria um PickPlace novo (reinicia o Z, referencia Z e J2, homing do J1) e no fim cortava a energia.
O braço fica aberto entre as OS: só a primeira referencia; erro numa OS fecha tudo e a próxima referencia de novo."""
from braco_persistente import BracoPersistente


class PPFalso:
    criados = 0

    def __init__(self, log):
        PPFalso.criados += 1
        self.log, self.com_nomes = log, None
        self.r = self

    def preparar(self):
        self.log.append(("preparar", self.com_nomes))
        return []

    def bomba(self, v):
        self.log.append(("bomba", v))

    def parar(self):
        self.log.append("parar")

    def fechar(self):
        self.log.append("fechar")


def _braco(log):
    PPFalso.criados = 0
    return BracoPersistente(lambda: PPFalso(log))


def test_segunda_os_usa_o_mesmo_braco_sem_fechar():
    log = []
    b = _braco(log)
    for com_nomes in (True, False):
        ex = b.executor(com_nomes)
        ex.preparar()
        ex.fechar()                                  # fim da OS sem erro
    assert PPFalso.criados == 1
    assert "fechar" not in log                       # energia e conexões continuam
    assert log.count(("bomba", 0)) == 2              # mas a bomba fica desligada entre as OS
    assert ("preparar", True) in log and ("preparar", False) in log


def test_os_com_erro_fecha_e_a_proxima_abre_de_novo():
    log = []
    b = _braco(log)
    ex = b.executor(True)
    ex.preparar()
    ex.parar()                                       # o JobOS chama parar() quando a OS dá erro
    ex.fechar()
    assert "fechar" in log
    b.executor(True).preparar()
    assert PPFalso.criados == 2                      # posição perdida: abre e referencia de novo


def test_encerrar_fecha_o_braco_aberto():
    log = []
    b = _braco(log)
    b.executor(True).fechar()
    b.encerrar()
    assert log[-1] == "fechar"
