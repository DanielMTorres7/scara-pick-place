import cv2, time
class Cam:
    def __init__(self, idx=1, w=1920, h=1080):
        self.c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        self.c.set(cv2.CAP_PROP_FRAME_WIDTH, w); self.c.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        for _ in range(10): self.c.read()
    def foto(self, arq=None, descarta=5):
        for _ in range(descarta): self.c.read()
        r, f = self.c.read()
        if arq and r: cv2.imwrite(arq, f)
        return f
    def fechar(self): self.c.release()
