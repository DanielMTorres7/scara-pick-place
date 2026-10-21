"""nomes_gemini com o only-vision atual: detectar() devolve a lista de caixas (centro [y, x] em 0..1000)."""
import sys
import types

import numpy as np

import pick_place


def _fake_visao(monkeypatch, retorno):
    vr = types.ModuleType("vision_remedios")
    vr.os = __import__("os")

    class AnalisadorGemini:
        def __init__(self, modelo):
            self.modelo = modelo

        def detectar(self, frame):
            return retorno

    vr.AnalisadorGemini = AnalisadorGemini
    monkeypatch.setitem(sys.modules, "vision_remedios", vr)


def test_detectar_devolve_lista(monkeypatch):
    lidas = [{"centro": [500, 250], "nome": "Micpure"}, {"centro": [100, 900], "nome": "Arpadol"},
             {"centro": [900, 100], "nome": "Alois"}]
    _fake_visao(monkeypatch, lidas)
    f = np.zeros((1000, 2000, 3), np.uint8)
    caixas = [{"centro": (500.0, 500.0)}, {"centro": (1800.0, 100.0)}, {"centro": (200.0, 900.0)}]
    pick_place.nomes_gemini(f, caixas)
    assert [k["nome"] for k in caixas] == ["Micpure", "Arpadol", "Alois"]


def test_detectar_antigo_devolve_par(monkeypatch):
    _fake_visao(monkeypatch, ([{"centro": [500, 250], "nome": "Micpure"}], None))
    caixas = [{"centro": (500.0, 500.0)}]
    pick_place.nomes_gemini(np.zeros((1000, 2000, 3), np.uint8), caixas)
    assert caixas[0]["nome"] == "Micpure"
