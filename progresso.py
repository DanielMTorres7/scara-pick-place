"""Quantas caixas de cada remédio já foram soltas na coletora, por OS, salvo em disco: se o processo cair ou a OS
for retomada, o braço continua de onde parou em vez de pegar de novo o que já separou."""
import json
import os
from pathlib import Path


class Progresso:
    def __init__(self, caminho):
        self.caminho = Path(caminho)

    def _tudo(self):
        try:
            return json.loads(self.caminho.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def carrega(self, os_):
        return dict(self._tudo().get(os_, {}))

    def salva(self, os_, feitos):
        tudo = self._tudo()
        tudo[os_] = feitos
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(tudo, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.caminho)


def reconcilia(itens, quantidade, separadas, salvo):
    """o sistema manda quantas já foram separadas: vale o salvo se bate; 0 = OS refeita do zero; se diverge, supõe
    que as primeiras `separadas` da lista (na ordem pedida) foram as feitas"""
    if sum(salvo.values()) == separadas:
        return dict(salvo)
    if separadas == 0:
        return {}
    if not itens:
        return {"": separadas}
    feitos = {}
    resto = separadas
    for it in itens:
        n = min(it["quantidade"], resto)
        if n > 0:
            feitos[it["nome"]] = feitos.get(it["nome"], 0) + n
        resto -= n
    return feitos
