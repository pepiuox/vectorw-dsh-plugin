#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Firma W 4D y caché semántica de VectorW — implementación de referencia.

Arquitectura y autor del núcleo VectorW original:
    Jose Ricardo Mantilla Mantilla (PePiuoX)
    https://github.com/PePiuoX
    Licencia LAMC v1.0 / LULA v1.1

Este módulo es una implementación PROPIA, independiente y sin dependencias
(solo biblioteca estándar), escrita para tres cosas:

  1. Servir de **referencia legible** del algoritmo de firma W 4D y de la
     caché semántica que usa el plugin de DeepSeek Harness.
  2. **Generar los vectores de prueba** compartidos
     (`pruebas/vectores_w.json`) que verifican que las implementaciones en
     otros lenguajes producen exactamente los mismos números.
  3. Permitir que el plugin funcione **sin depender del núcleo original**.

Relación con el núcleo original
-------------------------------
`vendor/vectorW_py/vectorW_6.py` es el núcleo de PePiuoX. Este archivo respeta
su geometría exacta —las 4 diagonales del cubo, el parámetro `t` y su
normalización— de modo que una firma calculada aquí coincide con la que
calcula `FamiliaDiagonales.calcular_firma_normalizada` sobre el mismo punto.
La verificación de esa equivalencia está en `pruebas/verificar_equivalencia.py`.

Lo que este archivo hace distinto y por qué está documentado en el README:
firma un texto por el **centroide de los puntos W de sus tokens**, no por el
hash del texto completo, y combina la distancia geométrica con el
solapamiento de vocabulario.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import unicodedata
from collections import OrderedDict

__all__ = [
    "ConfigW",
    "FirmaW",
    "FamiliaDiagonalesW",
    "tokenizar",
    "VERSION",
]

VERSION = "1.1.0"


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


class ConfigW:
    """Constantes del espacio de memoria VectorW.

    Los valores por defecto reproducen los del núcleo v6.0: cubo de lado 1024
    y 8 espacios por diagonal (32 espacios de resolución total).
    """

    LADO_CUBO: float = 1024.0
    N_ESPACIOS: int = 8
    UMBRAL_SIMILITUD: float = 0.15
    MAX_ENTRADAS: int = 2000
    TTL_SEGUNDOS: float = 0.0
    INVARIANTE_PERMUTACIONES: bool = True

    # Pesos de la distancia combinada.
    PESO_GEOMETRIA: float = 0.35
    PESO_SOLAPAMIENTO: float = 1.3


# ---------------------------------------------------------------------------
# Tokenización
# ---------------------------------------------------------------------------

_PALABRAS_VACIAS = frozenset("""
a al algo algunas algunos ante antes aqui asi aun aunque bien cada como con contra cual
cuando de del desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso
esos esta estaba estado estas este esto estos fue fueron ha hace hacia han hasta hay la
las le les lo los mas me mi mis mucho muy nada ni no nos nosotros nuestra nuestro o os
otra otro para pero poco por porque que quien se sea segun ser si sin sobre son su sus
tal tambien tanto te tiene tienen todo todos tu tus un una uno unos y ya
the is at which on an and are as be been but by can for from has have how in into it its
of or that their there these this to was were what when where who will with your
""".split())

# Sufijos que se recortan para tolerar plurales, género y conjugaciones simples.
_SUFIJOS = (
    "ciones", "cion", "mente", "ados", "adas", "ado", "ada",
    "idos", "idas", "ido", "ida", "es", "os", "as", "s",
)

_RE_TOKEN = re.compile(r"[\w\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1]+", re.UNICODE)


def _sin_acentos(texto: str) -> str:
    """Quita diacríticos conservando la letra base (á -> a, ñ -> n)."""
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _raiz(token: str) -> str:
    """Raíz aproximada de un token, conservadora y determinista."""
    for sufijo in _SUFIJOS:
        if len(token) > len(sufijo) + 3 and token.endswith(sufijo):
            return token[: -len(sufijo)]
    return token


def tokenizar(texto: str) -> list:
    """Extrae los tokens significativos de un texto.

    Aplica minúsculas, quita acentos, descarta palabras vacías y palabras de
    menos de 3 letras, reduce a raíz y elimina duplicados conservando el orden.

    La determinación de la raíz debe ser **idéntica en todos los lenguajes**,
    porque de ella depende que las firmas coincidan.

    @param texto - texto arbitrario (consulta, pregunta, tarea).
    @returns lista de tokens con raíz, sin duplicados.
    """
    if not texto:
        return []
    vistos = set()
    salida = []
    for crudo in _RE_TOKEN.findall(texto):
        normalizado = _sin_acentos(crudo)
        if len(normalizado) < 3 or normalizado in _PALABRAS_VACIAS:
            continue
        raiz = _raiz(normalizado)
        if raiz in vistos:
            continue
        vistos.add(raiz)
        salida.append(raiz)
    return salida


# ---------------------------------------------------------------------------
# Firma W 4D
# ---------------------------------------------------------------------------


class FirmaW:
    """Firma W 4D de un texto, con su procedencia.

    Atributos:
        tokens        - tokens significativos usados.
        coords        - centroide 3D de los tokens dentro del cubo.
        componentes   - las 4 proyecciones `t` sobre las diagonales (sin normalizar).
        firma         - las 4 proyecciones normalizadas por la longitud de la diagonal.
        espacios      - índice de espacio W (0..n-1) en cada diagonal.
        es_vacia      - True si el texto no aportó ningún token.
    """

    __slots__ = ("tokens", "coords", "componentes", "firma", "espacios", "es_vacia")

    def __init__(self, tokens, coords, componentes, firma, espacios, es_vacia):
        self.tokens = tokens
        self.coords = coords
        self.componentes = componentes
        self.firma = firma
        self.espacios = espacios
        self.es_vacia = es_vacia

    def como_dict(self) -> dict:
        """Representación JSON-serializable (usada por los vectores de prueba)."""
        return {
            "tokens": list(self.tokens),
            "coords": list(self.coords),
            "componentes": list(self.componentes),
            "firma": list(self.firma),
            "espacios": list(self.espacios),
            "es_vacia": self.es_vacia,
        }

    def __repr__(self) -> str:
        return f"FirmaW(firma={[round(f, 6) for f in self.firma]}, espacios={self.espacios})"


class FamiliaDiagonalesW:
    """Las 4 diagonales del cubo de memoria y la aritmética de firmas W 4D.

    Reproduce **exactamente** la geometría del núcleo original. Cada diagonal es
    una recta dirigida entre dos vértices opuestos del cubo, y la proyección de
    un punto sobre ella es una forma afín verificada contra el núcleo:

        t_k(p) = ( b_k · L + s_k · p ) / √3

    con `s_k` los coeficientes de la diagonal (±1) y `b_k` su término constante:

        k   diagonal   b_k              s_k
        1   W1 (+++)   0                (+1, +1, +1)
        2   W2 (-++)   1+√3 ≈ 2.7321    (-1, +1, +1)
        3   W3 (+-+)   1+√3 ≈ 2.7321    (+1, -1, +1)
        4   W4 (++-)   1+√3 ≈ 2.7321    (+1, +1, -1)

    La firma normalizada es `t_k / (L·√3) = (b_k + s_k · p') / 3`, con
    `p' = p/L`. Por eso los componentes 2..4 **arrancan en ≈0.9107**
    (= (1+√3)/3), no en 0: el núcleo sitúa el inicio de esas tres rectas fuera
    del cubo (2797.62 con lado 1024), así que cualquier punto del interior
    proyecta un valor alto. El recorrido de la firma es:

        (0,0,0)  → (0.000, 0.911, 0.911, 0.911)
        (L,L,L)  → (1.000, 1.244, 1.244, 1.244)

    Es una propiedad del núcleo, no un error; por eso la firma W 4D sirve para
    *clasificar y comparar*, no como medida absoluta. La tabla se obtuvo
    midiendo el núcleo y se verifica punto por punto (a dos tamaños de cubo) en
    `pruebas/verificar_equivalencia.py`.
    """

    # Término constante `b_k` y signos `s_k` por diagonal, en el orden
    # W1(+++), W2(-++), W3(+-+), W4(++-).
    _SIGNOS = (
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, -1.0),
    )

    def __init__(self, lado_cubo: float = ConfigW.LADO_CUBO,
                 n_espacios: int = ConfigW.N_ESPACIOS):
        self.lado = float(lado_cubo)
        self.n_espacios = max(1, int(n_espacios))
        self._raiz3 = math.sqrt(3.0)
        self.longitud = self.lado * self._raiz3
        # Divisor de normalización: la longitud de la diagonal. Hace la firma
        # independiente del tamaño del cubo.
        self.normalizador = self.longitud

        # Término constante b_k de t = (b·L + s·p)/√3.
        #   W1: 0           → firma 0 en el vértice (0,0,0)
        #   W2..W4: 1+√3    → firma (1+√3)/3 ≈ 0.9107 en ese mismo vértice,
        #                     porque el núcleo sitúa el inicio de esas rectas
        #                     fuera del cubo (2797.62 con lado 1024).
        self._bases = (
            0.0,
            1.0 + self._raiz3,
            1.0 + self._raiz3,
            1.0 + self._raiz3,
        )
        # Origen y dirección equivalentes de cada recta (documentales).
        self.diagonales = self._rectas()

    def _rectas(self) -> list:
        """Origen y dirección de cada recta dirigida, coherentes con la forma lineal.

        Se derivan de `_bases`/`_SIGNOS` para que origen, dirección y proyección
        no puedan desincronizarse:

            t(p) = (b·L + s·p)/√3   y   t(p) = (p - O)·dir
            ⇒ O_i = -b·L·s_i / (√3 · |s|²)
        """
        rectas = []
        for indice in range(4):
            signos = self._SIGNOS[indice]
            norma2 = sum(s * s for s in signos)
            direccion = tuple(s / math.sqrt(norma2) for s in signos)
            origen = tuple(
                -self._bases[indice] * self.lado * s / (self._raiz3 * norma2)
                for s in signos
            )
            rectas.append((origen, direccion))
        return rectas

    @property
    def es_geometria_canonica(self) -> bool:
        """True si el lado del cubo es el del núcleo (1024).

        La forma afín escala con el lado del cubo, así que este módulo coincide
        con el núcleo en cualquier tamaño (verificado a 1024 y 32000). La marca
        se conserva para poder distinguir la configuración por defecto.
        """
        return abs(self.lado - 1024.0) < 1e-9


    def punto_w(self, token: str) -> tuple:
        """Punto 3D determinista de un token dentro del cubo.

        Es la proyección de un hash criptográfico, no una posición semántica
        real: lo que importa es que sea determinista, uniforme y estable, para
        que dos textos con los mismos tokens den el mismo centroide.

        @param token - token ya normalizado.
        @returns terna (x, y, z) en [0, lado).
        """
        resumen = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return (
            float(int(resumen[0:8], 16) % self.lado),
            float(int(resumen[8:16], 16) % self.lado),
            float(int(resumen[16:24], 16) % self.lado),
        )

    def centroide(self, tokens: list, texto: str = "") -> tuple:
        """Punto medio de los puntos W de los tokens.

        Si no hay tokens se usa el punto del texto completo, para que una
        consulta vacía siga teniendo una firma válida.
        """
        if not tokens:
            return self.punto_w(texto)
        x = y = z = 0.0
        for token in tokens:
            px, py, pz = self.punto_w(token)
            x += px
            y += py
            z += pz
        n = float(len(tokens))
        return (x / n, y / n, z / n)

    def parametro_t(self, indice: int, punto) -> float:
        """Proyección escalar del punto sobre la diagonal `indice`.

        Forma lineal verificada punto por punto contra el núcleo:

            t_k(p) = ( b_k · L + s_k · p ) / √3

        donde `s_k` son los coeficientes (±1) de la diagonal y `b_k` su término
        constante: 0 en W1 y `1+√3 ≈ 2.7321` en W2, W3 y W4. Ese desplazamiento
        es lo que hace que las tres últimas ramas de la firma empiecen en
        `(1+√3)/3 ≈ 0.9107` en lugar de en 0.

        @param indice - 0..3, en el orden W1, W2, W3, W4.
        @param punto - terna de coordenadas dentro del cubo.
        @returns la proyección sin normalizar.
        """
        signos = self._SIGNOS[indice]
        proyeccion = signos[0] * punto[0] + signos[1] * punto[1] + signos[2] * punto[2]
        return (self._bases[indice] * self.lado + proyeccion) / self._raiz3

    def componentes_de(self, punto) -> tuple:
        """Las 4 proyecciones `t` sin normalizar."""
        return tuple(self.parametro_t(i, punto) for i in range(4))

    def firma_de_punto(self, punto) -> tuple:
        """Firma W 4D normalizada de un punto 3D.

        Equivale a `FamiliaDiagonales.calcular_firma_normalizada` del núcleo:
        divide cada proyección por el normalizador (lado/√3), no por la
        longitud de la diagonal.
        """
        return tuple(t / self.normalizador for t in self.componentes_de(punto))

    def espacios_de(self, punto) -> tuple:
        """Índice de espacio W (0..n-1) de cada diagonal para un punto.

        El núcleo acota la proyección a `[0, longitud]` (la diagonal completa)
        antes de repartirla en espacios, no al normalizador.
        """
        n = self.n_espacios
        salida = []
        for i in range(4):
            t = self.parametro_t(i, punto)
            t_acotado = max(0.0, min(t, self.longitud))
            indice = min(int(t_acotado / self.longitud * n), n - 1)
            salida.append(indice)
        return tuple(salida)

    def firma_de_texto(self, texto: str) -> FirmaW:
        """Firma W 4D completa de un texto.

        @param texto - consulta o tarea a indexar.
        @returns una {@link FirmaW} con tokens, centroide, firma y espacios.
        """
        tokens = tokenizar(texto)
        coords = self.centroide(tokens, texto or "")
        componentes = self.componentes_de(coords)
        firma = tuple(t / self.normalizador for t in componentes)
        return FirmaW(tokens, coords, componentes, firma, self.espacios_de(coords),
                      es_vacia=not tokens)

    # -- distancias ---------------------------------------------------------

    def distancia_geometrica(self, f1, f2) -> float:
        """Distancia euclídea directa entre dos firmas W 4D."""
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(f1, f2)))

    def distancia_permutaciones(self, f1, f2) -> float:
        """Distancia mínima sobre las 24 permutaciones de la segunda firma.

        Hace la comparación invariante al orden de las diagonales, de modo que
        un punto que cae simétrico respecto a un eje no se penalice. Es
        sensiblemente más caro (24 distancias en lugar de 1).
        """
        mejor = float("inf")
        # 4! = 24 permutaciones de los 4 componentes.
        for a in range(4):
            for b in range(4):
                if b == a:
                    continue
                for c in range(4):
                    if c == a or c == b:
                        continue
                    d = 6 - a - b - c  # el índice restante
                    perm = (f2[a], f2[b], f2[c], f2[d])
                    dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(f1, perm)))
                    if dist < mejor:
                        mejor = dist
        return mejor

    def distancia(self, f1: FirmaW, f2: FirmaW,
                  invariante_permutaciones: bool = ConfigW.INVARIANTE_PERMUTACIONES) -> tuple:
        """Distancia combinada W 4D + solapamiento de vocabulario.

        La geometría sola produce falsos aciertos: dos consultas sin ninguna
        palabra en común pueden caer cerca por azar. El solapamiento (Jaccard
        sobre las raíces de los tokens) actúa de penalización, y sin
        vocabulario compartido la distancia no puede bajar del umbral.

        @returns `(distancia, solapamiento)`.
        """
        geometrica = (self.distancia_permutaciones(f1.firma, f2.firma)
                      if invariante_permutaciones
                      else self.distancia_geometrica(f1.firma, f2.firma))

        conjunto1, conjunto2 = set(f1.tokens), set(f2.tokens)
        if not conjunto1 or not conjunto2:
            return geometrica, 0.0

        interseccion = len(conjunto1 & conjunto2)
        union = len(conjunto1 | conjunto2)
        solapamiento = interseccion / union if union else 0.0
        penalizacion = ConfigW.PESO_GEOMETRIA + ConfigW.PESO_SOLAPAMIENTO * (1.0 - solapamiento)
        return geometrica * penalizacion, solapamiento


# ---------------------------------------------------------------------------
# Caché semántica
# ---------------------------------------------------------------------------


class CacheSemanticaW:
    """Caché de pares consulta→valor con recuperación por similitud W 4D.

    Sustituye la coincidencia literal de cadenas por coincidencia semántica:
    una consulta reformulada recupera la respuesta ya calculada, que es el
    ahorro real de tokens.
    """

    def __init__(self, familia: FamiliaDiagonalesW = None,
                 umbral_similitud: float = ConfigW.UMBRAL_SIMILITUD,
                 max_entradas: int = ConfigW.MAX_ENTRADAS,
                 ttl_segundos: float = ConfigW.TTL_SEGUNDOS):
        self.familia = familia or FamiliaDiagonalesW()
        self.umbral = float(umbral_similitud)
        self.max_entradas = int(max_entradas)
        self.ttl = float(ttl_segundos)
        self._entradas = OrderedDict()
        self.hits_exactos = 0
        self.hits_semanticos = 0
        self.fallos = 0
        self.tokens_ahorrados = 0
        self.tokens_almacenados = 0

    @staticmethod
    def _normalizar(texto: str) -> str:
        """Normalización para la coincidencia exacta: minúsculas, sin espacios dobles."""
        return " ".join((texto or "").lower().split())

    def buscar(self, consulta: str) -> dict:
        """Busca una consulta equivalente en la caché.

        Primero intenta coincidencia exacta normalizada y después similitud
        semántica; nunca acepta una entrada si no comparte al menos un token.

        @param consulta - la consulta a resolver.
        @returns dict con `hit`, `kind`, `value` y métricas de la coincidencia.
        """
        normalizada = self._normalizar(consulta)
        firma = self.familia.firma_de_texto(normalizada)
        ahora = time.time()
        expiradas = []

        # 1) coincidencia exacta
        for clave, entrada in self._entradas.items():
            if self.ttl > 0 and entrada["expira"] and entrada["expira"] < ahora:
                expiradas.append(clave)
                continue
            if entrada["query_norm"] == normalizada:
                self._entradas.move_to_end(clave)
                self.hits_exactos += 1
                self.tokens_ahorrados += entrada["tokens"]
                return self._vista(entrada, "exacto", 0.0, 1.0, consulta)
        for clave in expiradas:
            self._entradas.pop(clave, None)

        # 2) coincidencia semántica
        #
        # Solo se consideran candidatas las entradas que comparten al menos un
        # token. Filtrar *antes* de elegir la más cercana es imprescindible: si
        # se elige primero la de menor distancia y luego se exige solapamiento,
        # una entrada sin nada en común puede adelantarse a la que sí coincide
        # (distancia pequeña por azar) y convertir un acierto válido en un fallo.
        mejor_dist, mejor_solape, mejor_entrada = float("inf"), 0.0, None
        for entrada in self._entradas.values():
            if self.ttl > 0 and entrada["expira"] and entrada["expira"] < ahora:
                continue
            dist, solape = self.familia.distancia(firma, entrada["firma"])
            if solape <= 0:
                continue
            if dist < mejor_dist:
                mejor_dist, mejor_solape, mejor_entrada = dist, solape, entrada

        if mejor_entrada is not None and mejor_dist <= self.umbral:
            self.hits_semanticos += 1
            self.tokens_ahorrados += mejor_entrada["tokens"]
            return self._vista(mejor_entrada, "semantico", mejor_dist, mejor_solape, consulta)

        self.fallos += 1
        return {
            "hit": False,
            "kind": "miss",
            "query": consulta,
            "firma": list(firma.firma),
            "tokens": list(firma.tokens),
            "umbral": self.umbral,
            "candidatos": len(self._entradas),
            "mejor_distancia": None if mejor_entrada is None else mejor_dist,
            "mejor_solapamiento": mejor_solape,
        }

    def guardar(self, consulta: str, valor, tokens: int = 0, metadata: dict = None) -> dict:
        """Guarda un resultado asociado a una consulta.

        @param consulta - consulta que produjo el resultado.
        @param valor - resultado a cachear.
        @param tokens - coste estimado en tokens de obtenerlo (para medir el ahorro).
        @param metadata - metadatos libres.
        """
        normalizada = self._normalizar(consulta)
        firma = self.familia.firma_de_texto(normalizada)
        tokens = max(0, int(tokens or 0))

        while len(self._entradas) >= self.max_entradas:
            self._entradas.popitem(last=False)

        self._entradas[firma.firma] = {
            "query": consulta,
            "query_norm": normalizada,
            "valor": valor,
            "tokens": tokens,
            "firma": firma,
            "metadata": metadata or {},
            "timestamp": time.time(),
            "expira": (time.time() + self.ttl) if self.ttl > 0 else None,
        }
        self._entradas.move_to_end(firma.firma)
        self.tokens_almacenados += tokens
        return {
            "stored": True,
            "query": consulta,
            "firma": list(firma.firma),
            "espacios": list(firma.espacios),
            "tokens": tokens,
            "entradas": len(self._entradas),
        }

    def _vista(self, entrada: dict, tipo: str, dist: float, solape: float,
               consultada: str) -> dict:
        return {
            "hit": True,
            "kind": tipo,
            "query": entrada["query"],
            "query_consultada": consultada,
            "value": entrada["valor"],
            "tokens_ahorrados": entrada["tokens"],
            "distancia": dist,
            "solapamiento": solape,
            "umbral": self.umbral,
            "firma_cache": list(entrada["firma"].firma),
            "espacios": list(entrada["firma"].espacios),
            "metadata": entrada["metadata"],
            "antiguedad_s": time.time() - entrada["timestamp"],
        }

    def estadisticas(self) -> dict:
        """Métricas de acierto y ahorro acumulado."""
        total = self.hits_exactos + self.hits_semanticos + self.fallos
        return {
            "entradas": len(self._entradas),
            "max_entradas": self.max_entradas,
            "umbral_similitud": self.umbral,
            "hits_exactos": self.hits_exactos,
            "hits_semanticos": self.hits_semanticos,
            "fallos": self.fallos,
            "hit_rate": (self.hits_exactos + self.hits_semanticos) / total if total else 0.0,
            "tokens_ahorrados": self.tokens_ahorrados,
            "tokens_almacenados": self.tokens_almacenados,
        }

    def limpiar(self) -> int:
        """Vacía la caché y devuelve cuántas entradas había."""
        cantidad = len(self._entradas)
        self._entradas.clear()
        return cantidad


# ---------------------------------------------------------------------------
# Demostración
# ---------------------------------------------------------------------------


def _demo() -> None:
    familia = FamiliaDiagonalesW()
    cache = CacheSemanticaW(familia)

    print("Firma W 4D — demostración")
    print("=" * 62)
    for texto in ["optimizar consultas vectoriales con octree",
                  "la diagonal W proyecta el punto en el cubo"]:
        f = familia.firma_de_texto(texto)
        print(f"\n{texto}")
        print(f"  tokens     : {f.tokens}")
        print(f"  centroide  : ({f.coords[0]:.2f}, {f.coords[1]:.2f}, {f.coords[2]:.2f})")
        print(f"  firma W 4D : {[round(v, 6) for v in f.firma]}")
        print(f"  espacios   : {f.espacios}")

    print("\n" + "=" * 62)
    cache.guardar("optimizar consultas vectoriales con octree", "Poda por octante.", 4200)
    for consulta in ["optimizar consultas vectoriales con octree",
                     "optimizar consultas vectoriales con octree y podado",
                     "desplegar el plugin en linux con systemd"]:
        r = cache.buscar(consulta)
        estado = f"HIT {r['kind']}" if r["hit"] else "MISS"
        print(f"  [{estado:<14}] {consulta}")

    print("\n" + "=" * 62)
    for clave, valor in cache.estadisticas().items():
        print(f"  {clave:<22} {valor}")


if __name__ == "__main__":
    _demo()
