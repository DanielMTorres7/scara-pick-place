"""Fins de curso (fiação de 2026-10-22): Z cima = FIM1, Z baixo = FIM2; J2 lado + (xadrez) = FIM2, lado - = FIM1.
As chaves do J2 ficam em ±130,5°."""
import pytest

import modelo
import scara


class PlacaFalsa:
    """aciona a chave `chave` quando o eixo passa de `aciona` (passos) no sentido do movimento"""

    def __init__(self, k, chave, aciona, sinal):
        self.k, self.chave, self.aciona, self.sinal = k, chave, aciona, sinal
        self.p = 0
        self.cmds = []
        self.eventos = []

    def _st(self):
        f = int(self.sinal * self.p >= self.sinal * self.aciona)
        return {"ok": 1, "mov": "", "pk": {"dm556": 0, "tmc": 0, self.k: self.p},
                "f1": f if self.chave == "f1" else 0, "f2": f if self.chave == "f2" else 0}

    def cmd(self, c, **kw):
        self.cmds.append((c, kw))
        if c == "mover":
            alvo = self.p + kw["n"]
            if (alvo - self.aciona) * self.sinal >= 0 > (self.p - self.aciona) * self.sinal:
                alvo = self.aciona
            self.p = alvo
        elif c == "ir":
            self.p = kw["p"]
        elif c == "zero":
            self.p = kw["p"]
        return self._st()


def _scara(placas):
    r = object.__new__(scara.Scara)
    r.placas = placas
    r.fator_vel = 0.2
    return r


def test_scara_configura_as_chaves_das_duas_placas(monkeypatch):
    cmds = {}

    class Registro:
        def __init__(self, p):
            self.nome = p
            self.eventos = []
            cmds[p] = []

        def cmd(self, c, **kw):
            cmds[self.nome].append((c, kw))
            return {}

        def reiniciar(self):
            pass

    class Reles:
        def energizar(self):
            pass

    monkeypatch.setattr(scara, "acha_portas", lambda: {"braco": "braco", "z": "z"})
    monkeypatch.setattr(scara, "Reles", Reles)
    monkeypatch.setattr(scara, "Placa", Registro)
    monkeypatch.setattr(scara.Scara, "referenciar_z", lambda self, **kw: scara.Z_CHAVE)
    scara.Scara()
    assert ("fim", {"f1": 1, "f2": -1}) in cmds["z"]          # cima (FIM1) bloqueia subir, baixo (FIM2) descer
    assert ("fim", {"f1": -1, "f2": 1}) in cmds["braco"]      # FIM1 no lado -, FIM2 no lado + do J2


def test_referenciar_z_sobe_ate_o_fim1():
    spu = scara.EIXOS["z"]["passos_un"]
    pl = PlacaFalsa("dm556", "f1", aciona=int(50 * spu), sinal=1)
    r = _scara({"z": pl})
    assert r.referenciar_z() == pytest.approx(50, abs=0.01)


def test_z_anda_pelo_dm556_a_400_passos_por_mm():
    """Z no DM556 da placa do Z (3200 passos/volta, fuso de 8 mm); sentido acertado com inv_dir na placa"""
    assert scara.EIXOS["z"]["k"] == "dm556"
    assert scara.EIXOS["z"]["passos_un"] == 400


def test_referenciar_j2_vai_ate_o_fim2_e_define_130_5():
    spu = scara.EIXOS["j2"]["passos_un"]
    pl = PlacaFalsa("tmc", "f2", aciona=int(40 * spu), sinal=1)
    r = _scara({"braco": pl})
    r.referenciar_j2()
    spu_ = scara.EIXOS["j2"]["passos_un"]
    assert ("zero", {"k": "tmc", "p": round(scara.J2_CHAVE * spu_)}) in pl.cmds    # a chave vira +130,5°
    assert r.posicao("j2") == pytest.approx(scara.EIXOS["j2"]["max"], abs=0.01)   # e sai de cima dela
    assert scara.J2_CHAVE == 130.5


def test_limites_do_j2_ficam_dentro_das_chaves():
    e = scara.EIXOS["j2"]
    assert -scara.J2_CHAVE < e["min"] and e["max"] < scara.J2_CHAVE
    m = object.__new__(modelo.Modelo)
    m.L1, m.L2, m.o2 = 300.0, 200.0, 0.0
    for j1, j2 in m.ik_todas(*m.fk(0, 129.5)):
        assert abs(j2) < scara.J2_CHAVE - 1


def test_altura_da_mesa_bate_com_a_ventosa_encostando_na_caixa():
    """2026-10-23: a ventosa encosta numa caixa de 30 mm com o Z em -84 (mesa 6 mm mais alta que em 22/10)"""
    assert modelo.Z_TOQUE_MESA + modelo.ALTURA_CAIXA == -84.0
    assert scara.Z_TOQUE_MESA == modelo.Z_TOQUE_MESA


class PlacaJaNaChave(PlacaFalsa):
    """como a placa real: com a chave acionada, recusa mover para o lado dela"""

    def cmd(self, c, **kw):
        if c == "mover" and self._st()[self.chave] and kw["n"] * self.sinal > 0:
            raise RuntimeError("mover: FIM%s acionado bloqueia esse sentido" % self.chave[-1])
        return super().cmd(c, **kw)


def test_referenciar_z_comecando_em_cima_da_chave():
    spu = scara.EIXOS["z"]["passos_un"]
    pl = PlacaJaNaChave(scara.EIXOS["z"]["k"], "f1", aciona=int(50 * spu), sinal=1)
    pl.p = int(51 * spu)
    r = _scara({"z": pl})
    assert r.referenciar_z() == pytest.approx(50, abs=0.01)


class PlacaHisterese(PlacaJaNaChave):
    """chave real (23/10): aciona em `aciona` subindo, mas só solta `hist` passos abaixo"""

    def __init__(self, *a, hist, **kw):
        super().__init__(*a, **kw)
        self.hist, self.preso = hist, False

    def _st(self):
        st = super()._st()
        f = st[self.chave] or (self.preso and self.p > self.aciona - self.hist)
        st[self.chave] = int(f)
        return st

    def cmd(self, c, **kw):
        r = super().cmd(c, **kw)
        self.preso = bool(self._st()[self.chave])
        return r


def test_referenciar_z_recua_ate_a_chave_soltar_e_aproxima_devagar():
    """23/10: o recuo de 3 mm não soltava a chave (solta só com ~6 mm), a aproximação lenta era recusada em silêncio e o
    Z ficava referenciado 3 mm abaixo da chave"""
    spu = scara.EIXOS["z"]["passos_un"]
    pl = PlacaHisterese(scara.EIXOS["z"]["k"], "f1", aciona=int(50 * spu), sinal=1, hist=int(6 * spu))
    r = _scara({"z": pl})
    assert r.referenciar_z(vfina=1.0) == pytest.approx(50, abs=0.01)
    finos = [kw for c, kw in pl.cmds if c == "mover" and kw["v"] == 1.0 * spu]
    assert len(finos) == 1                      # a aproximação lenta aconteceu
    assert min(p for c, kw in pl.cmds if c == "ir" for p in [kw["p"]]) <= 44 * spu   # recuou além da histerese


def test_referenciar_z_avisa_se_a_chave_nao_solta():
    spu = scara.EIXOS["z"]["passos_un"]
    pl = PlacaHisterese(scara.EIXOS["z"]["k"], "f1", aciona=int(50 * spu), sinal=1, hist=int(100 * spu))
    r = _scara({"z": pl})
    with pytest.raises(RuntimeError, match="não soltou"):
        r.referenciar_z()
    # 23/10: com o DIR do DM556 em mau contato o "recuo" sobe; desiste cedo para o Z não ir longe contra o topo
    assert min(kw["p"] for c, kw in pl.cmds if c == "ir") >= 50 * spu - scara.RECUO_MAX_Z * spu
    assert scara.RECUO_MAX_Z <= 10


def test_referenciar_z_desce_6_mm_entre_os_cliques():
    """23/10: o user pediu mais descida entre o 1º e o 2º clique (antes 3 mm)"""
    spu = scara.EIXOS["z"]["passos_un"]
    pl = PlacaFalsa(scara.EIXOS["z"]["k"], "f1", aciona=int(50 * spu), sinal=1)
    r = _scara({"z": pl})
    assert r.referenciar_z() == pytest.approx(50, abs=0.01)
    recuo = [kw["p"] for c, kw in pl.cmds if c == "ir"][0]
    assert recuo == pytest.approx(44 * spu, abs=1)


def test_referenciar_z_nao_passa_muito_da_chave_se_ela_falhar():
    """23/10: o Z subiu além da chave no referenciamento (buscava até 260 mm, e do alto só há ~25 mm até ela).
    A busca vai só até um pouco depois de onde a chave deveria estar; sem ela, para e avisa."""
    spu = scara.EIXOS["z"]["passos_un"]
    pl = PlacaFalsa(scara.EIXOS["z"]["k"], "f1", aciona=int(500 * spu), sinal=1)   # chave nunca aciona
    pl.p = int(75 * spu)
    r = _scara({"z": pl})
    with pytest.raises(RuntimeError, match="sem acionar"):
        r.referenciar_z()
    n = [kw["n"] for c, kw in pl.cmds if c == "mover"][0]
    assert n / spu <= scara.Z_CHAVE - 75 + scara.FOLGA_BUSCA_Z + 0.01
    assert scara.FOLGA_BUSCA_Z <= 15


class PlacaZReinicia(PlacaFalsa):
    """placa do Z que zera a contagem ao reiniciar; o Z está fisicamente em `z_real` (mm)"""

    def __init__(self, z_real):
        spu = scara.EIXOS["z"]["passos_un"]
        super().__init__(scara.EIXOS["z"]["k"], "f1", aciona=int((scara.Z_CHAVE - z_real) * spu), sinal=1)
        self.reiniciou = False

    def reiniciar(self):
        self.reiniciou = True
        self.cmds.append(("reiniciar", {}))
        self.p = 0

    def cmd(self, c, **kw):
        if c == "zero":                      # muda só a contagem: a chave continua no mesmo lugar físico
            self.aciona += kw["p"] - self.p
        return super().cmd(c, **kw)


@pytest.mark.parametrize("z_real", [-91.0, 0.0, 99.0])
def test_scara_reinicia_a_placa_do_z_e_referencia_antes_de_mover(monkeypatch, z_real):
    """23/10: com a placa do Z ligada havia horas, a chave de cima deixou de parar o motor (a placa achava que tinha
    parado e o Z seguia subindo); reiniciada, voltou a parar. O Scara reinicia a placa e referencia o Z ao abrir,
    buscando a chave pelo curso todo (a contagem zerou), sem passar muito dela."""
    z = PlacaZReinicia(z_real)

    class Braco:
        eventos = []

        def cmd(self, c, **kw):
            return {}

    class Reles:
        def energizar(self):
            pass

    monkeypatch.setattr(scara, "acha_portas", lambda: {"braco": "braco", "z": "z"})
    monkeypatch.setattr(scara, "Reles", Reles)
    monkeypatch.setattr(scara, "Placa", lambda p: z if p == "z" else Braco())
    r = scara.Scara()
    nomes = [c for c, _ in z.cmds]
    assert nomes.index("reiniciar") < nomes.index("mover")
    assert r.posicao("z") == pytest.approx(scara.Z_CHAVE, abs=0.01)
    spu = scara.EIXOS["z"]["passos_un"]
    n = [kw["n"] for c, kw in z.cmds if c == "mover"][0]
    assert n / spu <= scara.Z_CURSO + scara.FOLGA_BUSCA_Z + 0.01
