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


def test_le_camera_da_linha_de_comando():
    c = grade.le_camera("XWF:796,863:2.09:-90")
    assert c == {"nome": "XWF", "centro": (796.0, 863.0), "escala": 2.09, "ang0": -90.0}


def test_pose_entra_se_alguma_camera_ve_em_todas_as_alturas():
    so_a = lambda j1, j2, z: (960, 540) if j1 == 0 else (-500, 0)
    so_b = lambda j1, j2, z: (960, 540) if j1 == 10 else (-500, 0)
    nenhuma = lambda j1, j2, z: (-500, 0)
    assert grade.poses_visiveis([(0, 0), (10, 0), (20, 0)], [so_a, so_b, nenhuma], (-40, 10)) == [(0, 0), (10, 0)]


def test_saida_por_camera():
    assert grade.saida_camera("dados_grade.json", "XWF", 2) == "dados_grade_XWF.json"
    assert grade.saida_camera("dados_grade.json", "C920", 1) == "dados_grade.json"   # uma câmera: igual a antes


def test_tira_poses_com_o_braco_sobre_a_coletora():
    assert grade.poses_livres([(0, 0), (10, 0), (20, 0)], lambda j1, j2: j1 != 10) == [(0, 0), (20, 0)]
