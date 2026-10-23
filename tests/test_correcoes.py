"""Mapa de correções aprendidas: desvio sistemático (mm) medido pela câmera em cada ponto da mesa, aplicado já no
primeiro movimento das próximas vezes perto dali."""
import pytest

from correcoes import MapaCorrecoes


def test_sem_dados_nao_corrige(tmp_path):
    assert MapaCorrecoes(tmp_path / "c.json").prever((100, 200)) == (0.0, 0.0)


def test_usa_o_desvio_dos_pontos_perto(tmp_path):
    m = MapaCorrecoes(tmp_path / "c.json")
    m.registrar((100, 200), (4.0, -2.0))
    assert m.prever((110, 205)) == pytest.approx((4.0, -2.0))
    assert m.prever((400, -300)) == (0.0, 0.0)          # longe de tudo: não chuta


def test_media_ponderada_pela_distancia(tmp_path):
    m = MapaCorrecoes(tmp_path / "c.json")
    m.registrar((0, 0), (10.0, 0.0))
    m.registrar((60, 0), (0.0, 0.0))
    dx, _ = m.prever((10, 0))
    assert 8.0 < dx < 10.0                               # bem mais perto do primeiro


def test_salva_e_le_de_volta(tmp_path):
    arq = tmp_path / "c.json"
    m = MapaCorrecoes(arq)
    m.registrar((100, 200), (4.0, -2.0))
    m.salvar()
    assert MapaCorrecoes(arq).prever((100, 200)) == pytest.approx((4.0, -2.0))


def test_ponto_novo_no_mesmo_lugar_substitui_o_antigo(tmp_path):
    m = MapaCorrecoes(tmp_path / "c.json")
    m.registrar((100, 200), (4.0, -2.0))
    m.registrar((102, 201), (1.0, 1.0))
    assert m.prever((101, 200)) == pytest.approx((1.0, 1.0))


def test_aprender_pega_tudo_na_primeira_vez_e_metade_depois(tmp_path):
    """filtra o ruído da medida da ponta (±3-5 mm na XWF) sem demorar a aprender um lugar novo"""
    m = MapaCorrecoes(tmp_path / "c.json")
    m.aprender((100, 200), (8.0, 0.0))                   # lugar novo: aprende tudo
    assert m.prever((100, 200)) == pytest.approx((8.0, 0.0))
    m.aprender((100, 200), (2.0, -4.0))                  # já com o 8 aplicado, ainda sobrou (2, -4): soma metade
    assert m.prever((100, 200)) == pytest.approx((9.0, -2.0))


def test_lugar_novo_nao_e_confiavel(tmp_path):
    assert not MapaCorrecoes(tmp_path / "c.json").confiavel((100, 200))


def test_confiavel_quando_a_ultima_medida_ja_acertou(tmp_path):
    m = MapaCorrecoes(tmp_path / "c.json")
    m.aprender((100, 200), (8.0, 0.0))                  # primeira vez: errou 8 mm
    assert not m.confiavel((100, 200))
    m.aprender((101, 200), (1.0, -1.0))                 # com a correção aplicada, sobrou 1,4 mm
    assert m.confiavel((100, 200))
    assert not m.confiavel((160, 200))                  # longe do ponto medido


def test_volta_a_conferir_depois_de_alguns_pulos(tmp_path):
    from correcoes import MAX_PULOS
    m = MapaCorrecoes(tmp_path / "c.json")
    m.aprender((100, 200), (8.0, 0.0))
    m.aprender((100, 200), (0.5, 0.0))
    for _ in range(MAX_PULOS):
        assert m.confiavel((100, 200))
        m.pulou((100, 200))
    assert not m.confiavel((100, 200))
    m.aprender((100, 200), (0.3, 0.0))                  # conferiu de novo: volta a valer
    assert m.confiavel((100, 200))
