"""Recupera los coeficientes lineales EXACTOS de parametro_t por diagonal.

parametro_t es lineal en el punto, asi que t(p) = t0 + a*x + b*y + c*z.
Resolviendo ese sistema para cada diagonal se obtienen sus coeficientes reales,
que es lo que la implementacion de referencia debe reproducir.
"""

import sys

sys.path.insert(0, r"C:\Users\PePiuoX\Documents\Github\VectorW\vectorW_py")
import vectorW_6 as vw  # noqa: E402

for L in (1024.0, 32000.0):
    fam = vw.FamiliaDiagonales(lado_cubo=L, n_espacios=8)
    print(f"=== lado {L} ===")
    for nombre, diag in fam.diagonales.items():
        t0 = diag.parametro_t((0.0, 0.0, 0.0))
        # Coeficientes exactos: diferencia finita con paso 1.
        a = diag.parametro_t((1.0, 0.0, 0.0)) - t0
        b = diag.parametro_t((0.0, 1.0, 0.0)) - t0
        c = diag.parametro_t((0.0, 0.0, 1.0)) - t0
        print(f"  {nombre.value}")
        print(f"     inicio    = {tuple(round(v,4) for v in diag.punto_inicio)}")
        print(f"     direccion = {tuple(round(v,8) for v in diag.direccion)}")
        print(f"     t(0)      = {t0:.8f}   ({t0/L:.8f} * L)")
        print(f"     coef      = ({a:.8f}, {b:.8f}, {c:.8f})")
        print(f"     coef*L    = ({a*L:.6f}, {b*L:.6f}, {c*L:.6f})")
        print(f"     t(0)/L    = {t0/L:.8f}")
    print()
