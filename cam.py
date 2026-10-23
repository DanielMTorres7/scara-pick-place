import cv2, sys, time
from pathlib import Path

NOME_CAM = "C920"
IDX_PADRAO = 1  # Windows (DirectShow): índice da C920 com a câmera do notebook no 0
FOCO = 0        # foco manual da C920 (0 = infinito): o autofoco caça e borra a imagem depois de um reset no USB
SYSFS = Path("/sys/class/video4linux")
DESCARTA_MIN = 5  # o buffer da V4L2 pode segurar ~4 quadros mesmo pedindo 1
TENTATIVAS = 5
REABRE_ESPERA, REABRE_TENTATIVAS = 1.0, 5
WB_K = {"C920": 5500}   # balanço de branco fixo (K): no automático a C920 azulou a foto com a luz do fim de tarde (23/10)   # s entre tentativas de reabrir uma câmera que caiu da USB
FPS = 10          # C920 e XWF no mesmo hub USB 2.0: a 30 fps não há banda para as duas (23/10; no UH700, só a 10); a XWF fica em 30


class CameraSemImagem(RuntimeError):
    """a câmera parou de entregar quadros"""



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
    def __init__(self, idx=None, w=1920, h=1080, nome=None):
        """nome: trecho do nome do dispositivo (ex. "XWF"); com ele a câmera é reaberta se cair da USB"""
        if idx is None: idx = acha_indice(nome or NOME_CAM) if sys.platform.startswith("linux") else None
        if idx is None: idx = IDX_PADRAO
        self.nome, self.w, self.h = nome, w, h
        self._abre(idx)
    def _abre(self, idx):
        self.c = cv2.VideoCapture(idx, backend())
        if not self.c.isOpened(): raise RuntimeError("câmera %s não abriu" % idx)
        # MJPG: sem isso a C920 entrega 1080p a ~5 fps em YUYV no Linux
        self.c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.c.set(cv2.CAP_PROP_FRAME_WIDTH, self.w); self.c.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
        self.c.set(cv2.CAP_PROP_FPS, FPS)
        self.c.set(cv2.CAP_PROP_AUTOFOCUS, 0); self.c.set(cv2.CAP_PROP_FOCUS, FOCO)
        wb = WB_K.get(self.nome)                      # só com o nome: aberta pelo índice pode ser qualquer câmera
        if wb:
            self.c.set(cv2.CAP_PROP_AUTO_WB, 0); self.c.set(cv2.CAP_PROP_WB_TEMPERATURE, wb)
        self.c.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # com buffer cheio o driver guarda os quadros velhos
        for _ in range(10): self.c.read()
    def _le(self, arq, descarta):
        for _ in range(max(descarta, DESCARTA_MIN)): self.c.grab()
        for _ in range(TENTATIVAS):
            r, f = self.c.read()
            if r and f is not None:
                if arq: cv2.imwrite(arq, f)
                return f
        return None
    def _reabre(self):
        """a câmera caiu da USB (23/10: a XWF some por ~1 s com o chaveamento dos relés) e volta com outro /dev/videoN"""
        self.c.release()
        for _ in range(REABRE_TENTATIVAS):
            time.sleep(REABRE_ESPERA)
            idx = acha_indice(self.nome)
            if idx is not None:
                try:
                    self._abre(idx)
                    return True
                except RuntimeError:
                    pass
        return False
    def foto(self, arq=None, descarta=5):
        """quadro atual; `descarta` esvazia o buffer (quadros de antes de um movimento). Sem imagem, reabre a câmera
        pelo nome (caiu da USB) e tenta de novo; se continuar, levanta em vez de seguir com uma foto que não existe."""
        f = self._le(arq, descarta)
        if f is None and getattr(self, "nome", None) and self._reabre():
            f = self._le(arq, descarta)
        if f is None:
            raise CameraSemImagem("câmera sem imagem depois de %d tentativas (cabo/hub USB?)" % TENTATIVAS)
        return f
    def fechar(self): self.c.release()
