from progresso import Progresso, reconcilia

ITENS = [{"nome": "micpure", "quantidade": 2}, {"nome": "arpadol", "quantidade": 1}]


def test_salva_e_carrega(tmp_path):
    p = Progresso(tmp_path / "os_progresso.json")
    assert p.carrega("OS-1") == {}
    p.salva("OS-1", {"micpure": 1})
    p.salva("OS-2", {"arpadol": 1})
    assert Progresso(tmp_path / "os_progresso.json").carrega("OS-1") == {"micpure": 1}


def test_reconcilia_usa_salvo():
    assert reconcilia(ITENS, 3, 1, {"arpadol": 1}) == {"arpadol": 1}


def test_reconcilia_zera_em_restart():
    assert reconcilia(ITENS, 3, 0, {"micpure": 2}) == {}


def test_reconcilia_diverge_usa_ordem():
    assert reconcilia(ITENS, 3, 3, {}) == {"micpure": 2, "arpadol": 1}
    assert reconcilia(ITENS, 3, 1, {"micpure": 2}) == {"micpure": 1}


def test_reconcilia_sem_itens():
    assert reconcilia([], 4, 2, {}) == {"": 2}
