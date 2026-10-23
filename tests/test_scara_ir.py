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


class PlacaTjRecusa:
    """aceita o tjini mas recusa o tj (ex.: fim de curso acionado), como a placa faz"""

    def __init__(self):
        self.cmds = []
        self.eventos = []

    def cmd(self, c, **kw):
        self.cmds.append(c)
        if c == "st":
            return {"ok": 1, "pk": {"dm556": 0, "tmc": 0}}
        if c == "tjini":
            return {"ok": 1, "livre": 1000}
        if c == "tj":
            raise RuntimeError("tj: FIM2 acionado: trajetória não começa")
        return {"ok": 1}


def test_ir_juntas_cancela_a_trajetoria_se_o_envio_falhar():
    pl = PlacaTjRecusa()
    r = _scara(pl)
    with pytest.raises(RuntimeError, match="não começa"):
        r.ir_juntas(10, 10)
    assert pl.cmds[-1] == "parar"      # sem isso a placa fica com a trajetória pendurada e recusa o próximo comando


class PlacaRegistra(PlacaFalsa):
    def cmd(self, c, **kw):
        if c == "ir":
            self.ultimo_ir = kw
        return super().cmd(c, **kw)


def test_ir_com_aceleracao_fixa():
    """o Z do pick_place: velocidade maior com a aceleração testada (150 mm/s²), não escalada junto"""
    pl = PlacaRegistra(scara.EIXOS["z"]["k"])
    r = object.__new__(scara.Scara)
    r.placas, r.fator_vel = {"z": pl}, 1.0
    spu = scara.EIXOS["z"]["passos_un"]
    r.ir("z", 10, fator=60 / scara.EIXOS["z"]["v"], acel=150.0)
    assert pl.ultimo_ir["v"] == pytest.approx(60 * spu) and pl.ultimo_ir["a"] == pytest.approx(150 * spu)
