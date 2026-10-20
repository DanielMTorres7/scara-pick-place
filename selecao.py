"""Quais caixas da mesa pegar para uma OS: casa o nome lido pelo Gemini com os remédios pedidos, respeitando
a ordem da lista e a quantidade de cada um. Nome vazio no pedido = qualquer caixa (OS só com quantidade)."""
import difflib
import unicodedata


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def mesmo_nome(pedido, lido):
    """tolera um erro de leitura do Gemini ("Miopure" = "Micpure")"""
    a = _norm(pedido)
    return any(a in w or difflib.SequenceMatcher(None, a, w).ratio() >= 0.75 for w in _norm(lido).split())


def pendentes(itens, quantidade, feitos):
    """o que ainda falta pegar: [{"nome", "faltam"}] na ordem dos itens"""
    if not itens:
        faltam = quantidade - sum(feitos.values())
        return [{"nome": "", "faltam": faltam}] if faltam > 0 else []
    out = []
    for it in itens:
        faltam = it["quantidade"] - feitos.get(it["nome"], 0)
        if faltam > 0:
            out.append({"nome": it["nome"], "faltam": faltam})
    return out


def escolhe_caixas(caixas, pend):
    """fila [(caixa, nome do item)]: cada caixa no máximo uma vez; dentro de um item, de cima para baixo na imagem"""
    usadas = set()
    fila = []
    for p in pend:
        cands = [i for i, k in enumerate(caixas)
                 if i not in usadas and (p["nome"] == "" or mesmo_nome(p["nome"], k.get("nome", "")))]
        cands.sort(key=lambda i: caixas[i]["centro"][1])
        for i in cands[:p["faltam"]]:
            usadas.add(i)
            fila.append((caixas[i], p["nome"]))
    return fila
