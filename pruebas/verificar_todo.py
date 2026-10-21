#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejecuta toda la verificación del plugin y resume el resultado.

Sirve para CI y para que un contribuidor compruebe en un solo paso que sus
cambios no rompen la cadena de confianza:

    nucleo original (vendor/vectorW_py)
        → referencia Python
        → corpus compartido (vectores_w.json)
        → ports (TypeScript, JavaScript)

Uso:
    python pruebas/verificar_todo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ejecutar(titulo: str, comando: list) -> tuple:
    """Ejecuta un comando y devuelve (ok, salida_resumida)."""
    try:
        resultado = subprocess.run(
            comando,
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except FileNotFoundError:
        return None, f"no encontrado: {comando[0]}"
    except subprocess.TimeoutExpired:
        return False, "timeout"

    salida = (resultado.stdout or "") + (resultado.stderr or "")
    # La última línea no vacía suele ser el veredicto.
    lineas = [l.strip() for l in salida.strip().splitlines() if l.strip()]
    resumen = lineas[-1] if lineas else "(sin salida)"
    return resultado.returncode == 0, resumen


def main() -> int:
    pasos = [
        ("Referencia vs nucleo original", [sys.executable, os.path.join("pruebas", "verificar_equivalencia.py")]),
        ("Memoria SQLite y puente 1.4", [sys.executable, os.path.join("pruebas", "verificar_memoria.py")]),
        ("Port TypeScript", ["node", os.path.join("implementaciones", "typescript", "prueba.ts")]),
        ("Port JavaScript", ["node", os.path.join("implementaciones", "javascript", "prueba.mjs")]),
    ]

    print("Verificacion completa del plugin VectorW")
    print("=" * 68)

    fallos = 0
    omitidos = 0
    for titulo, comando in pasos:
        ok, resumen = ejecutar(titulo, comando)
        if ok is None:
            print(f"  OMITIDO  {titulo:<32} {resumen}")
            omitidos += 1
        elif ok:
            print(f"  OK       {titulo:<32} {resumen}")
        else:
            print(f"  FALLO    {titulo:<32} {resumen}")
            fallos += 1

    # La verificacion de montaje reproduce el arranque del loader, asi que debe
    # correr desde el directorio del perfil (ahi vive node_modules). Solo se
    # ejecuta si el plugin esta instalado en ese perfil.
    home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    dir_perfil = os.path.join(home, "profiles")
    enlazado = os.path.isdir(os.path.join(
        dir_perfil, "node_modules", "@deepseek-ai", "dsh-plugin-vectorw"
    ))
    etiqueta_montaje = "Montaje en el perfil de DSH"

    if enlazado:
        ruta_montaje = os.path.join(RAIZ, "pruebas", "verificar_montaje.mjs")
        # Sin capturar la salida a proposito: el banco de pruebas lanza el
        # puente Python, y bajo el sandbox de Windows un proceso anidado no
        # puede abrir tuberias. Con `capture_output=True` el spawn del puente
        # falla con EPERM y la prueba daria un falso negativo. Dejando que
        # herede la consola, el arbol de procesos no anida tuberias.
        print(f"\n  --- salida de {etiqueta_montaje} ---")
        try:
            resultado = subprocess.run(
                ["node", ruta_montaje, "--solo-montaje"], cwd=dir_perfil, timeout=300,
            )
            print(f"  --- fin de {etiqueta_montaje} ---\n")
            if resultado.returncode == 0:
                print(f"  OK       {etiqueta_montaje:<32} todas las comprobaciones pasaron")
            else:
                print(f"  FALLO    {etiqueta_montaje:<32} codigo {resultado.returncode}")
                fallos += 1
        except FileNotFoundError:
            print(f"  OMITIDO  {etiqueta_montaje:<32} node no encontrado")
            omitidos += 1
    else:
        print(f"  OMITIDO  {etiqueta_montaje:<32} el plugin no esta instalado")
        omitidos += 1

    # Comprobaciones que no necesitan subproceso.
    ruta_vectores = os.path.join(RAIZ, "pruebas", "vectores_w.json")
    if os.path.isfile(ruta_vectores):
        with open(ruta_vectores, encoding="utf-8") as manejador:
            vectores = json.load(manejador)
        print(f"  OK       {'Corpus compartido':<32} "
              f"{len(vectores['puntos'])} puntos, {len(vectores['textos'])} textos, "
              f"{len(vectores['distancias'])} distancias")
    else:
        print(f"  FALLO    {'Corpus compartido':<32} no existe vectores_w.json")
        fallos += 1

    for ruta, etiqueta in (
        (os.path.join("vendor", "vectorW_py", "vectorW_6.py"), "Nucleo vendorizado"),
        (os.path.join("bridge_vos.py"), "Puente del plugin"),
        (os.path.join("memoria_vectorw.py"), "Memoria SQLite"),
        (os.path.join("lib", "index.js"), "Plugin de DSH"),
    ):
        if os.path.isfile(os.path.join(RAIZ, ruta)):
            print(f"  OK       {etiqueta:<32} presente")
        else:
            print(f"  FALLO    {etiqueta:<32} falta {ruta}")
            fallos += 1

    print("=" * 68)
    if fallos:
        print(f"RESULTADO: {fallos} FALLOS")
        return 1
    extra = f" ({omitidos} omitidos)" if omitidos else ""
    print(f"RESULTADO: todo OK{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
