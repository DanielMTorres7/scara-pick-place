"""Calibração pelo botão do sistema (servidor_os POST /calibrar): soltar / referenciar o braço / recalibrar câmeras."""
import json

import calibracao


class Ex:
    """executor do BracoPersistente falso"""

    def __init__(self, log, falha=None):
        self.log, self.falha = log, falha
        self.pickplace = self

    def referenciar(self):
        self.log.append("referenciar")
        if self.falha:
            raise self.falha

    def parar(self):
        self.log.append("parar")

    def fechar(self):
        self.log.append("fechar")


class Braco:
    def __init__(self, log, falha=None):
        self.log, self.falha = log, falha

    def executor(self, com_nomes, nomes=()):
        return Ex(self.log, self.falha)

    def encerrar(self):
        self.log.append("encerrar")


def test_referenciar_braco():
    log = []
    c = calibracao.Calibracao("braco", Braco(log))
    assert c.tarefa == "braco" and c.os is None
    c.rodar()
    assert log == ["referenciar", "fechar"]
    assert c.resultado["ok"] and c.resultado["tipo"] == "braco" and c.resultado["fim"]
    assert c.encerrando


def test_erro_vira_resultado_e_fecha_o_braco():
    log = []
    c = calibracao.Calibracao("braco", Braco(log, falha=RuntimeError("ponta não encontrada")))
    c.rodar()
    assert log == ["referenciar", "parar", "fechar"]       # parar marca a falha: o fechar corta a energia
    assert not c.resultado["ok"] and "ponta não encontrada" in c.resultado["msg"]


def test_soltar_fecha_o_braco_para_alinhar_o_j1():
    log = []
    c = calibracao.Calibracao("soltar", Braco(log))
    c.rodar()
    assert log == ["encerrar"] and c.resultado["ok"]
    assert "alinhe o J1" in c.resultado["msg"]


def test_tipo_invalido():
    import pytest
    with pytest.raises(ValueError):
        calibracao.Calibracao("tudo", Braco([]))


def test_so_aplica_modelo_novo_se_erra_menos():
    assert calibracao.vale_aplicar(antigo=57.0, novo=4.6, n=49)
    assert not calibracao.vale_aplicar(antigo=4.0, novo=5.1, n=49)          # piorou: mantém o atual
    assert not calibracao.vale_aplicar(antigo=57.0, novo=4.6, n=8)          # pontos de menos para confiar


def test_aplicar_guarda_copia_do_modelo_antigo(tmp_path):
    arq = tmp_path / "calibracao_XWF.json"
    arq.write_text(json.dumps({"o2": 0.7}))
    copia = calibracao.aplica_modelo({"o2": 1.4}, arq, "20261023-1700")
    assert json.loads(arq.read_text()) == {"o2": 1.4}
    assert copia.name == "calibracao_XWF.20261023-1700.json" and json.loads(copia.read_text()) == {"o2": 0.7}
