#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera los vectores de prueba compartidos entre implementaciones.

Produce `pruebas/vectores_w.json`, que contiene firmas y decisiones de caché
calculadas por la implementación de referencia de Python. Cualquier port a otro
lenguaje debe reproducir esos números exactamente: es la garantía de que todas
las implementaciones hablan el mismo espacio W.

El archivo incluye:
  · los parámetros de configuración usados;
  · la geometría de las 4 diagonales;
  · firmas de puntos 3D concretos (para validar la aritmética pura);
  · firmas de textos (para validar tokenización + centroide);
  · pares consulta/consulta con su distancia y solapamiento (para validar la
    métrica y el umbral de decisión).

Uso:
    python pruebas/generar_vectores.py            # escribe el JSON
    python pruebas/generar_vectores.py --salida X # a otra ruta
"""

from __future__ import annotations

import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "implementaciones", "python"))

from vectorw_w import (  # noqa: E402
    ConfigW,
    FamiliaDiagonalesW,
    CacheSemanticaW,
    VERSION,
    tokenizar,
)

# Puntos 3D de prueba: vértices, centro, y posiciones irregulares.
PUNTOS = [
    (0.0, 0.0, 0.0),
    (1024.0, 0.0, 0.0),
    (0.0, 1024.0, 0.0),
    (0.0, 0.0, 1024.0),
    (1024.0, 1024.0, 1024.0),
    (512.0, 512.0, 512.0),
    (123.0, 456.0, 789.0),
    (999.0, 1.0, 512.0),
    (102.4, 921.6, 337.92),
]

# Textos de prueba: consultas reales, con acentos, plurales y palabras vacías.
TEXTOS = [
    "optimizar consultas vectoriales con octree",
    "optimizar consultas vectoriales con octree y podado espacial",
    "octree poda espacial para consultas vectoriales optimizar",
    "como funciona la cache LRU con TTL y frecuencia",
    "como funciona la cache LRU con TTL y frecuencias",
    "explicame la cache LRU con TTL y frecuencia",
    "desplegar el plugin en linux con systemd",
    "recetas de cocina vegana con tofu",
    "la diagonal W proyecta el punto en el cubo",
    "prediccion markov de orden superior",
    "cachés y caches",
    "PODA, podado y podando",
    "áéíóú ñ",
    "",
    "a de la el",
]

# Pares (consulta A, consulta B) para validar la métrica y el umbral.
PARES = [
    ("optimizar consultas vectoriales con octree",
     "optimizar consultas vectoriales con octree y podado espacial"),
    ("optimizar consultas vectoriales con octree",
     "octree poda espacial para consultas vectoriales optimizar"),
    ("como funciona la cache LRU con TTL y frecuencia",
     "como funciona la cache LRU con TTL y frecuencias"),
    ("optimizar consultas vectoriales con octree",
     "desplegar el plugin en linux con systemd"),
    ("la diagonal W proyecta el punto en el cubo",
     "prediccion markov de orden superior"),
]


def redondear(valor, digitos=12):
    """Redondeo estable para que el JSON sea comparable entre lenguajes."""
    if isinstance(valor, float):
        return round(valor, digitos)
    if isinstance(valor, (list, tuple)):
        return [redondear(v, digitos) for v in valor]
    return valor


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera vectores de prueba de VectorW")
    parser.add_argument("--salida", default=os.path.join(RAIZ, "pruebas", "vectores_w.json"))
    argumentos = parser.parse_args()

    familia = FamiliaDiagonalesW(
        lado_cubo=ConfigW.LADO_CUBO, n_espacios=ConfigW.N_ESPACIOS
    )

    datos = {
        "version_implementacion": VERSION,
        "autor_nucleo_original": "Jose Ricardo Mantilla Mantilla (PePiuoX)",
        "config": {
            "lado_cubo": familia.lado,
            "n_espacios": familia.n_espacios,
            "longitud_diagonal": redondear(familia.longitud),
            "normalizador": redondear(familia.normalizador),
            "umbral_similitud": ConfigW.UMBRAL_SIMILITUD,
        },
        "geometria": {
            "bases": redondear(list(familia._bases)),
            "signos": [list(s) for s in familia._SIGNOS],
        },
        "tokenizacion": {
            texto: tokenizar(texto) for texto in TEXTOS
        },
        "puntos": [],
        "textos": [],
        "distancias": [],
        "cache": [],
    }

    # --- firmas de puntos 3D ---------------------------------------------
    for punto in PUNTOS:
        datos["puntos"].append({
            "punto": list(punto),
            "componentes": redondear(familia.componentes_de(punto)),
            "firma": redondear(familia.firma_de_punto(punto)),
            "espacios": list(familia.espacios_de(punto)),
        })

    # --- firmas de textos -------------------------------------------------
    firmas = {}
    for texto in TEXTOS:
        firma = familia.firma_de_texto(texto)
        firmas[texto] = firma
        datos["textos"].append({
            "texto": texto,
            "tokens": list(firma.tokens),
            "coords": redondear(firma.coords),
            "componentes": redondear(firma.componentes),
            "firma": redondear(firma.firma),
            "espacios": list(firma.espacios),
        })

    # --- distancias y decisiones ------------------------------------------
    for texto_a, texto_b in PARES:
        distancia, solapamiento = familia.distancia(firmas[texto_a], firmas[texto_b])
        datos["distancias"].append({
            "a": texto_a,
            "b": texto_b,
            "distancia": redondear(distancia),
            "solapamiento": redondear(solapamiento),
            "acierto": bool(
                distancia <= ConfigW.UMBRAL_SIMILITUD and solapamiento > 0
            ),
        })

    # --- comportamiento de la caché ---------------------------------------
    cache = CacheSemanticaW(familia, umbral_similitud=ConfigW.UMBRAL_SIMILITUD)
    cache.guardar("optimizar consultas vectoriales con octree", "resultado-caro", 4200)
    cache.guardar("como funciona la cache LRU con TTL y frecuencia", "otro", 60)
    for consulta in [
        "optimizar consultas vectoriales con octree",
        "optimizar consultas vectoriales con octree y podado espacial",
        "desplegar el plugin en linux con systemd",
    ]:
        resultado = cache.buscar(consulta)
        datos["cache"].append({
            "consulta": consulta,
            "hit": resultado["hit"],
            "kind": resultado["kind"],
            "query": resultado.get("query"),
            "tokens_ahorrados": resultado.get("tokens_ahorrados", 0),
            "distancia": redondear(resultado.get("distancia")),
            "solapamiento": redondear(resultado.get("solapamiento")),
        })
    datos["cache_estadisticas"] = {
        k: redondear(v) for k, v in cache.estadisticas().items()
    }

    with open(argumentos.salida, "w", encoding="utf-8") as manejador:
        json.dump(datos, manejador, ensure_ascii=False, indent=2, sort_keys=False)
        manejador.write("\n")

    print(f"Vectores escritos en {argumentos.salida}")
    print(f"  puntos      : {len(datos['puntos'])}")
    print(f"  textos      : {len(datos['textos'])}")
    print(f"  distancias  : {len(datos['distancias'])}")
    print(f"  cache       : {len(datos['cache'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
