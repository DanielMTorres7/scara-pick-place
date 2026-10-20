import grade


def test_sequencia_alterna_a_ordem_do_z_entre_poses():
    seq = grade.sequencia([(0, 0), (10, 0), (20, 0)], (-40, 10))
    assert seq == [(0, 0, -40), (0, 0, 10), (10, 0, 10), (10, 0, -40), (20, 0, -40), (20, 0, 10)]


def test_na_imagem_usa_margem():
    assert grade.na_imagem((960, 540), margem=100)
    assert not grade.na_imagem((50, 540), margem=100)
    assert not grade.na_imagem((960, 1000), margem=100)


def test_faixa_nao_passa_do_fim():
    assert grade.faixa("-100:130:30") == [-100, -70, -40, -10, 20, 50, 80, 110]
    assert grade.faixa("0:20:10") == [0, 10, 20]
