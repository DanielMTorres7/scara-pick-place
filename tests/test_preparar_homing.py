"""O homing (Z e J2 pelas chaves, J1 conferido pela visão) roda uma vez por execução (no primeiro preparar), não a
cada foto/caixa. O J1 vem do alinhamento à mão; a visão só confere e não para o robô (23/10: mesa com caixas embaixo
das poses do homing)."""
import homing
import pick_place
from pick_place import PickPlace


class ScaraFalso:
    def __init__(self, log=None):
        self.placas = {}
        self.log = log if log is not None else []

    def referenciar_z(self, **kw):
        self.log.append("ref_z")
        return 100.0

    def referenciar_j2(self, **kw):
        self.log.append("ref_j2")

    def ir_juntas(self, j1, j2, **kw):
        self.log.append(("juntas", j1))

    def definir(self, eixo, valor):
        self.log.append(("definir", eixo, valor))

    def ir(self, eixo, alvo, **kw):
        self.log.append(("ir", eixo, alvo))

    def bomba(self, v):
        pass

    def posicao(self, eixo):
        return 100.0


def test_homing_so_no_primeiro_preparar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(pick_place, "homing_j1", lambda *a, **kw: chamadas.append("homing") or (0.0, 0.0))
    monkeypatch.setattr(pick_place, "fotos", lambda r, cams, prefixo: {})
    monkeypatch.setattr(pick_place, "pontos_alcancaveis", lambda m, solta: solta)
    pp = PickPlace.__new__(PickPlace)
    pp.r, pp.cams, pp.ms, pp.m, pp.com_nomes = ScaraFalso(chamadas), {}, {}, None, False
    pp._homing_feito = False
    pp.planejar = lambda fs: ({"cam": "C920", "cantos": []}, [], [(0.0, 0.0)], (0.0, 0.0, 100.0))
    pp.preparar()
    pp.preparar()
    assert chamadas == ["ref_z", ("definir", "z", pick_place.Z_CHAVE), ("ir", "z", pick_place.Z_ALTO), "ref_j2",
                        "homing", ("juntas", 0.0)]     # depois do homing o J1 vai ao 0 corrigido (o user confere reto)
    assert pick_place.Z_ALTO == homing.Z            # o homing do J1 projeta a ponta nessa altura


def test_homing_do_j1_sem_ponta_para_o_pick_place(monkeypatch):
    """23/10: a placa do braço reiniciou na troca do hub (J1 zerado com o braço em outro lugar); o homing não achou a
    ponta, o pick_place seguiu "com o alinhamento à mão" e o J1 passou dos limites. Sem confirmar o J1, nada se move."""
    import pytest

    def falha(*a, **kw):
        raise homing.HomingFalhou("ponta não encontrada em nenhuma pose do homing")
    monkeypatch.setattr(pick_place, "homing_j1", falha)
    monkeypatch.setattr(pick_place, "fotos", lambda r, cams, prefixo: {})
    pp = PickPlace.__new__(PickPlace)
    pp.r, pp.cams, pp.ms, pp.m, pp.com_nomes = ScaraFalso(), {}, {}, None, False
    pp._homing_feito = False
    with pytest.raises(homing.HomingFalhou, match="alinhe o J1"):
        pp.preparar()


def test_homing_do_j1_que_discorda_para_o_pick_place(monkeypatch):
    """23/10: as câmeras mediram +1,27 e +5,51 (J1 tinha saído do lugar numa batida); seguir com o alinhamento à mão
    levou o braço a pegar no vazio e soltar fora da coletora. Medida que discorda/fora = para."""
    import pytest

    def discorda(*a, **kw):
        raise homing.HomingFalhou("as medidas discordam no desvio do J1 (+1.27, +5.51°): alguma detecção errada")
    monkeypatch.setattr(pick_place, "homing_j1", discorda)
    monkeypatch.setattr(pick_place, "fotos", lambda r, cams, prefixo: {})
    pp = PickPlace.__new__(PickPlace)
    pp.r, pp.cams, pp.ms, pp.m, pp.com_nomes = ScaraFalso(), {}, {}, None, False
    pp._homing_feito = False
    with pytest.raises(homing.HomingFalhou, match="alinhe o J1"):
        pp.preparar()
