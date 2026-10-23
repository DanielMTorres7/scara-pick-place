"""Módulo de 8 relés na RP2040-Zero b02d1c (firmware em firmware_reles/, comandado pelo REPL do MicroPython).

GP4 potência (fonte 24 V; o comando continua ligado) · GP5 bomba de vácuo · GP7 DM556 do Z · GP8 placa 2 (Z) ·
GP10 placa 1 (braço) · GP11 DM556 do J1 · GP6 livre · GP9 com defeito (o contato não fecha) · GP26 tensão (ADC) · GP0 lê o 24 V. Ativo baixo e contatos NA: no boot (e em reset) tudo desliga.
Aqui tudo é lógico: 1 = ligado. Os pinos mantêm o estado com a porta fechada.

Uso: python reles.py estado|liga <nome>|desliga <nome>|energiza|desenergiza|gravar
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import serial
import serial.tools.list_ports

UID_RELES = "5044466888b02d1c"
FIRMWARE = Path(__file__).resolve().parent / "firmware_reles"
TIMEOUT_24V_MS = 2000


class SemEnergia(RuntimeError):
    """liguei a potência mas o 24 V não apareceu no GP0"""


class RelesSemResposta(RuntimeError):
    """a placa não devolveu o prompt: o comando não foi executado (23/10: travou e a bomba ficou ligada)"""


def porta():
    for p in serial.tools.list_ports.comports():
        if (p.serial_number or "").lower() == UID_RELES:
            return p.device
    raise RuntimeError("placa dos relés não encontrada")


class Reles:
    """conexão aberta com o REPL da placa: cada comando leva ~20 ms"""

    def __init__(self):
        self._conecta()

    def _conecta(self):
        self.s = serial.Serial(porta(), 115200, timeout=0.5)
        time.sleep(0.1)
        self.s.write(b"\x03\x03")              # interrompe um comando pendente e cai no REPL (sem Ctrl+D: desligaria tudo)
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self._envia("import fw_reles")

    def _exec(self, linha, timeout=1.0):
        """manda a linha; se a USB cair (o pico ao ligar um DM556 derruba a porta, os relés mantêm o estado),
        reconecta e repete uma vez: todos os comandos daqui são idempotentes"""
        try:
            return self._envia(linha, timeout)
        except (serial.SerialException, OSError, RelesSemResposta):
            try:
                self.s.close()
            except (serial.SerialException, OSError):
                pass
            time.sleep(1.5)                      # a porta volta a aparecer depois de ~1 s
            self._conecta()
            return self._envia(linha, timeout)

    def _envia(self, linha, timeout=1.0):
        self.s.write(linha.encode() + b"\r\n")
        resp = b""
        fim = time.time() + timeout
        while time.time() < fim and not resp.endswith(b">>> "):
            resp += self.s.read(self.s.in_waiting or 1)
        txt = resp.decode(errors="replace")
        if not resp.endswith(b">>> "):
            raise RelesSemResposta("relés: sem resposta para %s (placa travada?)" % linha)
        if "Error" in txt:
            raise RuntimeError("relés: %s" % txt)
        return txt

    def _resposta(self, linha, timeout=1.0):
        """valor que o firmware imprimiu como 'E <valor>'"""
        for ln in self._exec(linha, timeout).splitlines():
            if ln.startswith("E "):
                return ln[2:].strip()
        raise RuntimeError("relés: sem resposta para %s" % linha)

    def ligar(self, nome, v):
        self._exec("fw_reles.ligar(%r, %d)" % (nome, 1 if v else 0))

    def estado(self):
        return json.loads(self._resposta("fw_reles.print_estado()"))

    def energizar(self):
        """liga placas, DM556 e potência; levanta SemEnergia se o 24 V não aparecer"""
        r = self._resposta("print('E', fw_reles.energizar(%d))" % TIMEOUT_24V_MS, timeout=TIMEOUT_24V_MS / 1000 + 1)
        if r != "1":
            raise SemEnergia("24 V não apareceu em %d ms depois de ligar a potência" % TIMEOUT_24V_MS)

    def desenergizar(self):
        self._exec("fw_reles.desenergizar()")

    def fechar(self):
        self.s.close()


def gravar():
    """copia o firmware para a placa e reinicia (tudo desliga no boot)"""
    p = porta()
    arqs = sorted(FIRMWARE.glob("*.py"))
    cmd = ["mpremote", "connect", p]
    for a in arqs:
        cmd += ["fs", "cp", str(a), ":%s" % a.name, "+"]
    cmd += ["reset"]
    subprocess.run(cmd, check=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "estado"
    if cmd == "gravar":
        gravar()
        sys.exit()
    r = Reles()
    if cmd in ("liga", "desliga"):
        r.ligar(sys.argv[2], cmd == "liga")
    elif cmd == "energiza":
        r.energizar()
    elif cmd == "desenergiza":
        r.desenergizar()
    print(r.estado())
    r.fechar()
