"""Acha caixas de remédio na mesa só com OpenCV (sem Gemini).

1) a impressão colorida (saturação alta) dá a semente de cada caixa;
2) a partir de cada lado da semente, procura para fora a borda da caixa branca (pico de gradiente),
   no referencial girado da própria caixa. Devolve centro (px), tamanho, ângulo e cantos da caixa inteira.
"""
import cv2
import numpy as np

MARGEM = 45     # px que a borda da caixa pode estar além da impressão
TAM_LONGO, TAM_CURTO = 185, 125   # px: maior tampa de caixa vista até agora (+~10%)
RAIO_BRACO_PX = 150   # semente a menos disso de um hexágono previsto do braço é o braço (paralaxe do cotovelo)
ROXO = (116, 165)  # matiz (OpenCV 0-179) do tampo roxo; azul da impressão ~100-110, vermelho ~175


def _sementes(f, roi, braco_px=None):
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]
    roxo = (h >= ROXO[0]) & (h <= ROXO[1])          # tampo da mesa: saturado, mas roxo (a impressão é azul/vermelha)
    m = ((hsv[..., 1] > 45) & (hsv[..., 2] > 60) & ~roxo).astype(np.uint8) * 255
    if roi:
        x0, y0, x1, y1 = roi
        r = np.zeros_like(m); r[y0:y1, x0:x1] = 255; m &= r
    # fechamento pequeno: junta a impressão de uma caixa sem unir caixas encostadas (margem branca de ~10-20 px)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        a = cv2.contourArea(c)
        (cx, cy), (w, h), ang = cv2.minAreaRect(c)
        preench = a / (w * h)
        if a < 4000 or preench < 0.75 or not (80 < max(w, h) < 220 and 55 < min(w, h) < 160):
            continue
        if braco_px is not None:
            # posição dos hexágonos do braço conhecida (cotovelo e ponta na foto): descarta só o que está perto
            if any(np.hypot(cx - u, cy - v) < RAIO_BRACO_PX for u, v in braco_px):
                continue
        # o hexágono azul do braço é quase redondo (~1,15:1) e preenche ~75% do retângulo; a impressão da caixa
        # é retangular (~1,5:1) ou, quando quase quadrada (Levoxin ~1,17:1; degradê azul na C920), preenche 80-90%
        elif max(w, h) / min(w, h) < 1.25 and preench < 0.80:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if x <= 2 or y <= 2 or x + bw >= f.shape[1] - 2 or y + bh >= f.shape[0] - 2:
            continue                                    # cortada na borda da imagem
        out.append(((cx, cy), (w, h), ang))
    return out


def _borda(perfil, ini, sentido, minimo):
    """posição do pico de gradiente entre ini+6 e ini+MARGEM (sentido +1/-1); ini se não houver pico"""
    idx = [ini + sentido * k for k in range(6, MARGEM)]
    idx = [i for i in idx if 0 <= i < len(perfil)]
    if not idx:
        return ini
    vals = perfil[idx]
    j = int(np.argmax(vals))
    return idx[j] if vals[j] > minimo else ini


def caixa_inteira(g, semente):
    (cx, cy), (w, h), ang = semente
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(g, M, (g.shape[1], g.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    gx = np.abs(cv2.Sobel(rot, cv2.CV_32F, 1, 0, ksize=3))
    gy = np.abs(cv2.Sobel(rot, cv2.CV_32F, 0, 1, ksize=3))
    x0, x1 = int(round(cx - w / 2)), int(round(cx + w / 2))
    y0, y1 = int(round(cy - h / 2)), int(round(cy + h / 2))
    px = gx[y0 + 8:y1 - 8].mean(axis=0)          # perfil ao longo de x (colunas)
    py = gy[:, x0 + 8:x1 - 8].mean(axis=1)
    minimo = 6.0
    L = _borda(px, x0, -1, minimo); R = _borda(px, x1, +1, minimo)
    T = _borda(py, y0, -1, minimo); B = _borda(py, y1, +1, minimo)
    # caixas encostadas: a busca pode passar da margem e achar a borda da vizinha. Se o lado ficou maior que uma
    # caixa de verdade, a margem maior vira igual à menor (a impressão fica mais ou menos centrada na tampa)
    def limita(a, b, ini, fim, tam_max):
        ma, mb = ini - a, b - fim
        if b - a > tam_max:
            m = min(ma, mb)
            a, b = ini - m, fim + m
        return a, b
    longo_x = (x1 - x0) >= (y1 - y0)
    L, R = limita(L, R, x0, x1, TAM_LONGO if longo_x else TAM_CURTO)
    T, B = limita(T, B, y0, y1, TAM_CURTO if longo_x else TAM_LONGO)
    ccx, ccy = (L + R) / 2, (T + B) / 2
    Mi = cv2.invertAffineTransform(M)
    c = Mi @ [ccx, ccy, 1.0]
    tam = (R - L, B - T)
    cantos = cv2.boxPoints(((float(c[0]), float(c[1])), tam, ang))
    return {"centro": (float(c[0]), float(c[1])), "tam": tam, "ang": ang, "cantos": cantos.tolist(),
            "impressao": (cx, cy)}


def acha_caixas(f, roi=None, braco_px=None):
    """braco_px: pixels previstos dos hexágonos do braço (cotovelo, ponta); sem eles, a forma é que os separa"""
    g = cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.float32)
    return [caixa_inteira(g, s) for s in _sementes(f, roi, braco_px)]


if __name__ == "__main__":
    import sys
    f = cv2.imread(sys.argv[1])
    v = f.copy()
    for k in acha_caixas(f):
        print("centro", [round(x, 1) for x in k["centro"]], "tam", [round(x) for x in k["tam"]], "ang", round(k["ang"], 1),
              "impressão", [round(x) for x in k["impressao"]])
        cv2.drawContours(v, [np.int32(k["cantos"])], -1, (0, 255, 0), 3)
        cv2.drawMarker(v, tuple(int(x) for x in k["centro"]), (0, 0, 255), cv2.MARKER_CROSS, 30, 3)
    cv2.imwrite(sys.argv[2] if len(sys.argv) > 2 else "fotos/caixas_dbg.jpg", cv2.resize(v, (960, 540)))
