"""Mira: mede o erro da ponta pela câmera e devolve as juntas corrigidas e o desvio medido, sem mover (a correção vai
junto com a descida). Medida absurda (> MAX_CORRECAO) é refeita; se continuar absurda, não corrige nem aprende."""
import pick_place
from pick_place import MAX_CORRECAO, PickPlace


class ModeloFalso:
    def fk(self, j1, j2):
        return j1, j2                      # juntas = mm: facilita as contas

    def ik(self, x, y, ref=None, livre=None):
        return x, y


class ScaraFalso:
    def __init__(self):
        self.movimentos = []

    def posicao(self, eixo):
        return -65.0

    def ir_juntas(self, *a, **kw):
        self.movimentos.append(a)


def _pp(monkeypatch, medidas):
    pp = PickPlace.__new__(PickPlace)
    pp.m, pp.r, pp.ms, pp.cams, pp.obstaculo = ModeloFalso(), ScaraFalso(), {}, {}, None
    fila = list(medidas)
    pp.procurou = []

    def ponta_xy(cams, ms, xy, z):
        pp.procurou.append(xy)
        return fila.pop(0)
    monkeypatch.setattr(pick_place, "ponta_xy", ponta_xy)
    return pp


def test_corrige_sem_mover(monkeypatch):
    pp = _pp(monkeypatch, [("C920", 95.0, 52.0)])            # ponta caiu 5 mm antes em x e 2 mm depois em y
    assert pp.mira(100.0, 50.0, (100.0, 50.0)) == ((105.0, 48.0), (5.0, -2.0))
    assert pp.r.movimentos == []


def test_erro_pequeno_nao_corrige(monkeypatch):
    pp = _pp(monkeypatch, [("C920", 99.0, 50.5)])
    assert pp.mira(100.0, 50.0, (100.0, 50.0)) == ((100.0, 50.0), (1.0, -0.5))   # não move, mas aprende


def test_medida_absurda_e_refeita(monkeypatch):
    pp = _pp(monkeypatch, [("XWF", 100.0 + MAX_CORRECAO + 5, 50.0), ("XWF", 97.0, 50.0)])
    assert pp.mira(100.0, 50.0, (100.0, 50.0)) == ((103.0, 50.0), (3.0, 0.0))


def test_duas_medidas_absurdas_nao_corrige(monkeypatch):
    pp = _pp(monkeypatch, [("XWF", 100.0 + MAX_CORRECAO + 5, 50.0), ("XWF", 100.0 - MAX_CORRECAO - 5, 50.0)])
    assert pp.mira(100.0, 50.0, (100.0, 50.0)) == ((100.0, 50.0), None)


def test_procura_a_ponta_em_cima_da_caixa_mesmo_com_desvio_aprendido(monkeypatch):
    """com o desvio aprendido as juntas apontam para outro lugar do modelo; a ponta de verdade deve estar na caixa"""
    pp = _pp(monkeypatch, [("XWF", 100.0, 50.0)])
    pp.mira(100.0, 50.0, (112.0, 41.0))
    assert pp.procurou == [(100.0, 50.0)]


def test_correcao_fora_do_alcance_segue_sem_corrigir(monkeypatch):
    """perto do limite do alcance, o ponto corrigido pode não ter solução: não derruba o ciclo"""
    pp = _pp(monkeypatch, [("XWF", 95.0, 50.0)])

    def ik(x, y, ref=None, livre=None):
        raise ValueError("sem solução livre dentro dos limites")
    pp.m.ik = ik
    assert pp.mira(100.0, 50.0, (100.0, 50.0)) == ((100.0, 50.0), (5.0, 0.0))
