"""Placa.reiniciar: Ctrl-C para o firmware, Ctrl-D reinicia o MicroPython (zera PIO e estado) e o main.py sobe de novo."""
import json

import scara


class SerialFalsa:
    def __init__(self, *a, **kw):
        self.escrito = b""
        self.saida = []
        self.reiniciou = False

    def reset_input_buffer(self):
        self.saida.clear()

    def write(self, b):
        self.escrito += b
        if b"\x04" in b:
            self.reiniciou = True
        for linha in b.split(b"\n"):
            if linha.startswith(b"{") and self.reiniciou:
                m = json.loads(linha)
                self.saida.append((json.dumps({"id": m["id"], "ok": 1}) + "\n").encode())

    def readline(self):
        return self.saida.pop(0) if self.saida else b""

    def close(self):
        pass


def test_reiniciar_manda_ctrl_c_e_ctrl_d_e_espera_o_firmware(monkeypatch):
    monkeypatch.setattr(scara.serial, "Serial", SerialFalsa)
    monkeypatch.setattr(scara.time, "sleep", lambda s: None)
    p = scara.Placa("z")
    p.reiniciar()
    e = p.s.escrito
    assert e.index(b"\x03") < e.index(b"\x04")
    assert b'"c": "ping"' in e[e.index(b"\x04"):]
