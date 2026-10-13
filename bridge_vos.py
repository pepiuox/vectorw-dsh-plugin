#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bridge_vos.py - Puente JSON de VectorW (vOS v6.0) para el plugin DSH.

Arquitectura y autor del núcleo VectorW:
    Jose Ricardo Mantilla Mantilla (PePiuoX)
    https://github.com/PePiuoX
    Licencia LAMC v1.0 / LULA v1.1 - https://pepiuox.org/lamc/v1.0

Este archivo NO reimplementa VectorW: importa el núcleo real
(`vectorW_6.py` de la carpeta `vectorW_py`) y lo expone por
stdin/stdout como líneas JSON, para que el plugin de DeepSeek
Harness pueda usarlo como caché semántica y predictor de consultas.

Protocolo:
    entrada  : una línea = un objeto JSON {"id": n, "method": str, "params": {...}}
    salida   : una línea = un objeto JSON {"id": n, "ok": true, "result": {...}}
                             o {"id": n, "ok": false, "error": "..."}

------------------------------------------------------------------
CAPA DE COMPATIBILIDAD (parches en memoria, no se toca el repo)
------------------------------------------------------------------
`vectorW_6.py` v6.0 contiene dos defectos que rompen las rutas que este
puente necesita. Se corrigen aquí, en memoria, sin modificar el archivo
original del autor:

  1. NodoOctreeMemoriaEficiente.insertar(key, dato, coords)
     es invocado por MemoriaVectorialProduccion.escribir con los
     argumentos desplazados (el dict de datos cae en `coords`), lo que
     termina en "sequence index must be integer, not 'slice'".
     -> se normaliza `coords` (debe ser una tupla de 3 números).

  2. PredictorMarkovOrdenSuperior usa `deque` y le aplica slicing
     (`self.historial[-self.orden:]`), operación que `deque` no soporta.
     -> se sustituye el `deque` interno por una `list` (misma semántica
        de cola acotada y sí soporta slicing).

Ambos parches son idempotentes y se anuncian en `result.patches` de
`status` / `init` para que el usuario sepa que están activos.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import unicodedata
from collections import OrderedDict

BRIDGE_VERSION = "1.1.0"
CORE_MODULE = "vectorW_6"

# Palabras vacías ES/EN: no aportan posición semántica y desplazarían el centroide.
_STOPWORDS = frozenset("""
a al algo algunas algunos ante antes aqui asi aun aunque bien cada como con contra cual
cuando de del desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso
esos esta estaba estado estas este esto estos fue fueron ha hace hacia han hasta hay la
las le les lo los mas me mi mis mucho muy nada ni no nos nosotros nuestra nuestro o os
otra otro para pero poco por porque que quien se sea segun ser si sin sobre son su sus
tal tambien tanto te tiene tienen todo todos tu tus un una uno unos y ya
the is at which on an and are as be been but by can for from has have how in into it its
of or that their there these this to was were what when where who will with your
""".split())

# Normaliza cada token: sin acentos, sin sufijos de plural/género simples.
_SUFIJOS = ("ciones", "cion", "mente", "ados", "adas", "ado", "ada", "idos", "idas",
            "ido", "ida", "es", "os", "as", "s")


def _normalizar_token(token: str) -> str:
    """Minúsculas, sin acentos y con una raíz conservadora."""
    token = unicodedata.normalize("NFKD", token.lower())
    token = "".join(c for c in token if not unicodedata.combining(c))
    return token


def _raiz(token: str) -> str:
    """Raíz aproximada para tolerar plurales y género (poda/podado, cache/caches)."""
    for sufijo in _SUFIJOS:
        if len(token) > len(sufijo) + 3 and token.endswith(sufijo):
            return token[: -len(sufijo)]
    return token


def tokenizar(texto: str) -> list:
    """Tokens significativos de un texto, con raíz, sin duplicados y ordenados."""
    crudos = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", (texto or ""), flags=re.UNICODE)
    vistos, salida = set(), []
    for crudo in crudos:
        normalizado = _normalizar_token(crudo)
        if len(normalizado) < 3 or normalizado in _STOPWORDS:
            continue
        raiz = _raiz(normalizado)
        if raiz in vistos:
            continue
        vistos.add(raiz)
        salida.append(raiz)
    return salida


@contextlib.contextmanager
def _stdout_silenciado():
    """Desvía el descriptor 1 a stderr durante operaciones del núcleo.

    El núcleo VectorW imprime avisos y errores con `print(...)` sobre stdout
    (`[vOS v6] Error en escritura: ...`). Como stdout es nuestro canal de
    protocolo JSON, cualquier `print` del núcleo lo corrompería. Aquí se
    redirige el descriptor de archivo (no solo `sys.stdout`), porque el
    búfer interno de texto de Python podría conservar el destino anterior.
    """
    sys.stdout.flush()
    try:
        fd_stdout = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        yield  # sin descriptor real: nada que redirigir
        return

    guardado = os.dup(fd_stdout)
    try:
        os.dup2(sys.stderr.fileno(), fd_stdout)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(guardado, fd_stdout)
        os.close(guardado)


# ---------------------------------------------------------------------------
# Localización del núcleo VectorW
# ---------------------------------------------------------------------------

_PATCHES_APLICADOS: list[str] = []
_CORE = None
_CORE_ERROR: str | None = None
_ORIGEN_NUCLEO: str | None = None


def _cargar_nucleo(ruta_core: str | None) -> tuple:
    """Importa `vectorW_6` buscándolo en este orden:

      1. la carpeta indicada en `rutaCore`;
      2. el núcleo vendorizado en `vendor/vectorW_py/`, que hace el plugin
         **autocontenido**: funciona sin tener VectorW instalado aparte;
      3. cualquier ruta ya presente en `sys.path`.
    """
    global _CORE, _CORE_ERROR, _ORIGEN_NUCLEO

    candidatas = []
    if ruta_core:
        candidatas.append(("rutaCore", os.path.abspath(ruta_core)))
    candidatas.append(("vendor", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "vendor", "vectorW_py"
    )))

    for origen, carpeta in candidatas:
        if not os.path.isdir(carpeta):
            if origen == "rutaCore":
                return None, f"rutaCore no existe: {carpeta}"
            continue
        if carpeta not in sys.path:
            sys.path.insert(0, carpeta)
        try:
            import importlib

            with _stdout_silenciado():
                modulo = importlib.import_module(CORE_MODULE)
        except Exception as exc:  # pragma: no cover - depende del entorno
            _CORE_ERROR = f"{type(exc).__name__}: {exc}"
            if origen == "rutaCore":
                return None, _CORE_ERROR
            continue

        _aplicar_parches(modulo)
        _CORE = modulo
        _CORE_ERROR = None
        _ORIGEN_NUCLEO = origen
        return modulo, None

    return None, _CORE_ERROR or "no se encontró vectorW_6.py"


def _aplicar_parches(modulo) -> None:
    """Corrige en memoria los dos defectos bloqueantes del núcleo v6.0."""
    # --- Parche 1: slicing de deque en las cadenas de Markov -----------------
    marca_markov = "PredictorMarkovOrdenSuperior.historial: deque -> list"
    markov_cls = getattr(modulo, "PredictorMarkovOrdenSuperior", None)
    if markov_cls is not None and isinstance(
        getattr(markov_cls, "__init__", None), type(lambda: None)
    ):
        original_init = markov_cls.__init__

        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            if not isinstance(self.historial, list):
                self.historial = list(self.historial)

        if not getattr(markov_cls, "_bridge_markov_patch", False):
            markov_cls.__init__ = __init__
            markov_cls._bridge_markov_patch = True
            marca_markov = marca_markov + " [aplicado]"
        else:
            marca_markov = marca_markov + " [ya aplicado]"
    else:
        marca_markov = marca_markov + " [omitido: clase ausente]"
    _PATCHES_APLICADOS.append(marca_markov)

    # --- Parche 2: argumentos desplazados en octree.insertar -----------------
    marca_octree = "NodoOctreeMemoriaEficiente.insertar: normaliza coords"
    nodo_cls = getattr(modulo, "NodoOctreeMemoriaEficiente", None)
    if nodo_cls is not None:
        original_insertar = nodo_cls.insertar

        def insertar(self, key, dato, coords=None):
            if not _es_tripleta(coords):
                extraido = None
                if isinstance(coords, dict):
                    extraido = coords.get("coords") or coords.get("vector")
                if extraido is None and isinstance(dato, dict):
                    extraido = dato.get("coords") or dato.get("vector")
                if extraido is None:
                    extraido = self._extraer_coords(dato)
                coords = extraido
            return original_insertar(self, key, dato, coords)

        if not getattr(nodo_cls, "_bridge_insertar_patch", False):
            nodo_cls.insertar = insertar
            nodo_cls._bridge_insertar_patch = True
            marca_octree = marca_octree + " [aplicado]"
        else:
            marca_octree = marca_octree + " [ya aplicado]"
    else:
        marca_octree = marca_octree + " [omitido: clase ausente]"
    _PATCHES_APLICADOS.append(marca_octree)


def _es_tripleta(valor) -> bool:
    if not isinstance(valor, (tuple, list)) or len(valor) < 3:
        return False
    try:
        float(valor[0]), float(valor[1]), float(valor[2])
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Estado del puente
# ---------------------------------------------------------------------------


class EstadoVOS:
    """Núcleo vOS + caché semántica por firma W 4D + métricas de ahorro."""

    def __init__(self, config: dict):
        self.lock = threading.RLock()
        self.config = self._normalizar_config(config)

        self.vos = None
        self.familia = None
        self.modo = "degradado"
        self.motivo_degradado: str | None = None

        # Caché semántica: firma_w4d -> entrada
        self.entradas: "OrderedDict[tuple, dict]" = OrderedDict()

        # Métricas de ahorro de tokens
        self.hits_exactos = 0
        self.hits_semanticos = 0
        self.fallos = 0
        self.tokens_ahorrados = 0
        self.tokens_guardados = 0
        self.historial_similitud: list[float] = []

        self._iniciar_nucleo()

    # -- configuración ----------------------------------------------------

    @staticmethod
    def _normalizar_config(config: dict | None) -> dict:
        config = dict(config or {})
        normalizado = {
            "lado_cubo": int(config.get("lado_cubo", 1024)),
            "n_espacios": int(config.get("n_espacios", 8)),
            "orden_markov": int(config.get("orden_markov", 2)),
            "umbral_similitud": float(config.get("umbral_similitud", 0.15)),
            "max_entradas": int(config.get("max_entradas", 2000)),
            "ttl_segundos": float(config.get("ttl_segundos", 0)),
            "store_path": config.get("store_path") or None,
            "ruta_core": config.get("ruta_core") or None,
            "invariante_permutaciones": bool(
                config.get("invariante_permutaciones", True)
            ),
        }
        # El cubo del núcleo v6 usa 1024 por defecto; permitimos el real de
        # vOS v3.0 (32000) si el usuario lo pide explícitamente.
        if normalizado["lado_cubo"] < 8:
            normalizado["lado_cubo"] = 8
        return normalizado

    def _iniciar_nucleo(self) -> None:
        modulo, error = _cargar_nucleo(self.config["ruta_core"])
        if modulo is None:
            self.vos = None
            self.familia = None
            self.modo = "degradado"
            self.motivo_degradado = error
            return

        try:
            with _stdout_silenciado():
                self.vos = modulo.MemoriaVectorialProduccion(
                    lado_cubo=self.config["lado_cubo"],
                    n_espacios_w=self.config["n_espacios"],
                    orden_markov=self.config["orden_markov"],
                    ruta_checkpoint=os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), ".vos_checkpoint.json"
                    ),
                    ruta_modelo=os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), ".vos_modelo.pkl"
                    ),
                )
            self.familia = self.vos.familia
            self.modo = "vectorw"
            self.motivo_degradado = None
        except Exception as exc:  # pragma: no cover
            self.vos = None
            self.familia = None
            self.modo = "degradado"
            self.motivo_degradado = f"{type(exc).__name__}: {exc}"

    # -- firma W 4D -------------------------------------------------------

    def _punto_w(self, token: str) -> tuple:
        """Punto 3D determinista de un token dentro del cubo de memoria."""
        h = hashlib.sha256(token.encode("utf-8")).hexdigest()
        lado = self.config["lado_cubo"]
        return (
            float(int(h[0:8], 16) % lado),
            float(int(h[8:16], 16) % lado),
            float(int(h[16:24], 16) % lado),
        )

    def firma_de(self, texto: str) -> tuple:
        """Firma W 4D normalizada de un texto.

        Cada token significativo se proyecta en el cubo de memoria con sha256
        y el texto se representa por el **centroide** de esos puntos; el
        centroide se proyecta luego sobre las 4 diagonales W del núcleo real.

        Es deliberadamente distinto de hashear el texto completo: con el hash
        íntegro, «poda espacial» y «podado espacial» caían en extremos opuestos
        del cubo y ninguna reformulación encontraba su entrada. Con el
        centroide, dos consultas que comparten vocabulario quedan cerca y las
        que no comparten nada quedan lejos.
        """
        tokens = tokenizar(texto)
        if self.familia is not None:
            return tuple(self.familia.calcular_firma_normalizada(self._centroide(tokens, texto)))

        if not tokens:
            h = hashlib.sha256(texto.encode("utf-8")).digest()
            return tuple(
                int.from_bytes(h[i * 4:(i + 1) * 4], "big") / 0xFFFFFFFF for i in range(4)
            )
        centro = self._centroide(tokens, texto)
        lado = float(self.config["lado_cubo"])
        return tuple(c / lado for c in centro)

    def _centroide(self, tokens: list, texto: str) -> tuple:
        """Punto medio de los tokens; si no hay tokens, el punto del texto."""
        if not tokens:
            return self._punto_w(texto)
        puntos = [self._punto_w(t) for t in tokens]
        n = len(puntos)
        return (
            sum(p[0] for p in puntos) / n,
            sum(p[1] for p in puntos) / n,
            sum(p[2] for p in puntos) / n,
        )

    def espacios_de(self, texto: str) -> tuple:
        """Clasificación del texto en los espacios W de cada diagonal."""
        if self.familia is None:
            return ()
        return tuple(
            self.familia.clasificar_en_espacios(self._centroide(tokenizar(texto), texto))
        )

    def distancia_geometrica(self, f1: tuple, f2: tuple) -> float:
        """Distancia entre firmas W 4D; usa el núcleo si está disponible."""
        if self.familia is not None:
            return float(
                self.familia.distancia_entre_firmas(
                    f1, f2, invariante_permutaciones=self.config["invariante_permutaciones"]
                )
            )
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(f1, f2)))

    def distancia(self, firma1: tuple, tokens1: list,
                  firma2: tuple, tokens2: list) -> tuple:
        """Distancia combinada firma W 4D + solapamiento de vocabulario.

        La geometría sola no basta: dos consultas sin ninguna palabra en común
        pueden caer cerca por azar y producir un falso acierto, que en una
        caché de agente es peor que un fallo. El solapamiento actúa de
        penalización, de modo que sin vocabulario compartido la distancia se
        dispara muy por encima de cualquier umbral razonable.

        @returns `(distancia, solapamiento)`.
        """
        geometrica = self.distancia_geometrica(firma1, firma2)
        # `tokens` puede venir ausente en entradas antiguas: se recalcula del
        # texto normalizado, que siempre está guardado.
        conjunto1 = set(tokens1 or [])
        conjunto2 = set(tokens2 or [])
        if not conjunto1 or not conjunto2:
            return geometrica, 0.0
        interseccion = len(conjunto1 & conjunto2)
        union = len(conjunto1 | conjunto2)
        solapamiento = interseccion / union if union else 0.0
        penalizacion = 0.35 + 1.3 * (1.0 - solapamiento)
        return geometrica * penalizacion, solapamiento

    # -- caché semántica --------------------------------------------------

    def _buscar(self, query: str) -> dict:
        normalizada = self._normalizar(query)
        tokens = tokenizar(normalizada)
        firma = self.firma_de(normalizada)
        ahora = time.time()
        ttl = self.config["ttl_segundos"]

        with self.lock:
            self._expulsar_expiradas(ahora, ttl)

            # 1) coincidencia exacta normalizada
            for firma_guardada, entrada in self.entradas.items():
                if entrada["query_norm"] == normalizada:
                    self.entradas.move_to_end(firma_guardada)
                    self.hits_exactos += 1
                    self.tokens_ahorrados += entrada["tokens"]
                    return self._vista_acierto(entrada, "exacto", 0.0, 1.0, firma, query)

            # 2) coincidencia semántica: firma W 4D + solapamiento de vocabulario
            #
            # Solo compiten las entradas con al menos un token en común. El
            # filtro va ANTES de elegir la más cercana: si se elige primero por
            # distancia y luego se exige solapamiento, una entrada sin nada en
            # común (cercana por azar) puede adelantarse a la que sí coincide y
            # convertir un acierto válido en un fallo.
            mejor_dist = float("inf")
            mejor_solape = 0.0
            mejor_entrada = None
            for firma_guardada, entrada in self.entradas.items():
                if entrada.get("expira") and entrada["expira"] < ahora:
                    continue
                dist, solape = self.distancia(
                    firma, tokens, firma_guardada,
                    entrada.get("tokens_texto") or tokenizar(entrada.get("query_norm", "")),
                )
                if solape <= 0:
                    continue
                if dist < mejor_dist:
                    mejor_dist, mejor_solape, mejor_entrada = dist, solape, entrada

            umbral = self.config["umbral_similitud"]
            if mejor_entrada is not None and mejor_dist <= umbral:
                self.hits_semanticos += 1
                self.tokens_ahorrados += mejor_entrada["tokens"]
                self.historial_similitud.append(mejor_dist)
                return self._vista_acierto(mejor_entrada, "semantico", mejor_dist,
                                           mejor_solape, firma, query)

            self.fallos += 1
            return {
                "hit": False,
                "kind": "miss",
                "query": query,
                "firma_w": _redondear(firma),
                "tokens": tokens,
                "espacios_w": list(self.espacios_de(normalizada)),
                "umbral": umbral,
                "candidatos": len(self.entradas),
                "mejor_distancia": None if mejor_entrada is None else round(mejor_dist, 5),
                "mejor_solapamiento": round(mejor_solape, 4),
                "motivo": ("sin vocabulario en comun"
                           if mejor_entrada is None and self.entradas else None),
            }

    def _guardar(self, query: str, valor, tokens: int, metadata: dict | None) -> dict:
        normalizada = self._normalizar(query)
        firma = self.firma_de(normalizada)
        tokens_texto = tokenizar(normalizada)
        tokens = max(0, int(tokens or 0))
        ttl = self.config["ttl_segundos"]

        with self.lock:
            while len(self.entradas) >= self.config["max_entradas"]:
                self.entradas.popitem(last=False)

            self.entradas[firma] = {
                "query": query,
                "query_norm": normalizada,
                "valor": valor,
                "tokens": tokens,
                "tokens_texto": tokens_texto,
                "metadata": metadata or {},
                "timestamp": time.time(),
                "expira": (time.time() + ttl) if ttl > 0 else None,
                "espacios_w": list(self.espacios_de(normalizada)),
                "firma_w": firma,
            }
            self.entradas.move_to_end(firma)
            self.tokens_guardados += tokens

            # Entrenar el núcleo: cada entrada es un acceso en el espacio W,
            # de modo que el predictor aprende el flujo real de consultas.
            self._entrenar_nucleo(normalizada)

            return {
                "stored": True,
                "query": query,
                "firma_w": _redondear(firma),
                "tokens_texto": tokens_texto,
                "espacios_w": list(self.espacios_de(normalizada)),
                "tokens": tokens,
                "entradas": len(self.entradas),
            }

    def guardar_valor(self, query: str, valor, tokens: int = 0,
                      metadata: dict | None = None) -> dict:
        with self.lock:
            return self._guardar(query, valor, tokens, metadata)

    # -- predicción -------------------------------------------------------

    def predecir(self, n: int = 5) -> dict:
        n = max(1, min(int(n or 5), 20))
        with self.lock:
            puntos: list = []
            if self.vos is not None:
                try:
                    crudos = self.vos.predictor.predecir_proximos_puntos(n=n)
                    puntos = [
                        {"coords": _redondear(p), "confianza": round(float(c), 4)}
                        for p, c in crudos
                    ]
                except Exception as exc:  # pragma: no cover
                    self.motivo_degradado = f"predictor: {type(exc).__name__}: {exc}"

            recientes = list(self.entradas.values())[-8:]
            return {
                "puntos_w": puntos,
                "consultas_recientes": [e["query"] for e in recientes],
                "sugerencias": self._sugerencias(recientes, n),
                "modo": self.modo,
            }

    def _sugerencias(self, recientes: list, n: int) -> list:
        """Predicción de la próxima consulta a partir del historial semántico."""
        if not recientes:
            return []
        ultima = recientes[-1]
        sugerencias = []
        for entrada in reversed(recientes[:-1]):
            dist, solape = self.distancia(
                ultima["firma_w"], ultima.get("tokens_texto", []),
                entrada["firma_w"], entrada.get("tokens_texto", []),
            )
            sugerencias.append(
                {
                    "query": entrada["query"],
                    "confianza": round(max(0.0, 1.0 - dist * 2), 4),
                    "distancia_w": round(dist, 5),
                    "solapamiento": round(solape, 4),
                }
            )
        sugerencias.sort(key=lambda x: x["confianza"], reverse=True)
        vistos, salida = set(), []
        for s in sugerencias:
            if s["query"] in vistos:
                continue
            vistos.add(s["query"])
            salida.append(s)
            if len(salida) >= n:
                break
        return salida

    # -- núcleo / métricas ------------------------------------------------

    def _normalizar(self, texto: str) -> str:
        return " ".join((texto or "").lower().split())

    def _vista_acierto(self, entrada: dict, tipo: str, dist: float, solape: float,
                       firma_nueva: tuple, consultada: str) -> dict:
        return {
            "hit": True,
            "kind": tipo,
            "query": entrada["query"],
            "query_consultada": consultada,
            "value": entrada["valor"],
            "tokens_ahorrados": entrada["tokens"],
            "distancia_w": round(float(dist), 5),
            "solapamiento": round(float(solape), 4),
            "umbral": self.config["umbral_similitud"],
            "firma_w": _redondear(firma_nueva),
            "firma_cache": _redondear(entrada["firma_w"]),
            "espacios_w": entrada.get("espacios_w", []),
            "metadata": entrada.get("metadata", {}),
            "antiguedad_s": round(time.time() - entrada["timestamp"], 3),
        }

    def _expulsar_expiradas(self, ahora: float, ttl: float) -> None:
        if ttl <= 0:
            return
        expiradas = [
            f for f, e in self.entradas.items()
            if e.get("expira") and e["expira"] < ahora
        ]
        for f in expiradas:
            self.entradas.pop(f, None)

    def _entrenar_nucleo(self, texto: str) -> None:
        """Registra la consulta como acceso en el cubo W del núcleo."""
        if self.vos is None:
            return
        try:
            h = hashlib.sha256(texto.encode("utf-8")).hexdigest()
            lado = self.config["lado_cubo"]
            coords = (
                float(int(h[0:8], 16) % lado),
                float(int(h[8:16], 16) % lado),
                float(int(h[16:24], 16) % lado),
            )
            with _stdout_silenciado():
                self.vos.familia.registrar_acceso(coords)
                self.vos.predictor.registrar_acceso(coords)
        except Exception:  # pragma: no cover - el entrenamiento es best-effort
            pass

    def metricas(self) -> dict:
        with self.lock:
            total = self.hits_exactos + self.hits_semanticos + self.fallos
            nucleo = {}
            if self.vos is not None:
                try:
                    nucleo = self.vos.estadisticas_completas()
                except Exception:  # pragma: no cover
                    nucleo = {}

            datos_octree = nucleo.get("octree", {}).get("total_datos", 0)
            exactos, semanticos = self.hits_exactos, self.hits_semanticos
            tokens_evitados = self.tokens_ahorrados
            return {
                "modo": self.modo,
                "motivo_degradado": self.motivo_degradado,
                "origen_nucleo": _ORIGEN_NUCLEO,
                "parches": list(_PATCHES_APLICADOS),
                "version_bridge": BRIDGE_VERSION,
                "cache_semantica": {
                    "entradas": len(self.entradas),
                    "max_entradas": self.config["max_entradas"],
                    "umbral_similitud": self.config["umbral_similitud"],
                    "hits_exactos": exactos,
                    "hits_semanticos": semanticos,
                    "fallos": self.fallos,
                    "hit_rate": (exactos + semanticos) / total if total else 0.0,
                    "tokens_ahorrados_efectivos": tokens_evitados,
                    "tokens_almacenados": self.tokens_guardados,
                },
                "nucleo_vectorw": {
                    "datos_en_octree": datos_octree,
                    "cache_nucleo": nucleo.get("cache", {}),
                    "predictor": nucleo.get("predictor", {}),
                    "familia_w": nucleo.get("familia_w", {}),
                    "episodios": nucleo.get("episodios", 0),
                },
                "distancia_media_aciertos": (
                    sum(self.historial_similitud) / len(self.historial_similitud)
                    if self.historial_similitud else None
                ),
                "uptime_s": round(time.time() - self.t_inicio, 3),
                "capacidades": self.capacidades(),
            }

    def capacidades(self) -> dict:
        """Qué ofrece el núcleo y en qué modo se está ejecutando."""
        capacidades = {
            "cache_semantica_firma_w4d": True,
            "prediccion_markov": self.vos is not None,
            "octree_memoria_3d": self.vos is not None,
            "compresion_hibrida": self.vos is not None,
            "invariante_permutaciones": self.config["invariante_permutaciones"],
            "espacios_por_diagonal": self.config["n_espacios"],
            "diagonales": 4 if self.vos is not None else 0,
        }
        return capacidades

    def purgar(self) -> dict:
        with self.lock:
            cantidad = len(self.entradas)
            self.entradas.clear()
            return {"purgadas": cantidad}

    # -- persistencia -----------------------------------------------------

    def persistir(self, path: str) -> dict:
        with self.lock:
            datos = {
                "version": BRIDGE_VERSION,
                "guardado_en": time.time(),
                "config": self.config,
                "entradas": [
                    {
                        "firma_w": list(f),
                        "query": e["query"],
                        "query_norm": e["query_norm"],
                        "valor": e["valor"],
                        "tokens": e["tokens"],
                        "tokens_texto": e.get("tokens_texto", []),
                        "metadata": e["metadata"],
                        "timestamp": e["timestamp"],
                        "expira": e["expira"],
                        "espacios_w": e["espacios_w"],
                    }
                    for f, e in self.entradas.items()
                ],
                "metricas": {
                    "hits_exactos": self.hits_exactos,
                    "hits_semanticos": self.hits_semanticos,
                    "fallos": self.fallos,
                    "tokens_ahorrados": self.tokens_ahorrados,
                    "tokens_guardados": self.tokens_guardados,
                },
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(datos, fh, ensure_ascii=False)
            return {"path": os.path.abspath(path), "entradas": len(self.entradas)}

    def restaurar(self, path: str) -> dict:
        if not os.path.isfile(path):
            return {"restaurado": False, "motivo": f"no existe: {path}"}
        with open(path, "r", encoding="utf-8") as fh:
            datos = json.load(fh)

        with self.lock:
            restauradas = 0
            for item in datos.get("entradas", []):
                firma = tuple(item["firma_w"])
                self.entradas[firma] = {
                    "query": item["query"],
                    "query_norm": item["query_norm"],
                    "valor": item["valor"],
                    "tokens": item["tokens"],
                    "tokens_texto": item.get("tokens_texto") or tokenizar(item["query_norm"]),
                    "metadata": item.get("metadata", {}),
                    "timestamp": item["timestamp"],
                    "expira": item.get("expira"),
                    "espacios_w": item.get("espacios_w", []),
                    "firma_w": firma,
                }
                restauradas += 1
            metricas = datos.get("metricas", {})
            self.hits_exactos = metricas.get("hits_exactos", 0)
            self.hits_semanticos = metricas.get("hits_semanticos", 0)
            self.fallos = metricas.get("fallos", 0)
            self.tokens_ahorrados = metricas.get("tokens_ahorrados", 0)
            self.tokens_guardados = metricas.get("tokens_guardados", 0)
            return {"restaurado": True, "path": os.path.abspath(path),
                    "entradas": restauradas}


def _redondear(valor, nd: int = 6):
    if isinstance(valor, (tuple, list)):
        return [round(float(v), nd) for v in valor]
    if isinstance(valor, float):
        return round(valor, nd)
    return valor


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------

_ESTADO: EstadoVOS | None = None


def _estado() -> EstadoVOS:
    global _ESTADO
    if _ESTADO is None:
        _ESTADO = EstadoVOS({})
        _ESTADO.t_inicio = time.time()
    return _ESTADO


def _asegurar_estado(params: dict) -> EstadoVOS:
    """Crea el estado en el primer uso, o lo reconfigura si `init` cambia config."""
    global _ESTADO
    config = params.get("config") or {}
    if _ESTADO is None:
        _ESTADO = EstadoVOS(config)
        _ESTADO.t_inicio = time.time()
    elif config and _ESTADO.config != EstadoVOS._normalizar_config(config):
        # `init` con una configuración distinta reconstruye el núcleo.
        entradas = _ESTADO.entradas
        nuevo = EstadoVOS(config)
        nuevo.t_inicio = _ESTADO.t_inicio
        nuevo.entradas = entradas
        _ESTADO = nuevo
    return _ESTADO


def _manejar(peticion: dict) -> dict:
    metodo = peticion.get("method")
    params = peticion.get("params") or {}
    estado = _asegurar_estado(params)

    if metodo == "init":
        return {
            "modo": estado.modo,
            "motivo_degradado": estado.motivo_degradado,
            "origen_nucleo": _ORIGEN_NUCLEO,
            "parches": list(_PATCHES_APLICADOS),
            "config": estado.config,
            "capacidades": estado.capacidades(),
            "version_bridge": BRIDGE_VERSION,
            "core_error": _CORE_ERROR,
        }
    if metodo == "status":
        return estado.metricas()
    if metodo == "firma":
        return {
            "firma_w": _redondear(estado.firma_de(params.get("query", ""))),
            "espacios_w": list(estado.espacios_de(params.get("query", ""))),
        }
    if metodo == "cache_check":
        return estado._buscar(params.get("query", ""))
    if metodo == "cache_store":
        return estado.guardar_valor(
            params.get("query", ""),
            params.get("value"),
            params.get("tokens", 0),
            params.get("metadata"),
        )
    if metodo == "predict":
        return estado.predecir(params.get("n", 5))
    if metodo == "purge":
        return estado.purgar()
    if metodo == "persist":
        return estado.persistir(params.get("path") or "vectorw_plugin_state.json")
    if metodo == "restore":
        return estado.restaurar(params.get("path") or "vectorw_plugin_state.json")
    if metodo == "ping":
        return {"pong": True, "modo": estado.modo}

    raise ValueError(f"metodo desconocido: {metodo}")


def main() -> int:
    # Todo el protocolo es UTF-8 y una línea por mensaje.
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except AttributeError:  # pragma: no cover - intérpretes antiguos
        pass

    for linea in sys.stdin:
        linea = linea.strip().lstrip("\ufeff")
        if not linea:
            continue
        try:
            peticion = json.loads(linea)
        except json.JSONDecodeError as exc:
            _emitir({"id": None, "ok": False, "error": f"JSON invalido: {exc}"})
            continue

        pid = peticion.get("id")
        try:
            # El núcleo imprime avisos en stdout: se silencia mientras trabaja
            # para que jamás se mezclen con el canal de protocolo JSON.
            with _stdout_silenciado():
                resultado = _manejar(peticion)
            _emitir({"id": pid, "ok": True, "result": resultado})
        except Exception as exc:  # pragma: no cover - defensivo
            _emitir({"id": pid, "ok": False,
                     "error": f"{type(exc).__name__}: {exc}"})
    return 0


def _emitir(objeto: dict) -> None:
    sys.stdout.write(json.dumps(objeto, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
