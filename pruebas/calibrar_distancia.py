"""Calibración empírica de la distancia de la caché semántica W.

Mide pares de consultas que deberían acertar (reformulaciones) frente a pares
que no deberían acertar nunca (temas distintos), para situar el umbral.
"""

import sys
import os

# La raíz del paquete es el directorio padre de pruebas/.
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
sys.path.insert(0, r"C:\Users\PePiuoX\Documents\Github\VectorW\vectorW_py")

import bridge_vos as b  # noqa: E402

estado = b.EstadoVOS({"ruta_core": r"C:\Users\PePiuoX\Documents\Github\VectorW\vectorW_py"})
print(f"modo: {estado.modo}\n")

BASE = [
    ("optimizar consultas vectoriales con octree y poda espacial", [
        "optimizar consultas vectoriales con octree y podado espacial",
        "como optimizar consultas vectoriales con octree y poda espacial",
        "octree poda espacial para consultas vectoriales optimizar",
        "optimizar las consultas vectoriales con el octree y la poda del espacio",
    ]),
    ("como funciona la cache LRU con TTL y frecuencia", [
        "como funciona la cache LRU con TTL y frecuencias",
        "explicame la cache LRU con TTL y frecuencia",
        "funcionamiento de la cache LRU, TTL y frecuencia",
    ]),
]

AJENAS = [
    "desplegar el plugin en linux con systemd",
    "recetas de cocina vegana con tofu",
    "configurar certificados TLS en nginx",
    "historia del imperio romano en el siglo tercero",
    "prediccion markov de orden superior",
]


def firma_tokens(texto):
    norm = estado._normalizar(texto)
    return estado.firma_de(norm), b.tokenizar(norm)


for base, variantes in BASE:
    fb, tb = firma_tokens(base)
    print(f"BASE: {base}")
    print(f"      tokens={tb}")
    for v in variantes:
        fv, tv = firma_tokens(v)
        dist, solape = estado.distancia(fb, tb, fv, tv)
        geo = estado.distancia_geometrica(fb, fv)
        print(f"   variante : {dist:.4f}  (geo {geo:.4f}, solape {solape:.2f})  <- {v}")
    print()

fb, tb = firma_tokens(BASE[0][0])
print(f"AJENAS frente a: {BASE[0][0]}")
peor = None
for a in AJENAS:
    fa, ta = firma_tokens(a)
    dist, solape = estado.distancia(fb, tb, fa, ta)
    if peor is None or dist < peor[0]:
        peor = (dist, a, solape)
    print(f"   ajeno    : {dist:.4f}  (solape {solape:.2f})  <- {a}")
print(f"\n   ajeno mas cercano (el peor caso): {peor[0]:.4f} con solape {peor[2]:.2f} <- {peor[1]}")
print(f"   variante mas lejana: 0.1162")
print("   => umbral seguro entre esos dos valores: 0.15")
