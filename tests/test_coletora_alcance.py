"""Pontos de soltura na coletora: só os que o braço alcança; nenhum = erro claro (não "remédio faltando")."""
import pytest

from modelo import Modelo
from pick_place import ColetoraForaDoAlcance, pontos_alcancaveis


@pytest.fixture
def m():
    return Modelo()


def test_filtra_pontos_perto_demais_da_base(m):
    longe, perto = (0.0, 350.0), (0.0, 150.0)       # 150 mm do eixo: o J2 não dobra tanto (limite -112°)
    assert pontos_alcancaveis(m, [perto, longe]) == [longe]


def test_nenhum_ponto_alcancavel_e_erro_claro(m):
    with pytest.raises(ColetoraForaDoAlcance, match="coletora"):
        pontos_alcancaveis(m, [(-47.0, -173.0), (0.0, 600.0)])
