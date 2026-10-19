import cv2, numpy as np, sys, math
def rot(a, b, roi=None):
    ga, gb = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (a, b)]
    m = np.zeros_like(ga)
    if roi: x0, y0, x1, y1 = roi; m[y0:y1, x0:x1] = 255
    else: m[:] = 255
    o = cv2.ORB_create(4000)
    ka, da = o.detectAndCompute(ga, m); kb, db = o.detectAndCompute(gb, m)
    mt = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    pa = np.float32([ka[x.queryIdx].pt for x in mt]); pb = np.float32([kb[x.trainIdx].pt for x in mt])
    mv = np.linalg.norm(pa - pb, axis=1) > 3   # só o que se moveu
    M, inl = cv2.estimateAffinePartial2D(pa[mv], pb[mv], ransacReprojThreshold=3)
    ang = math.degrees(math.atan2(M[1, 0], M[0, 0]))
    # centro fixo: (I - R) c = t
    R = M[:, :2]; t = M[:, 2]
    c = np.linalg.solve(np.eye(2) - R, t) if abs(ang) > 0.3 else None
    return ang, c, int(inl.sum()), int(mv.sum())
if __name__ == "__main__":
    a, b = cv2.imread(sys.argv[1]), cv2.imread(sys.argv[2])
    print(rot(a, b))
