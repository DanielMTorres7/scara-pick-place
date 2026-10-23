# Boot da placa dos relés: tudo desligado (nível alto) antes de qualquer outra coisa; depois fica no REPL.
# Ctrl+D (soft reset) roda isto de novo e desliga tudo. Gravar: python reles.py gravar
from machine import Pin
for g in range(4, 12):
    Pin(g, Pin.OUT, value=1)
import fw_reles  # noqa: E402  (fica no namespace do REPL)
