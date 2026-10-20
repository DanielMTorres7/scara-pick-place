import cv2

import cam


def _sysfs(tmp_path, devs):
    for nome, (titulo, index) in devs.items():
        d = tmp_path / nome
        d.mkdir()
        (d / "name").write_text(titulo + "\n")
        (d / "index").write_text(f"{index}\n")
    return tmp_path


def test_backend_por_sistema():
    assert cam.backend("win32") == cv2.CAP_DSHOW
    assert cam.backend("linux") == cv2.CAP_V4L2
    assert cam.backend("darwin") == cv2.CAP_ANY


def test_acha_c920_no_linux_ignora_integrada_e_nodo_de_metadados(tmp_path):
    raiz = _sysfs(tmp_path, {
        "video0": ("Integrated Camera: Integrated C", 0),
        "video1": ("Integrated Camera: Integrated C", 1),
        "video2": ("HD Pro Webcam C920", 0),
        "video3": ("HD Pro Webcam C920", 1),
    })
    assert cam.acha_indice("C920", raiz) == 2


def test_acha_indice_sem_camera_retorna_none(tmp_path):
    raiz = _sysfs(tmp_path, {"video0": ("Integrated Camera", 0)})
    assert cam.acha_indice("C920", raiz) is None


def test_acha_indice_sem_sysfs_retorna_none(tmp_path):
    assert cam.acha_indice("C920", tmp_path / "nao_existe") is None
