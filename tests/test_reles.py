"""Host do módulo de relés: manda comandos ao REPL da placa e interpreta as respostas."""
import pytest

import reles


class SerialFalsa:
    def __init__(self, respostas):
        self.escrito, self.respostas = [], list(respostas)
        self.buf = b""

    @property
    def in_waiting(self):
        return len(self.buf)

    def write(self, b):
        self.escrito.append(b)
        if b.endswith(b"\r\n"):
            self.buf += self.respostas.pop(0) if self.respostas else b">>> "

    def read(self, n):
        r, self.buf = self.buf[:n], self.buf[n:]
        return r

    def close(self):
        self.escrito.append("fechou")

    def reset_input_buffer(self):
        self.buf = b""


def _reles(respostas=()):
    r = object.__new__(reles.Reles)
    r.s = SerialFalsa(respostas)
    return r


def test_ligar_manda_comando_logico():
    r = _reles()
    r.ligar("bomba", True)
    r.ligar("bomba", False)
    assert r.s.escrito == [b"fw_reles.ligar('bomba', 1)\r\n", b"fw_reles.ligar('bomba', 0)\r\n"]


def test_estado_le_json():
    r = _reles([b'fw_reles.print_estado()\r\nE {"bomba": 1, "vs": 0}\r\n>>> '])
    assert r.estado() == {"bomba": 1, "vs": 0}


def test_energizar_sem_24v_levanta():
    r = _reles([b"E 0\r\n>>> "])
    with pytest.raises(reles.SemEnergia):
        r.energizar()


def test_energizar_com_24v():
    r = _reles([b"E 1\r\n>>> "])
    r.energizar()
    assert r.s.escrito[0].startswith(b"print('E', fw_reles.energizar(")


def test_erro_no_repl_levanta():
    r = _reles([b"Traceback...\r\nKeyError: bomb\r\n>>> "])
    with pytest.raises(RuntimeError, match="KeyError"):
        r.ligar("bomb", True)


class SerialCai(SerialFalsa):
    """a USB cai no primeiro comando (pico de corrente ao ligar um DM556 pelo relé)"""

    def write(self, b):
        if b.endswith(b"\r\n") and not getattr(self, "caiu", False):
            self.caiu = True
            raise reles.serial.SerialException("write failed: [Errno 5] Input/output error")
        super().write(b)


def test_usb_caiu_reconecta_e_repete_o_comando(monkeypatch):
    """23/10: a USB dos relés cai quando um relé liga um DM556; os relés mantêm o estado e o comando é idempotente"""
    r = _reles()
    r.s = SerialCai([])
    nova = SerialFalsa([])
    monkeypatch.setattr(reles, "porta", lambda: "/dev/ttyACM1")
    monkeypatch.setattr(reles.serial, "Serial", lambda *a, **kw: nova)
    monkeypatch.setattr(reles.time, "sleep", lambda s: None)
    r.ligar("dm556_z", True)
    assert r.s is nova
    assert b"fw_reles.ligar('dm556_z', 1)\r\n" in nova.escrito


def test_placa_muda_vira_erro_em_vez_de_seguir():
    """23/10: a placa dos relés travou no meio do pick_place; ligar('bomba', 0) voltava em silêncio depois de 1 s e a
    bomba seguiu segurando a caixa. Sem o prompt de volta, o comando não foi executado: erro."""
    r = _reles([b""])
    r._conecta = lambda: None                   # a reconexão também não traz resposta
    r.s.respostas = [b"", b""]
    with pytest.raises(reles.RelesSemResposta):
        r.ligar("bomba", False)
