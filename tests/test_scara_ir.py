import pytest

import scara


class PlacaFalsa:
    """aceita o `ir` e para em `para_em` passos (None = chega no alvo), como a placa faz ao abortar"""

    def __init__(self, k, para_em=None, evento=None):
        self.k, self.para_em, self.evento = k, para_em, evento
        self.pk = 0
        self.eventos = []

    def cmd(self, c, **kw):
        if c == "ir":
            self.pk = kw["p"] if self.para_em is None else self.para_em
            if self.evento:
                self.eventos.append(self.evento)
        return {"ok": 1, "mov": "", "pk": {"dm556": 0, "tmc": 0, self.k: self.pk}}


def _scara(placa):
    r = object.__new__(scara.Scara)
    r.placas = {"braco": placa}
    r.fator_vel = 0.2
    return r


def test_ir_chega_no_alvo():
    r = _scara(PlacaFalsa("dm556"))
    r.ir("j1", 5)
    assert r.placas["braco"].pk == round(5 * scara.EIXOS["j1"]["passos_un"])


def test_ir_levanta_se_a_placa_abortar_o_movimento():
    r = _scara(PlacaFalsa("dm556", para_em=0, evento="24 V caiu durante o movimento: parada imediata"))
    with pytest.raises(scara.MovimentoAbortado, match="24 V caiu"):
        r.ir("j1", 5)


def test_ir_sem_esperar_nao_confere():
    r = _scara(PlacaFalsa("dm556", para_em=0))
    r.ir("j1", 5, esperar=False)
