import cv2, sys
from pathlib import Path

NOME_CAM = "C920"
IDX_PADRAO = 1  # Windows (DirectShow): índice da C920 com a câmera do notebook no 0
FOCO = 0        # foco manual da C920 (0 = infinito): o autofoco caça e borra a imagem depois de um reset no USB
SYSFS = Path("/sys/class/video4linux")


def backend(plataforma=sys.platform):
    if plataforma == "win32": return cv2.CAP_DSHOW
    if plataforma.startswith("linux"): return cv2.CAP_V4L2
    return cv2.CAP_ANY


def acha_indice(nome=NOME_CAM, raiz=SYSFS):
    """índice /dev/videoN da câmera pelo nome (Linux); pula o nó de metadados (index != 0)"""
    if not raiz.is_dir(): return None
    for d in sorted(raiz.glob("video*"), key=lambda p: int(p.name[5:])):
        try:
            if nome in (d / "name").read_text() and (d / "index").read_text().strip() == "0":
                return int(d.name[5:])
        except (OSError, ValueError): continue
    return None


class Cam:
    def __init__(self, idx=None, w=1920, h=1080):
        if idx is None: idx = acha_indice() if sys.platform.startswith("linux") else None
        if idx is None: idx = IDX_PADRAO
        self.c = cv2.VideoCapture(idx, backend())
        if not self.c.isOpened(): raise RuntimeError("câmera %s não abriu" % idx)
        # MJPG: sem isso a C920 entrega 1080p a ~5 fps em YUYV no Linux
        self.c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.c.set(cv2.CAP_PROP_FRAME_WIDTH, w); self.c.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        self.c.set(cv2.CAP_PROP_AUTOFOCUS, 0); self.c.set(cv2.CAP_PROP_FOCUS, FOCO)
        for _ in range(10): self.c.read()
    def foto(self, arq=None, descarta=5):
        for _ in range(descarta): self.c.read()
        r, f = self.c.read()
        if arq and r: cv2.imwrite(arq, f)
        return f
    def fechar(self): self.c.release()
