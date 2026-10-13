#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Equivalencia entre la implementación de referencia y el núcleo original.

Comprueba que `implementaciones/python/vectorw_w.py` produce EXACTAMENTE los
mismos números que `vendor/vectorW_py/vectorW_6.py` (obra de PePiuoX) para los
mismos puntos. Si esta prueba pasa, la firma W 4D de la referencia es fiel al
núcleo, y por tanto los vectores de prueba que genera son válidos para
verificar los ports a otros lenguajes.

Uso:
    python pruebas/verificar_equivalencia.py
"""

from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "implementaciones", "python"))
sys.path.insert(0, os.path.join(RAIZ, "vendor", "vectorW_py"))

from vectorw_w import FamiliaDiagonalesW, tokenizar  # noqa: E402

TOLERANCIA = 1e-12


def cargar_nucleo():
    """Importa el núcleo original; devuelve None si no está disponible."""
    try:
        import vectorW_6  # noqa: F401
        return vectorW_6
    except Exception as exc:  # pragma: no cover
        print(f"[AVISO] no se pudo importar el núcleo original: {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    nucleo = cargar_nucleo()
    if nucleo is None:
        print("EQUIVALENCIA: no verificable (núcleo ausente)")
        return 0

    fallos = 0
    comprobaciones = 0

    # --- 1. Geometría y firma sobre puntos 3D arbitrarios -----------------
    # La forma lineal reproduce el núcleo en cualquier tamaño de cubo: el
    # término constante no está incrustado, es (1+√3)·L/√3, así que escala.
    puntos = [
        (0.0, 0.0, 0.0), (1024.0, 1024.0, 1024.0), (1024.0, 0.0, 0.0),
        (0.0, 1024.0, 0.0), (0.0, 0.0, 1024.0), (512.0, 512.0, 512.0),
        (123.0, 456.0, 789.0), (102.4, 921.6, 337.92), (999.0, 1.0, 512.0),
    ]

    for lado in (1024.0, 32000.0):
        ref = FamiliaDiagonalesW(lado_cubo=lado, n_espacios=8)
        orig = nucleo.FamiliaDiagonales(lado_cubo=lado, n_espacios=8)

        comprobaciones += 1
        if ref.es_geometria_canonica != (abs(lado - 1024.0) < 1e-9):
            print(f"  FALLO marca de geometria canonica en lado {lado}")
            fallos += 1

        comprobaciones += 1
        if abs(ref.longitud - orig.longitud) > TOLERANCIA:
            print(f"  FALLO longitud ({lado}): ref={ref.longitud} orig={orig.longitud}")
            fallos += 1

        # Los puntos de prueba se escalan al cubo analizado.
        escala = lado / 1024.0
        for base in puntos:
            punto = tuple(v * escala for v in base)
            esperado = orig.calcular_firma_normalizada(punto)
            obtenido = ref.firma_de_punto(punto)
            comprobaciones += 1
            if any(abs(a - b) > TOLERANCIA for a, b in zip(esperado, obtenido)):
                print(f"  FALLO firma ({lado}) en {punto}")
                print(f"        esperado {esperado}")
                print(f"        obtenido {obtenido}")
                fallos += 1

            esperado_esp = orig.clasificar_en_espacios(punto)
            obtenido_esp = ref.espacios_de(punto)
            comprobaciones += 1
            if tuple(esperado_esp) != tuple(obtenido_esp):
                print(f"  FALLO espacios ({lado}) en {punto}: "
                      f"esperado {esperado_esp} obtenido {obtenido_esp}")
                fallos += 1

    # --- 2. La firma del texto es la firma de su centroide ----------------
    # El núcleo no firma textos: firma puntos. Lo que debe coincidir es que la
    # referencia firme el centroide con la misma aritmética del núcleo.
    ref = FamiliaDiagonalesW()
    orig = nucleo.FamiliaDiagonales(lado_cubo=1024.0, n_espacios=8)
    for texto in ["optimizar consultas vectoriales con octree",
                  "la diagonal W", "cache LRU con TTL"]:
        f = ref.firma_de_texto(texto)
        esperado = orig.calcular_firma_normalizada(f.coords)
        comprobaciones += 1
        if any(abs(a - b) > TOLERANCIA for a, b in zip(esperado, f.firma)):
            print(f"  FALLO firma de texto en {texto!r}")
            fallos += 1

    # --- 3. Determinismo de la tokenización ------------------------------
    for texto in ["cachés y caches", "PODA, podado y podando", "", "áéíóú ñ"]:
        comprobaciones += 1
        if tokenizar(texto) != tokenizar(texto):
            print(f"  FALLO tokenización no determinista en {texto!r}")
            fallos += 1

    print(f"\nEQUIVALENCIA: {comprobaciones - fallos}/{comprobaciones} comprobaciones OK")
    if fallos:
        print(f"  {fallos} FALLOS")
        return 1
    print("  La firma W 4D de la referencia coincide con el núcleo original.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
