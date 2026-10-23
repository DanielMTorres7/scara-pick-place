"""codifica: palavras do _traj (no.py) cujo tempo real acompanha m·DT. Desde o fim de curso pela PIO (jmp pin depois
de cada passo) o passo dura 2d+8 ciclos; a espera, d+9; cada palavra com passos, +5."""
import scara


def _ciclos(w):
    n, d = w >> 21, w & 0xFFFFF
    return 5 + n * (2 * d + 8) if n else d + 9


def test_tempo_real_acompanha_dt_sem_acumular_erro():
    spu = scara.EIXOS["j1"]["passos_un"]
    q = [(m + 1) * 100 / spu for m in range(300)] + [300 * 100 / spu] * 20     # 100 passos/segmento e parado
    w, fim = scara.codifica(q, spu, 0)
    tc = round(scara.DT * scara.FREQ)
    total = 0
    for m, x in enumerate(w):
        total += _ciclos(x)
        periodo = 2 * (x & 0xFFFFF) + 8
        assert abs(total - (m + 1) * tc) <= periodo, (m, total - (m + 1) * tc)
    assert fim == 30000
