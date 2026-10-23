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


def test_foto_vazia_tenta_de_novo_e_depois_levanta():
    import pytest

    class CapFalsa:
        def __init__(self, quadros):
            self.quadros = list(quadros)

        def grab(self):
            return True

        def read(self):
            f = self.quadros.pop(0) if self.quadros else None
            return f is not None, f

    c = cam.Cam.__new__(cam.Cam)
    c.c = CapFalsa([None, "quadro"])
    assert c.foto() == "quadro"
    c.c = CapFalsa([None] * 10)
    with pytest.raises(cam.CameraSemImagem):
        c.foto()


def test_abre_a_15_fps_para_as_duas_cameras_caberem_no_mesmo_hub(monkeypatch):
    """23/10: C920 e XWF no mesmo hub USB 2.0 a 30 fps -> "Not enough bandwidth" e a XWF sem imagem; com a C920 a
    15 fps as duas cabem (a XWF ignora o pedido e fica em 30); no hub interno do UH700, só a 10 fps"""
    props = {}

    class CapFalsa:
        def __init__(self, *a):
            pass

        def isOpened(self):
            return True

        def set(self, p, v):
            props[p] = v

        def read(self):
            return True, "quadro"

    monkeypatch.setattr(cam.cv2, "VideoCapture", CapFalsa)
    cam.Cam(idx=2)
    assert props[cam.cv2.CAP_PROP_FPS] == 10


def test_camera_que_caiu_da_usb_e_reaberta_pelo_nome(monkeypatch):
    """23/10: a XWF cai da USB por ~1 s no meio do pick_place (volta com outro /dev/videoN) e a rodada parava.
    Sem imagem: reabre pelo nome e tenta de novo."""
    import pytest

    class CapMorta:
        def grab(self):
            return False

        def read(self):
            return False, None

        def release(self):
            pass

    class CapNova(CapMorta):
        def __init__(self, idx, *a):
            self.idx = idx

        def isOpened(self):
            return True

        def set(self, *a):
            pass

        def read(self):
            return True, "quadro de /dev/video%d" % self.idx

    monkeypatch.setattr(cam.cv2, "VideoCapture", CapNova)
    monkeypatch.setattr(cam, "acha_indice", lambda nome: 7 if nome == "XWF" else None)
    monkeypatch.setattr(cam.time, "sleep", lambda s: None)
    c = cam.Cam.__new__(cam.Cam)
    c.c, c.nome, c.w, c.h = CapMorta(), "XWF", 1920, 1080
    assert c.foto() == "quadro de /dev/video7"
    c.c, c.nome = CapMorta(), None                   # sem nome não tem como reabrir: levanta como antes
    with pytest.raises(cam.CameraSemImagem):
        c.foto()


def test_c920_abre_com_balanco_de_branco_fixo(monkeypatch):
    """23/10, fim de tarde: o balanço automático da C920 deixou a foto azul (disco branco da base com saturação 72, mesa
    H ~100) e o detector de caixas não achou nenhuma. Fixo em 5500 K: branco neutro, mesa roxa (H ~147)."""
    props = {}

    class CapFalsa:
        def __init__(self, *a):
            pass

        def isOpened(self):
            return True

        def set(self, p, v):
            props[p] = v

        def read(self):
            return True, "quadro"

    monkeypatch.setattr(cam.cv2, "VideoCapture", CapFalsa)
    cam.Cam(idx=2, nome="C920")
    assert props[cam.cv2.CAP_PROP_AUTO_WB] == 0 and props[cam.cv2.CAP_PROP_WB_TEMPERATURE] == 5500
    props.clear()
    cam.Cam(idx=3, nome="XWF")
    assert cam.cv2.CAP_PROP_AUTO_WB not in props               # a XWF fica no automático (está boa)
