"""Relé da bomba: 1 liga a bomba (ventosa puxa), 0 desliga. Sem válvula: em repouso a bomba fica desligada."""
import pick_place
from pick_place import RELE_PEGA, RELE_REPOUSO, PickPlace


class Registro:
    def __init__(self, log, nome):
        self.log, self.nome = log, nome

    def rele(self, v):
        self.log.append(("rele", v))

    def fechar(self):
        self.log.append(("fechar", self.nome))


def test_repouso_e_bomba_desligada():
    assert (RELE_REPOUSO, RELE_PEGA) == (0, 1)


def test_fechar_desliga_a_bomba_antes_de_soltar_a_porta():
    log = []
    pp = PickPlace.__new__(PickPlace)
    pp.c, pp.r, pp.bomba = Registro(log, "cam"), Registro(log, "scara"), Registro(log, "bomba")
    pp.fechar()
    assert log.index(("rele", RELE_REPOUSO)) < log.index(("fechar", "bomba"))


def test_fechar_fecha_tudo_mesmo_se_o_rele_falhar():
    log = []

    class BombaQuebrada(Registro):
        def rele(self, v):
            raise RuntimeError("bomba: sem resposta")

    pp = PickPlace.__new__(PickPlace)
    pp.c, pp.r, pp.bomba = Registro(log, "cam"), Registro(log, "scara"), BombaQuebrada(log, "bomba")
    pp.fechar()
    assert {("fechar", "cam"), ("fechar", "scara"), ("fechar", "bomba")} <= set(log)
    assert pick_place  # módulo importável sem hardware
