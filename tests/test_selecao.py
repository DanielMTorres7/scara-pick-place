from selecao import escolhe_caixas, mesmo_nome, pendentes

ITENS = [{"nome": "micpure", "quantidade": 2}, {"nome": "arpadol", "quantidade": 1}]


def _caixa(nome, y):
    return {"nome": nome, "centro": (100.0, float(y))}


def test_pendentes_respeita_ordem_e_feitos():
    assert pendentes(ITENS, 3, {"micpure": 1}) == [{"nome": "micpure", "faltam": 1}, {"nome": "arpadol", "faltam": 1}]


def test_pendentes_vazio_quando_tudo_feito():
    assert pendentes(ITENS, 3, {"micpure": 2, "arpadol": 1}) == []


def test_pendentes_sem_itens():
    assert pendentes([], 3, {"": 1}) == [{"nome": "", "faltam": 2}]
    assert pendentes([], 3, {"": 3}) == []


def test_escolhe_respeita_quantidade():
    caixas = [_caixa("Micpure", 300), _caixa("Micpure", 100), _caixa("Micpure", 200)]
    fila = escolhe_caixas(caixas, [{"nome": "micpure", "faltam": 2}])
    assert [(k["centro"][1], n) for k, n in fila] == [(100.0, "micpure"), (200.0, "micpure")]


def test_escolhe_segue_ordem_da_lista():
    caixas = [_caixa("Arpadol", 100), _caixa("Micpure", 200)]
    fila = escolhe_caixas(caixas, [{"nome": "micpure", "faltam": 1}, {"nome": "arpadol", "faltam": 1}])
    assert [n for _, n in fila] == ["micpure", "arpadol"]


def test_escolhe_nao_reusa_caixa():
    caixas = [_caixa("Micpure", 100)]
    fila = escolhe_caixas(caixas, [{"nome": "micpure", "faltam": 1}, {"nome": "", "faltam": 1}])
    assert len(fila) == 1


def test_escolhe_falta_quando_nao_ha():
    caixas = [_caixa("Micpure", 100), _caixa("Micpure", 200)]
    fila = escolhe_caixas(caixas, [{"nome": "micpure", "faltam": 2}, {"nome": "arpadol", "faltam": 1}])
    assert [n for _, n in fila] == ["micpure", "micpure"]


def test_escolhe_sem_nome_pega_qualquer():
    caixas = [_caixa("", 100), _caixa("Arpadol", 200)]
    assert len(escolhe_caixas(caixas, [{"nome": "", "faltam": 5}])) == 2


def test_mesmo_nome_tolera_erro():
    assert mesmo_nome("micpure", "Miopure")
    assert not mesmo_nome("micpure", "Arpadol")
