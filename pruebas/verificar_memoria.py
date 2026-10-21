#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verificar_memoria.py - Verificación de la memoria SQLite y del puente 1.4.0.

Comprueba, con una base temporal dentro de `pruebas/`, que:

  1. el esquema se crea y las métricas cuadran;
  2. un proceso guardado se recupera por una reformulación (firma W 4D) y NO se
     confunde con una tarea de otro tema;
  3. la deduplicación por huella actualiza en vez de duplicar;
  4. una lección asociada a un error se recupera junto con la tarea;
  5. el presupuesto de tokens recorta valores grandes al guardar y al devolver;
  6. el catálogo indexa skills/herramientas y enruta una necesidad a la skill
     correcta;
  7. los índices (token invertido y celdas W) no cambian el resultado de la
     búsqueda y los contadores lo reflejan;
  8. restaurar hace warm-start real (reentrena el predictor y reconstruye los
     índices);
  9. purgar limpia caché e índices sin tocar la memoria SQLite;
 10. los secretos se redactan antes de persistirse.

Uso:
    python pruebas/verificar_memoria.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)

import bridge_vos  # noqa: E402

BASE = os.path.join(AQUI, ".tmp_verificar_memoria")
fallos: list[str] = []
comprobaciones = 0


def comprobar(condicion: bool, mensaje: str, detalle: str = "") -> None:
    """Registra una comprobación y acumula el fallo con su detalle."""
    global comprobaciones
    comprobaciones += 1
    if condicion:
        print(f"  OK    {mensaje}")
    else:
        fallos.append(mensaje)
        print(f"  FALLO {mensaje}{(' -> ' + detalle) if detalle else ''}")


def preparar_entorno() -> str:
    """Crea una carpeta temporal con dos skills de ejemplo."""
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE)
    skills = os.path.join(BASE, "skills")
    muestras = {
        "arquitecto-software": (
            "Especialista en disenar la arquitectura de aplicaciones PHP y MySQL "
            "con capas, contratos y trade-offs documentados en ADR.",
            "Se invoca al iniciar un proyecto PHP o al decidir una estructura "
            "dificil de revertir.",
            "Decidir y documentar la estructura de una aplicacion PHP 8.2+ con "
            "MySQL 8+ antes de escribir codigo.",
        ),
        "tester-qa": (
            "Disena pruebas automatizadas y evidencia real de ejecucion para PHP "
            "y MySQL.",
            "Se invoca antes de entregar y al corregir un defecto.",
            "Verificar con evidencia real que el sistema cumple los criterios de "
            "aceptacion.",
        ),
    }
    for nombre, (descripcion, cuando, proposito) in muestras.items():
        carpeta = os.path.join(skills, nombre)
        os.makedirs(carpeta)
        with open(os.path.join(carpeta, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(
                "---\n"
                f"name: {nombre}\n"
                f'description: "{descripcion}"\n'
                f'whenToUse: "{cuando}"\n'
                "---\n"
                f"# {nombre}\n"
                "## Proposito\n"
                f"{proposito}\n"
            )
    return skills


def main() -> int:
    skills = preparar_entorno()
    config = {
        "ruta_memoria": os.path.join(BASE, "memoria", "prueba.db"),
        "ruta_skills": skills,
        "presupuesto_caracteres": 900,
        "max_tokens_respuesta": 120,
        "umbral_procesos": 0.22,
        "umbral_recursos": 0.35,
    }
    estado = bridge_vos.EstadoVOS(config)

    print("\n1. Arranque, memoria y catálogo")
    print("-" * 66)
    comprobar(estado.modo == "vectorw", f"núcleo real activo (modo {estado.modo})",
              str(estado.motivo_degradado))
    comprobar(estado.memoria is not None, "memoria SQLite abierta",
              str(estado.motivo_memoria))
    comprobar(estado.catalogo.get("skills") == 2,
              f"catálogo indexa 2 skills ({estado.catalogo})")
    comprobar(estado.catalogo.get("herramientas") == 9,
              f"catálogo indexa 9 herramientas ({estado.catalogo})")

    print("\n2. Procesos: guardar, recuperar y no confundir")
    print("-" * 66)
    guardado = estado.guardar_proceso({
        "intencion": "migrar la tabla de usuarios a MySQL 8 con PDO y transacciones",
        "resultado": ("Se creó la migración 003_usuarios.sql con PDO y transacciones "
                      "y se verificó con 12/12 pruebas de integración."),
        "pasos": ["leer esquema", "crear migración", "ejecutar pruebas"],
        "contexto": {"modulo": "usuarios", "preset": "php-mysql-senior-factory-v2"},
        "referencia": "migrations/003_usuarios.sql",
        "estado": "validado",
        "tokens": 3200,
    })
    comprobar(guardado["guardado"] and guardado["id"] > 0,
              f"proceso guardado (id {guardado['id']})")
    comprobar(guardado["huella"], f"huella semántica calculada: {guardado['huella']}")

    hit = estado.buscar_proceso({
        "query": "migrar tabla usuarios MySQL con PDO y transacciones",
        "limite": 3,
    })
    comprobar(hit["hit"], "reformulación de la tarea -> HIT",
              hit.get("resumen", ""))
    comprobar(bool(hit["procesos"]) and hit["procesos"][0]["id"] == guardado["id"],
              "el proceso recuperado es el correcto")
    comprobar(hit["tokens_ahorrados"] == 3200,
              f"tokens ahorrados contabilizados ({hit['tokens_ahorrados']})")

    miss = estado.buscar_proceso({
        "query": "disenar un sistema de facturacion electronica con firma digital",
    })
    comprobar(miss["hit"] is False, "tema distinto -> MISS (sin falso acierto)",
              miss.get("resumen", ""))

    otra = estado.guardar_proceso({
        "intencion": "migrar tabla usuarios MySQL con PDO y transacciones",
        "resultado": "Con el mismo índice, la migración se reduce a 4 pasos.",
        "estado": "validado",
        "tokens": 500,
    })
    comprobar(otra["actualizado"] is True,
              "misma huella -> actualiza en vez de duplicar")
    comprobar(otra["entradas"] == guardado["entradas"],
              f"sin entradas nuevas ({otra['entradas']})")

    print("\n3. Lecciones de error asociadas a la tarea")
    print("-" * 66)
    con_leccion = estado.guardar_proceso({
        "intencion": "consultar usuarios por correo en MySQL sin bloqueos",
        "resultado": "Se añadió el índice idx_usuarios_email y bajó el tiempo a 3 ms.",
        "tokens": 800,
        "leccion": {
            "tipo": "rendimiento",
            "causa": "falta de índice en la columna de búsqueda",
            "correccion": "crear un índice compuesto (tenant_id, email)",
            "prevencion": "revisar el plan de ejecución antes de desplegar",
            "modulo": "usuarios",
            "verificado": True,
        },
    })
    comprobar(con_leccion["leccion"] is not None, "lección guardada")
    recuperado = estado.buscar_proceso({
        "query": "consultar usuarios por correo en MySQL sin bloqueos",
    })
    comprobar(bool(recuperado.get("lecciones")),
              f"lección recuperada junto a la tarea "
              f"({len(recuperado.get('lecciones', []))})")
    if recuperado.get("lecciones"):
        leccion = recuperado["lecciones"][0]
        comprobar("índice" in (leccion.get("correccion") or ""),
                  "la corrección de la lección llega completa")

    print("\n4. Presupuesto de tokens (guardar y devolver)")
    print("-" * 66)
    largo = "dato_util " * 2000
    g = estado.guardar_valor("consulta con un valor enorme sobre índices", largo, 5000)
    comprobar(g["truncado"] is True, "valor grande recortado al guardar")
    comprobar(g["longitud_original"] > len(largo) * 0.9,
              f"se conserva la longitud original ({g['longitud_original']})")
    h = estado._buscar("consulta con un valor enorme sobre índices")
    comprobar(h["hit"] is True and h["truncado"] is True,
              "acierto recortado al devolver")
    comprobar(len(h["value"]) <= config["max_tokens_respuesta"] * 4 + 200,
              f"respuesta acotada ({len(h['value'])} car.)")
    comprobar(h["tokens_entregados"] < h["tokens_ahorrados"],
              "los tokens entregados son menores que los evitados")

    print("\n5. Deduplicación de la caché")
    print("-" * 66)
    d = estado.guardar_valor("consulta con un valor enorme sobre índices", "otro", 10)
    comprobar(d["deduplicada"] is True, "misma huella -> deduplicada")
    comprobar(len(estado.entradas) == 1, f"una sola entrada ({len(estado.entradas)})")

    print("\n6. Gate de polaridad (negación)")
    print("-" * 66)
    estado.guardar_valor("optimizar consultas vectoriales con octree", "podar 7/8", 300)
    negado = estado._buscar("no optimizar consultas vectoriales con octree")
    comprobar(negado["hit"] is False,
              "«no optimizar» NO acerta contra «optimizar» (distancia 0.0 sin gate)",
              negado.get("motivo") or "")
    estado.guardar_valor("activar la cache LRU con TTL", "activar", 100)
    desactivado = estado._buscar("desactivar la cache LRU con TTL")
    comprobar(desactivado["hit"] is False,
              "«desactivar» NO acerta contra «activar»")
    comprobar(estado.descartes_polaridad > 0,
              f"descartes por polaridad contabilizados "
              f"({estado.descartes_polaridad})")
    proceso_negado = estado.buscar_proceso({"query": "no migrar tabla usuarios MySQL"})
    comprobar(proceso_negado["hit"] is False,
              "«no migrar» NO recupera el proceso «migrar»")

    print("\n7. Catálogo: enrutar la necesidad al recurso correcto")
    print("-" * 66)
    r = estado.buscar_recurso({
        "query": "necesito disenar la arquitectura de la aplicacion",
    })
    comprobar(r["hit"] is True, "necesidad de arquitectura -> HIT",
              r.get("resumen", ""))
    comprobar(r["recursos"] and r["recursos"][0]["nombre"] == "arquitecto-software",
              f"recurso correcto: {r['recursos'][0]['nombre'] if r['recursos'] else '—'}")
    r2 = estado.buscar_recurso({
        "query": "pruebas automatizadas y evidencia de ejecucion",
        "tipo": "skill",
    })
    comprobar(r2["recursos"] and r2["recursos"][0]["nombre"] == "tester-qa",
              f"otra necesidad -> otra skill: "
              f"{r2['recursos'][0]['nombre'] if r2['recursos'] else '—'}")
    rt = estado.buscar_recurso({"query": "guardar el resultado en la cache semantica",
                                "tipo": "herramienta"})
    comprobar(rt["recursos"] and "vector_cache" in rt["recursos"][0]["nombre"],
              f"herramienta recomendada: "
              f"{rt['recursos'][0]['nombre'] if rt['recursos'] else '—'}")

    print("\n8. Índices de la caché")
    print("-" * 66)
    comprobar(len(estado.indice_tokens) > 0,
              f"índice invertido construido ({len(estado.indice_tokens)} tokens)")
    comprobar(len(estado.indice_espacios) > 0,
              f"índice de celdas W ({len(estado.indice_espacios)} celdas)")
    comprobar(estado.indice_norm, "índice de coincidencia exacta O(1)")
    # Con y sin índice de celdas, la decisión de la búsqueda debe ser la misma.
    estado.config["usar_indice_espacios"] = False
    sin_celdas = estado._buscar("consulta con un valor enorme sobre índices")
    estado.config["usar_indice_espacios"] = True
    con_celdas = estado._buscar("consulta con un valor enorme sobre índices")
    comprobar(sin_celdas["hit"] == con_celdas["hit"] == True,
              "el índice de celdas complementa sin cambiar el resultado")
    comprobar(estado.consultas_indice >= 2,
              f"contador de consultas indexadas ({estado.consultas_indice})")

    print("\n9. Restauración con warm-start real")
    print("-" * 66)
    estado.guardar_valor("configurar cache LRU con TTL y frecuencia",
                         "Expulsión por score = frecuencia*0.7 - antigüedad*0.3.", 90)
    ruta_estado = os.path.join(BASE, "estado.json")
    entradas_antes = len(estado.entradas)
    estado.persistir(ruta_estado)
    estado2 = bridge_vos.EstadoVOS({
        **config,
        "ruta_memoria": os.path.join(BASE, "memoria", "prueba2.db"),
    })
    restaurado = estado2.restaurar(ruta_estado)
    comprobar(restaurado["restaurado"] and restaurado["entradas"] == entradas_antes,
              f"estado restaurado ({restaurado['entradas']} de {entradas_antes})")
    comprobar(restaurado["reentrenadas"] == restaurado["entradas"],
              f"predictor reentrenado ({restaurado['reentrenadas']})")
    comprobar(estado2.indice_norm, "índices reconstruidos tras restaurar")
    comprobar(estado2._buscar("consulta con un valor enorme sobre índices")["hit"],
              "la caché restaurada sigue acertando")

    print("\n10. Redacción de secretos")
    print("-" * 66)
    secreto = estado.guardar_proceso({
        "intencion": "configurar el despliegue con credenciales",
        "resultado": "Se usó api_key = sk-abcdef1234567890abcdef y password: hunter2seguro.",
        "tokens": 50,
    })
    fila = estado.memoria.proceso_por_id(secreto["id"])
    comprobar("sk-abcdef1234567890abcdef" not in fila["resultado"],
              "la clave API no se persiste")
    comprobar("hunter2seguro" not in fila["resultado"],
              "la contraseña no se persiste")
    comprobar(secreto["redacciones"] >= 1,
              f"redacciones contabilizadas ({secreto['redacciones']})")

    print("\n11. Purga y aislamiento de la memoria")
    print("-" * 66)
    procesos_antes = estado.metricas()["memoria_sqlite"]["procesos"]
    purgado = estado.purgar()
    m = estado.metricas()
    comprobar(purgado["purgadas"] >= 1, f"caché vaciada ({purgado['purgadas']})")
    comprobar(len(estado.entradas) == 0 and not estado.indice_tokens,
              "índices vaciados con la caché")
    comprobar(m["memoria_sqlite"]["procesos"] == procesos_antes,
              "la memoria SQLite NO se borra al purgar la caché")

    print("\n" + "=" * 66)
    # En Windows la base sigue bloqueada mientras la conexión está abierta: se
    # cierran ambas antes de borrar para no dejar basura en el repo.
    for instancia in (estado, locals().get("estado2")):
        try:
            instancia.memoria.cerrar()
        except Exception:  # pragma: no cover - best effort
            pass
    if not os.environ.get("VECTORW_KEEP_TMP"):
        for intento in range(3):
            try:
                shutil.rmtree(BASE)
                break
            except OSError:
                if intento == 2:
                    print(f"  AVISO no se pudo borrar {BASE}")
                else:
                    import time as _time
                    _time.sleep(0.2)
    if fallos:
        print(f"RESULTADO: {len(fallos)} FALLOS de {comprobaciones} comprobaciones")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print(f"RESULTADO: {comprobaciones}/{comprobaciones} comprobaciones OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

