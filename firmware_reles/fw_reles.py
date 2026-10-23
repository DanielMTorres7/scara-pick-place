# Módulo de 8 relés (ativo baixo: LOW = relé ligado; contatos NA) na RP2040-Zero b02d1c.
# Comandado pelo REPL: o host chama ligar/estado/energizar/desenergizar com nomes lógicos (1 = ligado).
# GP0: divisor de tensão do 24 V (1 = 24 V presente). GP26 (ADC), no mesmo divisor: a tensão em volts.
import json

import utime
from machine import ADC, Pin

PINOS = {"potencia": 4, "bomba": 5, "rele6": 6, "dm556_z": 7,
         "placa2": 8, "rele9": 9, "placa1": 10, "dm556": 11}   # canal 9 com defeito (não fecha): placa 1 foi pro 10
RAMOS = ("placa1", "placa2", "dm556", "dm556_z")   # ligados com a fonte cortada: o relé da potência é quem comuta a carga
PIN_VS = 0
PIN_V = 26
FATOR_DIVISOR = 9.27   # volts na fonte por volt no pino (47k / 1k+4,7k; calibrado: 2,761 V no pino com a fonte em 25,6 V)
PAUSA_RELE_MS = 150   # entre um relé e outro: as bobinas saem do 5 V do USB e todas juntas resetavam a placa

_p = {n: Pin(g, Pin.OUT, value=1) for n, g in PINOS.items()}
_vs = Pin(PIN_VS, Pin.IN, None)   # sem pull: o divisor define o nível
_adc = ADC(PIN_V)


def ligar(nome, v):
    _p[nome].value(0 if v else 1)


def vs():
    return _vs.value()


def tensao(n=16):
    """volts na fonte (média de n leituras do ADC no divisor)"""
    s = 0
    for _ in range(n):
        s += _adc.read_u16()
    return s / n / 65535 * 3.3 * FATOR_DIVISOR


def estado():
    e = {n: 1 - p.value() for n, p in _p.items()}
    e["vs"] = vs()
    e["v"] = round(tensao(), 1)
    return e


def print_estado():
    print("E", json.dumps(estado()))


def energizar(timeout_ms=2000):
    """liga placas e DM556, depois a potência; devolve 1 se o 24 V apareceu dentro do timeout"""
    for n in RAMOS + ("potencia",):
        ligar(n, 1)
        utime.sleep_ms(PAUSA_RELE_MS)
    t0 = utime.ticks_ms()
    while not vs():
        if utime.ticks_diff(utime.ticks_ms(), t0) >= timeout_ms:
            return 0
        utime.sleep_ms(10)
    return 1


def desenergizar():
    """corta a potência primeiro, depois desliga todo o resto (bomba inclusive)"""
    ligar("potencia", 0)
    for n in PINOS:
        ligar(n, 0)
