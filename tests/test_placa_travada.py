"""Placa travada (23/10: o RP2040 parava de responder depois que o relé da bomba/potência mudava): o comando sem resposta
vira PlacaTravada com o número de série; recuperar corta a energia e desliga/religa a porta dela no hub (UH700, power
switching por porta)."""
import pytest

import scara


class SerialMuda:
    def __init__(self, *a, **kw):
        pass

    def reset_input_buffer(self):
        pass

    def write(self, b):
        pass

    def readline(self):
        return b""

    def close(self):
        pass


def test_sem_resposta_vira_placa_travada_com_o_serial(monkeypatch):
    monkeypatch.setattr(scara.serial, "Serial", SerialMuda)
    monkeypatch.setattr(scara.time, "sleep", lambda s: None)
    p = scara.Placa("/dev/ttyACM9", serie="abc123")
    with pytest.raises(scara.PlacaTravada) as ex:
        p.cmd("st", timeout=0.01)
    assert ex.value.serie == "abc123"
    assert isinstance(ex.value, TimeoutError)          # quem já trata TimeoutError (reiniciar, esperar) continua igual


def _sysfs(tmp_path, dev="1-9.3", serie="c15b1c"):
    (tmp_path / dev).mkdir()
    (tmp_path / dev / "serial").write_text(serie + "\n")
    hub, porta = dev.rsplit(".", 1)
    d = tmp_path / ("%s:1.0" % hub) / ("%s-port%s" % (hub, porta))
    d.mkdir(parents=True)
    (d / "disable").write_text("0")
    return d / "disable"


def test_reinicia_a_porta_do_hub_pelo_serial(tmp_path, monkeypatch):
    arq = _sysfs(tmp_path)
    escritas = []
    real = scara._escreve_sysfs
    monkeypatch.setattr(scara, "_escreve_sysfs", lambda a, v: (escritas.append(v), real(a, v)))
    monkeypatch.setattr(scara.time, "sleep", lambda s: None)
    assert scara.reinicia_porta_usb("c15b1c", raiz=tmp_path) is True
    assert escritas == ["1", "0"]
    assert arq.read_text() == "0"


def test_placa_fora_de_hub_nao_tem_como_reiniciar(tmp_path):
    (tmp_path / "1-3").mkdir()
    (tmp_path / "1-3" / "serial").write_text("c15b1c")
    assert scara.reinicia_porta_usb("c15b1c", raiz=tmp_path) is False
    assert scara.reinicia_porta_usb("outro", raiz=tmp_path) is False


def test_recuperar_corta_a_energia_antes_de_reiniciar_a_porta(monkeypatch):
    log = []

    class Reles:
        def desenergizar(self):
            log.append("corta")

        def fechar(self):
            pass

    monkeypatch.setattr(scara, "reinicia_porta_usb", lambda serie, **kw: log.append(("porta", serie)) or True)
    r = object.__new__(scara.Scara)
    r.reles = Reles()
    r.recuperar(scara.PlacaTravada("z", "c15b1c", "st"))
    assert log == ["corta", ("porta", "c15b1c")]
