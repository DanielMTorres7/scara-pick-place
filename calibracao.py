"""Calibração pelos botões do sistema EMR (servidor_os.py, POST /calibrar), no braço persistente do servidor.

soltar  — fecha o braço (energia cortada): motores soltos para o operador alinhar o J1 reto à mão
braco   — referencia: reinicia a placa do Z, Z e J2 pelas chaves, homing do J1 pela câmera, J1 no 0 (~1 min)
cameras — J1 = 0 onde está (alinhado à mão depois do soltar), Z e J2 pelas chaves, grade (~150 pontos, ~10-15 min),
          ajusta o modelo de cada câmera e só aplica se ele erra menos que o atual nos mesmos pontos (cópia do antigo);
          no fim refaz o homing com o modelo novo. Spec: .orchestrator/tasks/active/integracao-emr-braco-braco/03.
"""
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np

TIPOS = ("soltar", "braco", "cameras")
J1_GRADE, J2_GRADE, Z_GRADE = "-125:125:25", "-120:120:30", (-60.0, 10.0, 70.0)
FATOR_GRADE = 5.0       # velocidade da grade (grade.VEL x 5), a mesma das calibrações à mão de 23/10
DIST_MAX_PX = 150       # o modelo atual pode estar dezenas de px fora (por isso se recalibra)
MIN_PONTOS = 20         # menos que isso por câmera: não dá para confiar no ajuste
AQUI = Path(__file__).resolve().parent


def vale_aplicar(antigo, novo, n):
    """modelo novo só entra se teve pontos suficientes e erra menos (mediana, px) que o atual nos mesmos pontos"""
    return n >= MIN_PONTOS and novo < antigo


def aplica_modelo(cal, arq, carimbo):
    """grava o modelo novo em `arq`, guardando antes uma cópia do atual (<nome>.<carimbo>.json); devolve a cópia"""
    arq = Path(arq)
    copia = arq.with_name("%s.%s%s" % (arq.stem, carimbo, arq.suffix))
    shutil.copyfile(arq, copia)
    arq.write_text(json.dumps(cal, indent=1))
    return copia


def _erro_mediano(m, dados):
    e = [np.hypot(*np.subtract(m.robo_para_pixel(*m.fk(x["j1"], x["j2"]), x["z"])[:2], x["px"])) for x in dados]
    return float(np.median(e))


def recalibrar_cameras(pp):
    """pp: o PickPlace aberto (Scara + câmeras); devolve o resumo por câmera"""
    import calibrar
    import grade
    from cameras import CAMERAS, modelos
    from modelo import Modelo
    from pick_place import Z_ALTO
    from scara import Z_CHAVE

    r = pp.r
    r.definir("j1", 0.0)                        # o operador alinhou o J1 reto com os motores soltos (passo soltar)
    r.referenciar_z(vbusca=20.0)
    r.definir("z", Z_CHAVE)
    pp.ir_z(Z_ALTO)
    r.referenciar_j2()
    ms = modelos()
    specs = [{"nome": n, "saida": str(AQUI / ("dados_grade_auto_%s.json" % n)), "dist_max": DIST_MAX_PX,
              "prev": (lambda j1, j2, z, m=ms[n]: m.robo_para_pixel(*m.fk(j1, j2), z)[:2])} for n, _, _ in CAMERAS]
    poses = []
    for k, j1 in enumerate(grade.faixa(J1_GRADE)):
        j2s = grade.faixa(J2_GRADE)
        poses += [(j1, j2) for j2 in (j2s if k % 2 == 0 else j2s[::-1])]
    poses = grade.poses_visiveis(poses, [c["prev"] for c in specs], Z_GRADE)
    grade.coletar(grade.sequencia(poses, Z_GRADE), specs, FATOR_GRADE, r=r, abertas=[pp.cams[c["nome"]] for c in specs])
    carimbo = datetime.now().strftime("%Y%m%d-%H%M")
    resumo, copias = [], []
    for nome, arq, _ in CAMERAS:
        dados = [x for x in json.load(open(AQUI / ("dados_grade_auto_%s.json" % nome))) if x["px"]]
        if len(dados) < MIN_PONTOS:
            resumo.append("%s: só %d pontos, modelo mantido" % (nome, len(dados)))
            continue
        cal, err, _ = calibrar.ajustar(dados)
        antigo, novo = _erro_mediano(Modelo(arq), dados), float(np.median(err))
        if vale_aplicar(antigo, novo, len(dados)):
            copias.append((aplica_modelo(cal, arq, carimbo), arq))
            resumo.append("%s: %.1f -> %.1f px (aplicado)" % (nome, antigo, novo))
        else:
            resumo.append("%s: %.1f -> %.1f px (mantido o atual)" % (nome, antigo, novo))
    pp.ms = modelos()
    pp.m = pp.ms[CAMERAS[0][0]]
    pp._homing_feito = False
    try:
        pp.referenciar()                         # homing com o modelo novo: J1 no 0 corrigido
    except Exception:
        for copia, arq in copias:                # o modelo novo não confirmou o J1: volta o antigo
            shutil.copyfile(copia, arq)
        pp.ms = modelos()
        pp.m = pp.ms[CAMERAS[0][0]]
        raise
    return "; ".join(resumo)


class Calibracao:
    """trabalho do servidor de OS (rodar() numa thread), como o JobOS: tarefa, encerrando, resultado"""

    os = None

    def __init__(self, tipo, braco):
        if tipo not in TIPOS:
            raise ValueError("tipo: %s" % "|".join(TIPOS))
        self.tarefa, self.braco = tipo, braco
        self.encerrando = False
        self.resultado = None

    def _fim(self, ok, msg):
        self.resultado = {"tipo": self.tarefa, "ok": ok, "msg": msg, "fim": datetime.now().isoformat(timespec="seconds")}
        print("calibração %s: %s" % (self.tarefa, msg))

    def rodar(self):
        t0 = time.time()
        try:
            if self.tarefa == "soltar":
                self.braco.soltar()
                return self._fim(True, "motores soltos: alinhe o J1 reto (0°) à mão e inicie a recalibração")
            if self.tarefa == "cameras" and not self.braco.solto:
                # sem o soltar, J1 = 0 seria onde o braço estiver e a grade passaria dos limites do J1
                return self._fim(False, "recalibrar câmeras exige soltar os motores e alinhar o J1 à mão antes")
            ex = self.braco.executor(com_nomes=False)
            try:
                if self.tarefa == "braco":
                    ex.referenciar()
                    msg = "braço referenciado (%.0f s)" % (time.time() - t0)
                else:
                    msg = "câmeras: %s (%.0f min)" % (recalibrar_cameras(ex.pickplace), (time.time() - t0) / 60)
            except Exception:
                ex.parar()
                raise
            finally:
                ex.fechar()
            self._fim(True, msg)
        except Exception as e:
            self._fim(False, "erro: %s" % e)
        finally:
            self.encerrando = True
