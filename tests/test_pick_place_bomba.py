"""Bomba: 1 liga (ventosa puxa), 0 desliga. Sem válvula: em repouso fica desligada. Vai pelo relé do Scara."""
import pick_place
from pick_place import RELE_PEGA, RELE_REPOUSO, PickPlace


class Registro:
    def __init__(self, log, nome):
        self.log, self.nome = log, nome

    def bomba(self, v):
        self.log.append(("bomba", v))

    def fechar(self):
        self.log.append(("fechar", self.nome))


def test_repouso_e_bomba_desligada():
    assert (RELE_REPOUSO, RELE_PEGA) == (0, 1)


def test_fechar_desliga_a_bomba_antes_de_fechar_o_scara():
    log = []
    pp = PickPlace.__new__(PickPlace)
    pp.cams, pp.r = {"C920": Registro(log, "cam")}, Registro(log, "scara")
    pp.fechar()
    assert log.index(("bomba", RELE_REPOUSO)) < log.index(("fechar", "scara"))


def test_fechar_fecha_tudo_mesmo_se_o_rele_falhar():
    log = []

    class ScaraQuebrado(Registro):
        def bomba(self, v):
            raise RuntimeError("relés: sem resposta")

    pp = PickPlace.__new__(PickPlace)
    pp.cams, pp.r = {"C920": Registro(log, "cam")}, ScaraQuebrado(log, "scara")
    pp.fechar()
    assert {("fechar", "cam"), ("fechar", "scara")} <= set(log)
    assert pick_place  # módulo importável sem hardware


def test_fecha_todas_as_cameras():
    log = []
    pp = PickPlace.__new__(PickPlace)
    pp.cams = {"C920": Registro(log, "c920"), "XWF": Registro(log, "xwf")}
    pp.r = Registro(log, "scara")
    pp.fechar()
    assert {("fechar", "c920"), ("fechar", "xwf")} <= set(log)


def test_solta_desliga_a_bomba_1s_antes_de_chegar_e_espera_1s():
    """23/10: sem válvula e com a mangueira longa, desligar só ao chegar (e 0,5 s de espera) não dava tempo do vácuo
    acabar: a caixa não caía. Desliga 1 s antes da chegada em cima da coletora e espera mais 1 s lá."""
    # 23/10, 2ª rodada: com 1 s antes a caixa caiu 1-2 s depois de chegar -> 2 s antes e 0,5 s de espera
    # 3ª: com 2 s antes caiu na hora de chegar, quase fora -> 1 s antes e 1,5 s de espera (sair de cima no mesmo ponto)
    assert pick_place.SOLTA_ANTES == 1.0 and pick_place.PAUSA_SOLTA == 1.5
    # chegada = a última das duas (juntas e Z, cada uma depois do seu atraso)
    assert pick_place.instante_soltar(T=2.0, tz=1.3, atraso_j=0.2, atraso_z=0.0, antes=1.0) == 1.2
    assert pick_place.instante_soltar(T=1.0, tz=1.5, atraso_j=0.0, atraso_z=0.4, antes=1.0) == 0.9
    assert pick_place.instante_soltar(T=0.5, tz=0.3, atraso_j=0.0, atraso_z=0.0, antes=1.0) == 0.0
