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
from collections import OrderedDict, deque

BRIDGE_VERSION = "1.4.0"
CORE_MODULE = "vectorW_6"

# Catálogo de herramientas del plugin. Se indexa como recurso de tipo
# `herramienta` para que `recurso_buscar` pueda recomendar la herramienta
# correcta, no solo la skill correcta. Es una copia deliberada y mínima de las
# descripciones de `lib/index.js`: si allí cambian, este catálogo debe seguirlas.
CATALOGO_HERRAMIENTAS = (
    ("vector_cache_check", "Comprueba si una consulta equivalente ya está en la "
     "caché semántica W 4D antes de repetir una búsqueda o una lectura costosa."),
    ("vector_cache_store", "Guarda el resultado de una consulta en la caché "
     "semántica W 4D con su coste en tokens para reutilizarlo después."),
    ("vector_predict", "Predice las próximas consultas probables a partir del "
     "historial (Markov de orden superior + Kalman) para hacer prefetch."),
    ("vector_stats", "Informa del estado del subsistema: aciertos, tokens "
     "ahorrados, entropía por diagonal y métricas de la memoria SQLite."),
    ("vector_persist", "Guarda o restaura en disco el estado de la caché para "
     "conservar el ahorro entre sesiones."),
    ("vector_purge", "Vacía la caché semántica cuando el contexto ya no es fiable."),
    ("vector_proceso_buscar", "Recupera tareas ya resueltas y lecciones "
     "aprendidas semánticamente equivalentes, antes de repetir trabajo."),
    ("vector_proceso_guardar", "Guarda un proceso resuelto (pasos + resultado) y "
     "una lección opcional en la memoria SQLite, para no repetir la tarea."),
    ("vector_recurso_buscar", "Busca semánticamente en el catálogo indexado de "
     "skills, agentes, documentos y herramientas del preset."),
)


class _HistorialRebanable(deque):
    """`deque` que permite slicing, y solo para lo que usa el núcleo.

    El núcleo guarda el historial de Markov en un `deque` con `maxlen=10000` y
    luego le aplica slicing (`historial[-orden:]`), operación no soportada.
    Convertirlo en `list` resolvía el slicing pero **eliminaba el límite**, así
    que la memoria crecía sin cota. Esta subclase conserva ambos.
    """

    def __getitem__(self, indice):
        if isinstance(indice, slice):
            return list(self)[indice]
        return deque.__getitem__(self, indice)

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


# Marcadores de negación/polaridad. Se usan como GATE antes de aceptar un
# acierto: «no optimizar X» y «optimizar X» comparten todos los tokens
# significativos («no» es palabra vacía), así que sin este gate la caché
# devolvería lo contrario de lo pedido. Medido en el análisis del núcleo.
_NEGACIONES = frozenset("""
no sin nunca jamas ni evitar evita evitando desactivar desactiva desactivado
deshabilitar deshabilita deshabilitado quitar quita quitando eliminar elimina
eliminando descartar descarta descartando prohibir prohibe prohibido impedir
impide incorrecto erroneo mal falla fallo
""".split())


def _polaridad(texto: str) -> int:
    """Devuelve -1 si el texto contiene una negación, 0 si es afirmativo.

    No intenta entender la frase: solo separa «hacer» de «no hacer», que es el
    error de recuperación más caro en una caché de agente.
    """
    palabras = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", (texto or "").lower())
    for palabra in palabras:
        if palabra in _NEGACIONES:
            return -1
    return 0


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
            # `rutaCore` es una PREFERENCIA, no una obligación: si apunta a una
            # carpeta sin vectorW_6.py, se sigue probando el núcleo vendorizado.
            # Antes se devolvía None y el plugin quedaba degradado aunque el
            # vendor estuviera sano.
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
            if not isinstance(self.historial, _HistorialRebanable):
                # `deque` no admite slicing y la lista plana perdía el límite
                # `maxlen=10000` del núcleo, así que el historial crecía sin
                # cota. Esta subclase permite rebanar conservando el tope.
                self.historial = _HistorialRebanable(
                    self.historial, maxlen=getattr(self.historial, "maxlen", None) or 10000
                )

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
        # Contador monótono para claves únicas. `time.time()` NO sirve aquí: el
        # reloj de Windows avanza en saltos de ~15 ms, así que dos guardados
        # seguidos generaban la misma clave y el segundo sobrescribía al primero
        # (los episodios y el octree contaban menos entradas de las reales).
        self._secuencia = 0
        # Momento de arranque. Antes se asignaba desde fuera (`_estado()`), así
        # que un `EstadoVOS` construido directamente fallaba en `metricas()`.
        self.t_inicio = time.time()

        # --- índices de la caché (optimización de la búsqueda) ------------
        # Índice invertido léxico: token -> firmas. Permite generar candidatas
        # sin recorrer las 2000 entradas y sin perder recall, porque el filtro
        # de tokens compartidos ya era obligatorio antes de puntuar geometría.
        self.indice_tokens: dict[str, set] = {}
        # Celdas W (4 espacios) -> firmas. Complemento geométrico opcional.
        self.indice_espacios: dict[tuple, set] = {}
        # query_norm -> firma (acierto exacto O(1)) y huella -> firma (dedupe).
        self.indice_norm: dict[str, tuple] = {}
        self.indice_huellas: dict[str, tuple] = {}
        self.consultas_indice = 0
        self.fallbacks_indice = 0
        self.deduplicadas = 0
        self.descartes_polaridad = 0

        # --- memoria SQLite de procesos y autoaprendizaje -----------------
        self.memoria = None
        self.motivo_memoria: str | None = None
        self.ruta_memoria: str | None = None
        self.catalogo: dict = {"skills": 0, "documentos": 0, "herramientas": 0}

        self._iniciar_nucleo()
        self._iniciar_memoria()
        self._indexar_catalogo()

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
            # Evidencia léxica mínima para aceptar un acierto semántico. Con un
            # solo token en común se producían falsos aciertos; ver `_buscar`.
            "min_tokens_comunes": int(config.get("min_tokens_comunes", 2)),
            # Evidencia léxica mínima para aceptar un PROCESO ya resuelto. Más
            # exigente que la caché: dos palabras genéricas («mysql», «tabla»)
            # no identifican una tarea.
            "min_tokens_procesos": int(config.get("min_tokens_procesos", 3)),
            "min_solapamiento": float(config.get("min_solapamiento", 0.0)),
            # --- memoria de procesos / autoaprendizaje -------------------
            "ruta_memoria": str(config.get("ruta_memoria") or "").strip(),
            "ruta_skills": str(config.get("ruta_skills") or "").strip(),
            "ruta_documentos": str(config.get("ruta_documentos") or "").strip(),
            "umbral_procesos": float(config.get("umbral_procesos", 0.22)),
            "umbral_recursos": float(config.get("umbral_recursos", 0.35)),
            "presupuesto_caracteres": int(config.get("presupuesto_caracteres", 6000)),
            "max_tokens_respuesta": int(config.get("max_tokens_respuesta", 1500)),
            "usar_indice_espacios": bool(config.get("usar_indice_espacios", True)),
            "reentrenar_al_restaurar": bool(config.get("reentrenar_al_restaurar", True)),
            "persistir_al_cerrar": bool(config.get("persistir_al_cerrar", False)),
        }
        # Saneado: una errata de configuración no debe degradar ni tumbar el
        # puente (n_espacios=0 divide por cero en el núcleo; max_entradas=0
        # hacía fallar la expulsión con KeyError).
        normalizado["lado_cubo"] = max(8, normalizado["lado_cubo"])
        normalizado["n_espacios"] = max(1, normalizado["n_espacios"])
        normalizado["orden_markov"] = max(1, normalizado["orden_markov"])
        normalizado["max_entradas"] = max(1, normalizado["max_entradas"])
        normalizado["ttl_segundos"] = max(0.0, normalizado["ttl_segundos"])
        normalizado["min_tokens_comunes"] = max(1, normalizado["min_tokens_comunes"])
        normalizado["min_tokens_procesos"] = max(1, normalizado["min_tokens_procesos"])
        normalizado["min_solapamiento"] = min(1.0, max(0.0, normalizado["min_solapamiento"]))
        normalizado["umbral_procesos"] = min(1.0, max(0.01, normalizado["umbral_procesos"]))
        normalizado["umbral_recursos"] = min(1.0, max(0.05, normalizado["umbral_recursos"]))
        normalizado["presupuesto_caracteres"] = max(500, normalizado["presupuesto_caracteres"])
        normalizado["max_tokens_respuesta"] = max(100, normalizado["max_tokens_respuesta"])
        if not (0.0 < normalizado["umbral_similitud"] <= 1.0):
            normalizado["umbral_similitud"] = 0.15
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

    # -- memoria SQLite / catálogo ---------------------------------------

    def _iniciar_memoria(self) -> None:
        """Abre la memoria de procesos en SQLite.

        La memoria es OPCIONAL: si el módulo o la base fallan, la caché W 4D
        sigue funcionando y `vector_stats` declara la degradación. Nunca se
        oculta: un fallo de persistencia no debe tumbar la herramienta principal.
        """
        try:
            import memoria_vectorw as modulo_memoria
        except Exception as exc:  # pragma: no cover - instalación incompleta
            self.memoria = None
            self.motivo_memoria = f"no se pudo importar memoria_vectorw: {exc}"
            return

        try:
            carpeta_paquete = os.path.dirname(os.path.abspath(__file__))
            self.ruta_memoria = modulo_memoria.resolver_ruta_memoria(
                self.config["ruta_memoria"], carpeta_paquete
            )
            self.memoria = modulo_memoria.MemoriaVectorW(
                self.ruta_memoria,
                presupuesto_caracteres=self.config["presupuesto_caracteres"],
            )
            self.motivo_memoria = None
        except Exception as exc:  # pragma: no cover - base bloqueada/corrupta
            self.memoria = None
            self.motivo_memoria = f"{type(exc).__name__}: {exc}"

    def _indexar_catalogo(self) -> None:
        """Indexa las skills y documentos configurados como recursos buscables.

        Es la integración con los agentes del preset: cada `SKILL.md` se indexa
        con su nombre, descripción, `whenToUse` y un extracto, de modo que el
        agente pueda preguntar «¿qué skill resuelve esto?» en vez de cargar
        trece documentos para descubrirlo.
        """
        if self.memoria is None:
            return

        import glob

        contadores = {"skills": 0, "documentos": 0, "herramientas": 0}

        def indice_de(texto: str) -> tuple:
            tokens_texto = tokenizar(texto)
            coords = self._centroide(tokens_texto, texto)
            return (tokens_texto, self._firma_de_coords(coords),
                    list(self._espacios_de_coords(coords)))

        # 1) Skills del preset: <ruta_skills>/*/SKILL.md
        ruta_skills = self.config["ruta_skills"]
        if ruta_skills and os.path.isdir(ruta_skills):
            for archivo in sorted(glob.glob(os.path.join(ruta_skills, "*", "SKILL.md"))):
                try:
                    metadatos, cuerpo = _leer_skill_md(archivo)
                except OSError:
                    continue
                nombre = metadatos.get("name") or os.path.basename(os.path.dirname(archivo))
                descripcion = metadatos.get("description", "")
                cuando = metadatos.get("whenToUse", "")
                texto_busqueda = " ".join(
                    [nombre, descripcion, cuando, cuerpo[:2500]]
                )
                tokens_texto, firma, espacios = indice_de(texto_busqueda)
                self.memoria.indexar_recurso(
                    clave=f"skill:{nombre}",
                    tipo="skill",
                    nombre=nombre,
                    ruta=archivo,
                    descripcion=descripcion or cuando,
                    extracto=_extracto_legible(cuerpo),
                    contenido_hash=hashlib.sha256(texto_busqueda.encode("utf-8")).hexdigest(),
                    firma_w=firma,
                    espacios_w=espacios,
                    tokens_texto=tokens_texto,
                )
                contadores["skills"] += 1

        # 2) Documentos: <ruta_documentos>/**/*.md
        ruta_documentos = self.config["ruta_documentos"]
        if ruta_documentos and os.path.isdir(ruta_documentos):
            for archivo in sorted(glob.glob(os.path.join(ruta_documentos, "**", "*.md"),
                                             recursive=True)):
                try:
                    with open(archivo, "r", encoding="utf-8", errors="replace") as fh:
                        cuerpo = fh.read(12000)
                except OSError:
                    continue
                relativa = os.path.relpath(archivo, ruta_documentos)
                nombre = os.path.splitext(os.path.basename(archivo))[0]
                texto_busqueda = f"{nombre}\n{cuerpo[:6000]}"
                tokens_texto, firma, espacios = indice_de(texto_busqueda)
                self.memoria.indexar_recurso(
                    clave=f"documento:{relativa}",
                    tipo="documento",
                    nombre=nombre,
                    ruta=archivo,
                    descripcion=_primera_frase(cuerpo),
                    extracto=_extracto_legible(cuerpo),
                    contenido_hash=hashlib.sha256(cuerpo.encode("utf-8")).hexdigest(),
                    firma_w=firma,
                    espacios_w=espacios,
                    tokens_texto=tokens_texto,
                )
                contadores["documentos"] += 1

        # 3) Herramientas del propio plugin: permiten recomendar la herramienta
        #    correcta (guardar frente a consultar) sin leer su esquema completo.
        for nombre, descripcion in CATALOGO_HERRAMIENTAS:
            texto_busqueda = f"{nombre} {descripcion}"
            tokens_texto, firma, espacios = indice_de(texto_busqueda)
            self.memoria.indexar_recurso(
                clave=f"herramienta:{nombre}",
                tipo="herramienta",
                nombre=nombre,
                ruta="",
                descripcion=descripcion,
                extracto=descripcion,
                contenido_hash=hashlib.sha256(texto_busqueda.encode("utf-8")).hexdigest(),
                firma_w=firma,
                espacios_w=espacios,
                tokens_texto=tokens_texto,
            )
            contadores["herramientas"] += 1

        self.catalogo = contadores

    # -- índices de la caché ---------------------------------------------

    def _clave_huella(self, tokens_texto: list, texto: str) -> str:
        """Huella semántica estable: raíces ordenadas (dedupe sin palabras vacías).

        Incluye la polaridad: «no optimizar X» y «optimizar X» no son la misma
        tarea y no deben colisionar en la deduplicación.
        """
        unicos = sorted(set(tokens_texto or []))
        prefijo = "neg|" if _polaridad(texto) else ""
        if unicos:
            return prefijo + " ".join(unicos)
        return prefijo + "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()[:32]

    def _indexar_entrada(self, firma: tuple, entrada: dict) -> None:
        """Registra una entrada en los tres índices de la caché."""
        for token in entrada.get("tokens_texto") or []:
            self.indice_tokens.setdefault(token, set()).add(firma)
        clave = tuple(entrada.get("espacios_w") or ())
        if clave:
            self.indice_espacios.setdefault(clave, set()).add(firma)
        self.indice_norm[entrada["query_norm"]] = firma
        self.indice_huellas[entrada["huella"]] = firma

    def _desindexar_entrada(self, firma: tuple) -> None:
        """Retira una entrada de todos los índices (expulsión, purga, reemplazo)."""
        entrada = self.entradas.pop(firma, None)
        if entrada is None:
            return
        for token in entrada.get("tokens_texto") or []:
            firmas = self.indice_tokens.get(token)
            if firmas is not None:
                firmas.discard(firma)
                if not firmas:
                    self.indice_tokens.pop(token, None)
        clave = tuple(entrada.get("espacios_w") or ())
        if clave:
            firmas = self.indice_espacios.get(clave)
            if firmas is not None:
                firmas.discard(firma)
                if not firmas:
                    self.indice_espacios.pop(clave, None)
        if self.indice_norm.get(entrada["query_norm"]) == firma:
            self.indice_norm.pop(entrada["query_norm"], None)
        if self.indice_huellas.get(entrada["huella"]) == firma:
            self.indice_huellas.pop(entrada["huella"], None)

    def _reconstruir_indices(self) -> None:
        """Rehace los índices desde `self.entradas` (tras restaurar o purgar)."""
        self.indice_tokens.clear()
        self.indice_espacios.clear()
        self.indice_norm.clear()
        self.indice_huellas.clear()
        for firma, entrada in self.entradas.items():
            self._indexar_entrada(firma, entrada)

    def _candidatas_semanticas(self, tokens: list, espacios: list) -> list:
        """Firmas candidatas a acierto semántico, sin recorrer toda la caché.

        Garantía de recall: toda entrada que comparta al menos `min_tokens_comunes`
        tokens con la consulta aparece por el índice invertido, exactamente igual
        que si se recorriera la caché entera. El complemento geométrico (celdas W)
        solo AÑADE candidatas, nunca quita.
        """
        min_comunes = max(1, int(self.config["min_tokens_comunes"]))
        contador: dict = {}
        for token in set(tokens):
            for firma in self.indice_tokens.get(token, ()):  # type: ignore[arg-type]
                contador[firma] = contador.get(firma, 0) + 1
        candidatas = {f for f, comunes in contador.items() if comunes >= min_comunes}

        if (self.config["usar_indice_espacios"] and espacios
                and len(self.entradas) > 64):
            clave = tuple(int(x) for x in espacios)
            for celda, firmas in self.indice_espacios.items():
                if len(celda) != len(clave):
                    continue
                coincidencias = sum(1 for a, b in zip(celda, clave) if a == b)
                if coincidencias >= max(2, len(clave) - 1):
                    candidatas.update(firmas)

        # Red de seguridad: si los índices no aportan nada y la caché es pequeña,
        # recorrer todo es más barato que arriesgar un falso fallo.
        if not candidatas and len(self.entradas) <= 256:
            candidatas = set(self.entradas)
            self.fallbacks_indice += 1
        return list(candidatas)

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

    def _firma_de_coords(self, coords: tuple) -> tuple:
        """Firma W 4D de un punto. Única fuente de verdad de la geometría.

        La usan la caché, los espacios y el entrenamiento del predictor, de modo
        que el predictor aprende exactamente en los puntos donde la caché busca.
        """
        if self.familia is not None:
            return tuple(self.familia.calcular_firma_normalizada(coords))
        lado = float(self.config["lado_cubo"])
        return tuple(c / lado for c in coords)

    def _espacios_de_coords(self, coords: tuple) -> tuple:
        """Clasificación de un punto en los espacios W de cada diagonal."""
        if self.familia is None:
            return ()
        return tuple(self.familia.clasificar_en_espacios(coords))

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
        return self._firma_de_coords(self._centroide(tokenizar(texto), texto))

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
        return self._espacios_de_coords(self._centroide(tokenizar(texto), texto))

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
        espacios = list(self.espacios_de(normalizada))
        ahora = time.time()
        ttl = self.config["ttl_segundos"]

        with self.lock:
            self._expulsar_expiradas(ahora, ttl)
            self.consultas_indice += 1

            # 1) coincidencia exacta: índice O(1) en lugar de recorrer la caché.
            firma_exacta = self.indice_norm.get(normalizada)
            entrada_exacta = self.entradas.get(firma_exacta) if firma_exacta else None
            if entrada_exacta is not None:
                self.entradas.move_to_end(firma_exacta)
                self.hits_exactos += 1
                self.tokens_ahorrados += entrada_exacta["tokens"]
                return self._vista_acierto(entrada_exacta, "exacto", 0.0, 1.0,
                                           firma, query)

            # 2) coincidencia semántica: firma W 4D + solapamiento de vocabulario
            #
            # El filtro va ANTES de elegir la candidata y exige un mínimo de
            # evidencia léxica: con un solo token compartido se producían falsos
            # aciertos (medido: «poda de arboles frutales» acertaba contra una
            # entrada sobre octrees con distancia 0.077). En una caché de agente
            # devolver el resultado de otra tarea es peor que un fallo.
            #
            # Las candidatas salen de un índice invertido por token: el resultado
            # es idéntico al de recorrer toda la caché, pero sin coste O(n).
            min_comunes = max(1, int(self.config["min_tokens_comunes"]))
            min_solape = float(self.config["min_solapamiento"])
            conjunto_consulta = set(tokens)
            polaridad_consulta = _polaridad(normalizada)

            mejor_dist = float("inf")
            mejor_solape = 0.0
            mejor_entrada = None
            mejor_comunes = 0
            candidatas = self._candidatas_semanticas(tokens, espacios)
            evaluadas = 0
            for firma_guardada in candidatas:
                entrada = self.entradas.get(firma_guardada)
                if entrada is None:
                    continue
                if entrada.get("expira") and entrada["expira"] < ahora:
                    continue
                # Gate de polaridad: la negación es una palabra vacía para el
                # tokenizador, así que sin este filtro «no optimizar» acertaría
                # contra «optimizar» (medido: distancia 0.0).
                polaridad_entrada = entrada.get("polaridad")
                if polaridad_entrada is None:
                    polaridad_entrada = _polaridad(entrada.get("query_norm", ""))
                if polaridad_entrada != polaridad_consulta:
                    self.descartes_polaridad += 1
                    continue
                tokens_entrada = (entrada.get("tokens_texto")
                                  or tokenizar(entrada.get("query_norm", "")))
                comunes = len(conjunto_consulta & set(tokens_entrada))
                if comunes < min_comunes:
                    continue
                evaluadas += 1
                dist, solape = self.distancia(
                    firma, tokens, firma_guardada, tokens_entrada,
                )
                if solape < min_solape:
                    continue
                if dist < mejor_dist:
                    mejor_dist = dist
                    mejor_solape = solape
                    mejor_comunes = comunes
                    mejor_entrada = entrada

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
                "espacios_w": espacios,
                "umbral": umbral,
                "candidatos": len(self.entradas),
                "candidatas_evaluadas": evaluadas,
                "mejor_distancia": None if mejor_entrada is None else round(mejor_dist, 5),
                "mejor_solapamiento": round(mejor_solape, 4),
                "mejor_tokens_comunes": mejor_comunes,
                "requiere_tokens_comunes": min_comunes,
                "requiere_solapamiento": min_solape,
                "motivo": ("sin evidencia lexica suficiente"
                           if mejor_entrada is None and self.entradas else None),
            }

    def _guardar(self, query: str, valor, tokens: int, metadata: dict | None) -> dict:
        normalizada = self._normalizar(query)
        tokens_texto = tokenizar(normalizada)
        # Centroide calculado UNA vez y compartido por la firma, los espacios y
        # el entrenamiento del predictor. Antes el predictor recibía el hash del
        # texto completo: aprendía en puntos que no eran los de la caché.
        coords = self._centroide(tokens_texto, normalizada)
        firma = self._firma_de_coords(coords)
        espacios = list(self._espacios_de_coords(coords))
        huella = self._clave_huella(tokens_texto, normalizada)
        polaridad = _polaridad(normalizada)
        tokens = max(0, int(tokens or 0))
        ttl = self.config["ttl_segundos"]
        valor_guardado, truncado, longitud_original = self._presupuestar_valor(valor)

        with self.lock:
            # Deduplicación por hash semántico: una consulta equivalente en
            # contenido no debe ocupar dos entradas ni duplicar el entrenamiento.
            firma_previa = self.indice_huellas.get(huella)
            existente = self.entradas.get(firma_previa) if firma_previa else None
            if existente is not None:
                self.deduplicadas += 1
                self.tokens_guardados += max(0, tokens - existente["tokens"])
                existente.update({
                    "query": query,
                    "valor": valor_guardado,
                    "tokens": tokens,
                    "metadata": metadata or {},
                    "timestamp": time.time(),
                    "expira": (time.time() + ttl) if ttl > 0 else None,
                    "truncado": truncado,
                    "longitud_original": longitud_original,
                    "polaridad": polaridad,
                })
                self.entradas.move_to_end(firma_previa)
                return {
                    "stored": True,
                    "deduplicada": True,
                    "query": query,
                    "huella": huella,
                    "firma_w": _redondear(firma),
                    "tokens_texto": tokens_texto,
                    "espacios_w": espacios,
                    "tokens": tokens,
                    "truncado": truncado,
                    "longitud_original": longitud_original,
                    "entradas": len(self.entradas),
                }

            while len(self.entradas) >= self.config["max_entradas"]:
                firma_vieja = next(iter(self.entradas))
                self._desindexar_entrada(firma_vieja)

            self.entradas[firma] = {
                "query": query,
                "query_norm": normalizada,
                "huella": huella,
                "valor": valor_guardado,
                "tokens": tokens,
                "tokens_texto": tokens_texto,
                "metadata": metadata or {},
                "timestamp": time.time(),
                "expira": (time.time() + ttl) if ttl > 0 else None,
                "espacios_w": espacios,
                "firma_w": firma,
                "coords": coords,
                "truncado": truncado,
                "longitud_original": longitud_original,
                "polaridad": polaridad,
            }
            self.entradas.move_to_end(firma)
            self._indexar_entrada(firma, self.entradas[firma])
            self.tokens_guardados += tokens

            # Entrenar el núcleo con las MISMAS coordenadas que la firma.
            self._entrenar_nucleo(coords, normalizada, firma, tokens)

            return {
                "stored": True,
                "deduplicada": False,
                "query": query,
                "huella": huella,
                "firma_w": _redondear(firma),
                "tokens_texto": tokens_texto,
                "espacios_w": espacios,
                "tokens": tokens,
                "truncado": truncado,
                "longitud_original": longitud_original,
                "entradas": len(self.entradas),
            }

    def _presupuestar_valor(self, valor) -> tuple:
        """Aplica el presupuesto de caracteres a lo que se cachea.

        Un acierto debe costar un valor ACOTADO. Guardar el volcado completo de
        una búsqueda de 40 000 tokens convierte la caché en el problema que
        intenta resolver: se guarda un resumen recortado y se marca `truncado`
        para que el agente sepa que debe releer la fuente si necesita el resto.

        Returns:
            (texto_guardado, truncado, longitud_original_en_caracteres)
        """
        if valor is None:
            return "", False, 0
        if isinstance(valor, str):
            texto = valor
        else:
            try:
                texto = json.dumps(valor, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                texto = str(valor)
        limite = self.config["presupuesto_caracteres"]
        if len(texto) <= limite:
            return texto, False, len(texto)
        recorte = len(texto) - limite
        return (texto[:limite] +
                f"\n[... resumen de cache: recortados {recorte} caracteres; "
                f"vuelve a la fuente si necesitas el detalle completo ...]",
                True, len(texto))

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

    # -- memoria de procesos y autoaprendizaje ---------------------------

    def _requiere_memoria(self):
        """Devuelve la memoria SQLite o falla con un motivo legible."""
        if self.memoria is None:
            detalle = f": {self.motivo_memoria}" if self.motivo_memoria else ""
            raise RuntimeError(f"memoria SQLite no disponible{detalle}")
        return self.memoria

    def guardar_proceso(self, params: dict) -> dict:
        """Guarda un proceso resuelto (y una lección opcional) en SQLite.

        Esta es la pieza de autoaprendizaje: el resultado deja de vivir solo en
        la conversación y pasa a ser un recurso reutilizable por cualquier sesión.
        """
        memoria = self._requiere_memoria()
        intencion = str(params.get("intencion") or "").strip()
        resultado = str(params.get("resultado") or "").strip()
        if not intencion:
            raise ValueError("falta el parametro obligatorio 'intencion'")
        if not resultado:
            raise ValueError("falta el parametro obligatorio 'resultado'")

        contexto = params.get("contexto")
        # La huella se deriva SOLO de la intención: el contexto (proyecto,
        # módulo, preset) es metadato y no debe impedir la deduplicación de la
        # misma tarea guardada desde otra sesión.
        tokens_texto = tokenizar(intencion)
        huella = self._clave_huella(tokens_texto, intencion)
        coords = self._centroide(tokenizar(intencion), intencion)
        firma = self._firma_de_coords(coords)
        espacios = list(self._espacios_de_coords(coords))
        tokens = max(0, int(params.get("tokens") or 0))

        guardado = memoria.guardar_proceso(
            intencion=intencion,
            resultado=resultado,
            huella=huella,
            pasos=params.get("pasos"),
            contexto=contexto,
            referencia=params.get("referencia") or None,
            estado=str(params.get("estado") or "candidato"),
            firma_w=firma,
            espacios_w=espacios,
            tokens_texto=tokens_texto,
            tokens=tokens,
            coste_tokens=tokens,
        )

        leccion_guardada = None
        leccion = params.get("leccion")
        if isinstance(leccion, dict) and leccion:
            firma_error = str(
                leccion.get("error_signature") or leccion.get("firma") or ""
            ).strip()
            if not firma_error:
                base = (str(leccion.get("tipo") or "") + " " +
                        str(leccion.get("causa") or "")).strip() or intencion
                firma_error = "ERROR: " + base[:220]
            tokens_leccion = tokenizar(intencion + " " + " ".join(
                str(leccion.get(clave) or "")
                for clave in ("tipo", "causa", "correccion", "prevencion",
                              "modulo", "error_signature")
            ))
            leccion_guardada = memoria.guardar_leccion(
                error_signature=firma_error,
                tipo=str(leccion.get("tipo") or ""),
                causa=str(leccion.get("causa") or ""),
                correccion=str(leccion.get("correccion") or ""),
                prevencion=str(leccion.get("prevencion") or ""),
                modulo=str(leccion.get("modulo") or ""),
                verificado=bool(leccion.get("verificado")),
                tokens_texto=tokens_leccion,
            )

        resumen = (
            f"Proceso {'actualizado' if guardado['actualizado'] else 'guardado'} "
            f"(id {guardado['id']}, estado {params.get('estado') or 'candidato'}): "
            f"{guardado['entradas']} procesos en memoria."
        )
        if guardado.get("truncado"):
            resumen += (f" El resultado se recorto al presupuesto de "
                        f"{self.config['presupuesto_caracteres']} caracteres.")
        if leccion_guardada:
            resumen += f" Leccion registrada (id {leccion_guardada['id']})."
        return {
            "guardado": True,
            "id": guardado["id"],
            "huella": huella,
            "actualizado": guardado["actualizado"],
            "entradas": guardado["entradas"],
            "truncado": guardado.get("truncado", False),
            "redacciones": guardado.get("redacciones", 0),
            "leccion": leccion_guardada,
            "resumen": resumen,
        }

    def buscar_proceso(self, params: dict) -> dict:
        """Recupera procesos ya resueltos y lecciones equivalentes.

        Primero prefiltra por tokens en SQLite y luego puntúa con la MISMA
        geometría W 4D de la caché, de modo que «cómo migrar una tabla» puede
        recuperar un proceso descrito como «migración de esquema MySQL».
        """
        memoria = self._requiere_memoria()
        query = str(params.get("query") or "").strip()
        if not query:
            raise ValueError("falta el parametro obligatorio 'query'")
        limite = min(10, max(1, int(params.get("limite") or 5)))
        tokens = tokenizar(query)
        firma = self.firma_de(query)
        umbral = float(self.config["umbral_procesos"])
        min_comunes = max(1, int(self.config["min_tokens_procesos"]))
        polaridad_consulta = _polaridad(query)

        candidatos = memoria.candidatos_procesos(
            tokens, limite=200, min_comunes=min_comunes
        )
        puntuados = []
        for candidato in candidatos:
            # Mismo gate que en la caché: «no migrar» y «migrar» no son la misma
            # tarea aunque compartan todos los tokens significativos.
            if _polaridad(candidato.get("intencion", "")) != polaridad_consulta:
                continue
            firma_candidato = candidato.get("firma_w") or []
            if len(firma_candidato) != 4:
                continue
            tokens_candidato = tokenizar(candidato.get("intencion", ""))
            dist, solape = self.distancia(
                firma, tokens, tuple(firma_candidato), tokens_candidato
            )
            if dist > umbral:
                continue
            confianza = max(0.0, min(1.0, 1.0 - (dist / umbral)))
            # Un proceso validado y con uso previo se prefiere a uno candidato
            # con la misma distancia: la validación es evidencia, no adorno. La
            # evidencia léxica pesa además en la prioridad (el umbral se aplica
            # a la distancia W, no a la prioridad).
            prioridad = (dist
                         - 0.35 * solape
                         - (0.03 if candidato.get("estado") == "validado" else 0.0)
                         - min(0.03, 0.01 * int(candidato.get("exitos") or 0)))
            puntuados.append((
                prioridad,
                {
                    "id": candidato["id"],
                    "huella": candidato.get("huella"),
                    "intencion": candidato["intencion"],
                    "pasos": candidato.get("pasos") or [],
                    "resultado": candidato.get("resultado") or "",
                    "referencia": candidato.get("referencia"),
                    "contexto": candidato.get("contexto") or {},
                    "estado": candidato.get("estado"),
                    "exitos": candidato.get("exitos", 0),
                    "fallos": candidato.get("fallos", 0),
                    "distancia_w": round(dist, 5),
                    "solapamiento": round(solape, 4),
                    "confianza": round(confianza, 4),
                    "tokens_ahorrados": int(candidato.get("coste_tokens") or 0),
                    "actualizado_en": candidato.get("actualizado_en"),
                },
            ))

        puntuados.sort(key=lambda par: par[0])
        procesos = [item for _, item in puntuados[:limite]]
        tokens_ahorrados = sum(p["tokens_ahorrados"] for p in procesos)

        # Lecciones relacionadas: no se indexan por geometría (el error no
        # siempre comparte el vocabulario de la tarea), sino por solapamiento.
        lecciones = []
        candidatas_leccion = memoria.candidatos_lecciones(tokens, limite=30,
                                                          min_comunes=1)
        conjunto_consulta = set(tokens)
        for leccion in candidatas_leccion:
            texto = " ".join(str(leccion.get(campo) or "") for campo in
                             ("error_signature", "tipo", "causa", "correccion",
                              "prevencion", "modulo"))
            # Los tokens indexados incluyen la intención original de la tarea,
            # así que una lección se recupera buscando la tarea, no el error.
            tokens_leccion = set(leccion.get("tokens_texto") or tokenizar(texto))
            if not tokens_leccion:
                continue
            interseccion = len(conjunto_consulta & tokens_leccion)
            union = len(conjunto_consulta | tokens_leccion)
            solape = interseccion / union if union else 0.0
            if interseccion < 1 or solape < 0.08:
                continue
            lecciones.append({
                "id": leccion["id"],
                "error_signature": leccion["error_signature"],
                "tipo": leccion.get("tipo"),
                "causa": leccion.get("causa"),
                "correccion": leccion.get("correccion"),
                "prevencion": leccion.get("prevencion"),
                "modulo": leccion.get("modulo"),
                "verificado": bool(leccion.get("verificado")),
                "solapamiento": round(solape, 4),
            })
        lecciones.sort(key=lambda item: item["solapamiento"], reverse=True)
        lecciones = lecciones[:5]

        hit = bool(procesos)
        if hit:
            memoria.registrar_evento("proceso_hit", query,
                                     procesos[0].get("huella", ""),
                                     tokens_ahorrados,
                                     f"id={procesos[0]['id']}")
        else:
            memoria.registrar_evento("proceso_miss", query)

        if procesos:
            resumen = (f"HIT — {len(procesos)} proceso(s) ya resueltos para "
                       f"«{query}» (~{tokens_ahorrados} tokens evitados).")
        else:
            resumen = (f"MISS — no hay procesos equivalentes en la memoria SQLite "
                       f"(umbral {umbral}). Ejecuta la tarea y guárdala con "
                       f"vector_proceso_guardar.")
        if lecciones:
            resumen += f" {len(lecciones)} lección(es) relacionada(s)."
        return {
            "hit": hit,
            "procesos": procesos,
            "lecciones": lecciones,
            "candidatos": len(candidatos),
            "umbral": umbral,
            "tokens_ahorrados": tokens_ahorrados,
            "presupuesto_caracteres": self.config["presupuesto_caracteres"],
            "resumen": resumen,
        }

    def buscar_recurso(self, params: dict) -> dict:
        """Encuentra la skill, agente, documento o herramienta que resuelve la tarea."""
        memoria = self._requiere_memoria()
        query = str(params.get("query") or "").strip()
        if not query:
            raise ValueError("falta el parametro obligatorio 'query'")
        limite = min(10, max(1, int(params.get("limite") or 5)))
        tipo = str(params.get("tipo") or "todos")
        if tipo not in ("todos", "skill", "agente", "documento", "herramienta"):
            tipo = "todos"

        tokens = tokenizar(query)
        firma = self.firma_de(query)
        umbral = float(self.config["umbral_recursos"])
        candidatos = memoria.candidatos_recursos(
            tokens, tipo=None if tipo == "todos" else tipo, limite=200,
            min_comunes=1,
        )

        # Relevancia léxica ponderada por IDF del catálogo. La geometría W sola
        # no ordena bien recursos de texto largo (todas las skills comparten
        # «php», «mysql», «aplicación»): esos términos valen poco y los
        # distintivos («arquitectura», «seguridad») valen mucho. Es el mismo
        # aprendizaje que en la caché, aplicado al enrutado de agentes.
        conjuntos = []
        for candidato in candidatos:
            texto = " ".join([
                str(candidato.get("nombre") or ""),
                str(candidato.get("descripcion") or ""),
                str(candidato.get("extracto") or ""),
            ])
            conjuntos.append((candidato, set(tokenizar(texto))))
        total_documentos = max(1, len(conjuntos))
        frecuencia: dict = {}
        for _, conjunto in conjuntos:
            for token in conjunto:
                frecuencia[token] = frecuencia.get(token, 0) + 1

        def peso(token: str) -> float:
            return math.log(1.0 + total_documentos / (1.0 + frecuencia.get(token, 0)))

        denominador = sum(peso(token) for token in set(tokens)) or 1.0

        puntuados = []
        for candidato, tokens_candidato in conjuntos:
            texto = " ".join([
                str(candidato.get("nombre") or ""),
                str(candidato.get("descripcion") or ""),
                str(candidato.get("extracto") or ""),
            ])
            firma_candidato = candidato.get("firma_w") or []
            if len(firma_candidato) == 4:
                dist, solape = self.distancia(
                    firma, tokens, tuple(firma_candidato), tokenizar(texto)
                )
            else:
                dist, solape = 1.0, 0.0
            comunes = set(tokens) & tokens_candidato
            relevancia = sum(peso(token) for token in comunes) / denominador
            geometrica_conf = max(0.0, min(1.0, 1.0 - (dist / max(umbral, 0.05))))
            confianza = max(geometrica_conf, relevancia)
            baja_confianza = (relevancia < 0.18) and (dist > umbral)
            puntuados.append((-relevancia, dist, {
                "nombre": candidato["nombre"],
                "tipo": candidato["tipo"],
                "ruta": candidato.get("ruta") or "",
                "descripcion": candidato.get("descripcion") or "",
                "extracto": candidato.get("extracto") or "",
                "distancia_w": round(dist, 5),
                "solapamiento": round(solape, 4),
                "relevancia": round(relevancia, 4),
                "confianza": round(confianza, 4),
                "baja_confianza": baja_confianza,
            }))

        puntuados.sort(key=lambda par: (par[0], par[1]))
        recursos = [recurso for _, _, recurso in puntuados[:limite]]
        hit = bool(recursos) and not recursos[0]["baja_confianza"]
        if hit:
            memoria.registrar_evento("recurso_hit", query, "", 0,
                                     f"{recursos[0]['tipo']}:{recursos[0]['nombre']}")
        else:
            memoria.registrar_evento("recurso_hit", query, "", 0, "sin_acierto")
        resumen = (
            f"HIT — recurso mas relevante: «{recursos[0]['nombre']}» "
            f"({recursos[0]['tipo']}, confianza {recursos[0]['confianza']})."
            if hit else
            f"MISS — ningun recurso supera el umbral {umbral}; "
            f"candidatos mas cercanos: " +
            (", ".join(r["nombre"] for r in recursos[:3]) or "ninguno") + "."
        )
        return {
            "hit": hit,
            "recursos": recursos,
            "candidatos": len(candidatos),
            "umbral": umbral,
            "resumen": resumen,
        }

    def catalogo_reindexar(self) -> dict:
        """Reindexa las skills/documentos configurados (idempotente)."""
        self._requiere_memoria()
        self._indexar_catalogo()
        return {"catalogo": dict(self.catalogo), "memoria": self.ruta_memoria}

    # -- núcleo / métricas ------------------------------------------------

    def _normalizar(self, texto: str) -> str:
        return " ".join((texto or "").lower().split())

    def _vista_acierto(self, entrada: dict, tipo: str, dist: float, solape: float,
                       firma_nueva: tuple, consultada: str) -> dict:
        # Presupuesto de respuesta: un acierto no puede volcar 40 000 tokens al
        # contexto. Se recorta el valor a `max_tokens_respuesta` (≈4 car./token) y
        # se declara el recorte para que el agente decida si relee la fuente.
        valor = entrada.get("valor")
        texto_valor = valor if isinstance(valor, str) else json.dumps(
            valor, ensure_ascii=False, default=str)
        limite = self.config["max_tokens_respuesta"] * 4
        entregado_truncado = len(texto_valor) > limite
        if entregado_truncado:
            recorte = len(texto_valor) - limite
            texto_valor = (texto_valor[:limite] +
                           f"\n[... respuesta recortada: {recorte} caracteres; "
                           f"el valor completo está en la caché ...]")
        return {
            "hit": True,
            "kind": tipo,
            "query": entrada["query"],
            "query_consultada": consultada,
            "value": texto_valor,
            "tokens_ahorrados": entrada["tokens"],
            "tokens_entregados": max(1, len(texto_valor) // 4),
            "truncado": bool(entrada.get("truncado")) or entregado_truncado,
            "longitud_original": entrada.get("longitud_original"),
            "distancia_w": round(float(dist), 5),
            "solapamiento": round(float(solape), 4),
            "umbral": self.config["umbral_similitud"],
            "firma_w": _redondear(firma_nueva),
            "firma_cache": _redondear(entrada["firma_w"]),
            "huella": entrada.get("huella"),
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
            self._desindexar_entrada(f)

    def _entrenar_nucleo(self, coords: tuple, texto: str, firma: tuple,
                         tokens: int) -> None:
        """Registra la entrada en el núcleo, con las mismas coordenadas que la firma.

        Cada paso va en su propio `try`: si el predictor falla, la entrada debe
        quedar igualmente registrada en el octree y en los episodios, de modo
        que `vector_stats` refleje lo que la caché contiene de verdad. Antes se
        recalculaba el punto con el hash del texto completo, así que el
        predictor aprendía en una geometría distinta de la de la caché.
        """
        if self.vos is None:
            return

        # Clave única por entrada (ver `_secuencia`).
        self._secuencia += 1
        secuencia = self._secuencia

        with _stdout_silenciado():
            try:
                # SOLO el predictor: `PredictorAccesosAdaptativo.registrar_acceso`
                # ya llama internamente a `familia.registrar_acceso` (y también
                # al analizador de patrones, Markov y Kalman). Registrarlo
                # además aquí duplicaba los histogramas y sesgaba la entropía y
                # la predecibilidad.
                self.vos.predictor.registrar_acceso(coords)
            except Exception:  # pragma: no cover
                pass
            try:
                # Octree del núcleo: alimenta datos_en_octree / profundidad.
                self.vos.raiz.insertar(
                    f"VW_{secuencia}",
                    {"coords": coords, "valor": tokens, "timestamp": time.time()},
                    coords,
                )
            except Exception:  # pragma: no cover
                pass
            try:
                ep_id = f"EP_{secuencia}"
                self.vos.episodios[ep_id] = {
                    "id": ep_id,
                    "query": texto,
                    "coords": coords,
                    "firma_w": firma,
                    "espacios_w": self._espacios_de_coords(coords),
                    "tokens": tokens,
                    "timestamp": time.time(),
                }
                self.vos.indice_firmas[firma] = ep_id
            except Exception:  # pragma: no cover
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
            memoria = {"disponible": False, "motivo": self.motivo_memoria}
            if self.memoria is not None:
                try:
                    memoria = {"disponible": True, **self.memoria.estadisticas()}
                except Exception as exc:  # pragma: no cover - base bloqueada
                    memoria = {"disponible": False,
                               "motivo": f"{type(exc).__name__}: {exc}"}
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
                    "deduplicadas": self.deduplicadas,
                    "descartes_polaridad": self.descartes_polaridad,
                    "presupuesto_caracteres": self.config["presupuesto_caracteres"],
                    "max_tokens_respuesta": self.config["max_tokens_respuesta"],
                },
                "indices": {
                    "tokens": len(self.indice_tokens),
                    "celdas_w": len(self.indice_espacios),
                    "consultas": self.consultas_indice,
                    "fallbacks": self.fallbacks_indice,
                    "usar_indice_espacios": self.config["usar_indice_espacios"],
                },
                "memoria_sqlite": memoria,
                "catalogo": dict(self.catalogo),
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
            # El puente NO usa `CompresorHibrido` del núcleo: comprime
            # coordenadas, no texto. Declararlo como disponible era engañoso.
            "compresion_hibrida": False,
            "invariante_permutaciones": self.config["invariante_permutaciones"],
            "espacios_por_diagonal": self.config["n_espacios"],
            "diagonales": 4 if self.vos is not None else 0,
            "min_tokens_comunes": self.config["min_tokens_comunes"],
            "min_solapamiento": self.config["min_solapamiento"],
            # Memoria persistente y autoaprendizaje.
            "memoria_sqlite": self.memoria is not None,
            "memoria_procesos": self.memoria is not None,
            "lecciones": self.memoria is not None,
            "catalogo_recursos": self.memoria is not None,
            "presupuesto_tokens": True,
            "indice_invertido": True,
            "indice_espacios": self.config["usar_indice_espacios"],
            "dedupe_semantico": True,
        }
        return capacidades

    def purgar(self) -> dict:
        """Vacía la caché Y el estado acumulado del núcleo.

        Antes solo se limpiaba el diccionario del puente: los episodios, el
        octree, `indice_firmas` y `cache_firmas` del núcleo seguían creciendo, y
        `status` seguía reportando datos ya purgados.
        """
        with self.lock:
            cantidad = len(self.entradas)
            self.entradas.clear()
            self._reconstruir_indices()
            self.historial_similitud.clear()
            self.hits_exactos = self.hits_semanticos = self.fallos = 0
            self.tokens_ahorrados = self.tokens_guardados = 0
            self.deduplicadas = 0
            self.consultas_indice = 0
            self.fallbacks_indice = 0
            self.descartes_polaridad = 0
            if self.vos is not None:
                try:
                    with _stdout_silenciado():
                        self.vos.episodios.clear()
                        self.vos.indice_firmas.clear()
                        self.vos.cache.clear()
                        self.vos.familia.cache_firmas.clear()
                        modulo = type(self.vos).__module__
                        Nodo = getattr(sys.modules.get(modulo), "NodoOctreeMemoriaEficiente", None)
                        if Nodo is not None:
                            lado = self.config["lado_cubo"]
                            self.vos.raiz = Nodo(
                                centro=(lado / 2.0, lado / 2.0, lado / 2.0),
                                tamano=float(lado),
                            )
                except Exception:  # pragma: no cover - la purga es best-effort
                    pass
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
                        "huella": e.get("huella") or self._clave_huella(
                            e.get("tokens_texto") or [], e["query_norm"]),
                        "valor": e["valor"],
                        "tokens": e["tokens"],
                        "tokens_texto": e.get("tokens_texto", []),
                        "metadata": e["metadata"],
                        "timestamp": e["timestamp"],
                        "expira": e["expira"],
                        "espacios_w": e["espacios_w"],
                        "coords": list(e.get("coords") or ()),
                        "truncado": bool(e.get("truncado")),
                        "longitud_original": e.get("longitud_original"),
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
            # Escritura atómica: un fallo a mitad no deja el estado truncado.
            carpeta = os.path.dirname(os.path.abspath(path))
            if carpeta:
                os.makedirs(carpeta, exist_ok=True)
            temporal = f"{path}.tmp"
            with open(temporal, "w", encoding="utf-8") as fh:
                json.dump(datos, fh, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporal, path)
            return {"path": os.path.abspath(path), "entradas": len(self.entradas)}

    def restaurar(self, path: str) -> dict:
        if not os.path.isfile(path):
            return {"restaurado": False, "motivo": f"no existe: {path}"}
        with open(path, "r", encoding="utf-8") as fh:
            datos = json.load(fh)

        with self.lock:
            restauradas = 0
            descartadas = 0
            # Se respeta el límite de la caché y se descartan las caducadas: antes
            # se restauraba todo y el límite solo se aplicaba en el siguiente
            # guardado.
            ahora = time.time()
            maximo = self.config["max_entradas"]
            for item in datos.get("entradas", []):
                if restauradas >= maximo:
                    descartadas += 1
                    continue
                expira = item.get("expira")
                if expira and expira < ahora:
                    descartadas += 1
                    continue
                # Las coordenadas mandan: si el estado se guardó con otra
                # geometría, la firma se recalcula desde ellas.
                coords = item.get("coords")
                if not coords:
                    query_norm = item["query_norm"]
                    coords = self._centroide(tokenizar(query_norm), query_norm)
                firma = self._firma_de_coords(tuple(coords))
                if firma in self.entradas:
                    descartadas += 1
                    continue
                tokens_texto = item.get("tokens_texto") or tokenizar(item["query_norm"])
                self.entradas[firma] = {
                    "query": item["query"],
                    "query_norm": item["query_norm"],
                    "huella": item.get("huella") or self._clave_huella(
                        tokens_texto, item["query_norm"]),
                    "valor": item["valor"],
                    "tokens": item["tokens"],
                    "tokens_texto": tokens_texto,
                    "metadata": item.get("metadata", {}),
                    "timestamp": item["timestamp"],
                    "expira": expira,
                    "espacios_w": list(self._espacios_de_coords(tuple(coords))),
                    "firma_w": firma,
                    "coords": tuple(coords),
                    "truncado": bool(item.get("truncado")),
                    "longitud_original": item.get("longitud_original"),
                    "polaridad": _polaridad(item["query_norm"]),
                }
                restauradas += 1
            metricas = datos.get("metricas", {})
            self.hits_exactos = metricas.get("hits_exactos", 0)
            self.hits_semanticos = metricas.get("hits_semanticos", 0)
            self.fallos = metricas.get("fallos", 0)
            self.tokens_ahorrados = metricas.get("tokens_ahorrados", 0)
            self.tokens_guardados = metricas.get("tokens_guardados", 0)
            # Warm-start REAL: antes la persistencia solo restauraba métricas y
            # el predictor arrancaba vacío. Ahora se reinyectan las coordenadas
            # en el predictor, el octree y los episodios del núcleo, de modo que
            # `vector_predict` funciona tras reiniciar sin esperar a nuevos usos.
            reentrenadas = 0
            if self.config["reentrenar_al_restaurar"] and self.vos is not None:
                for firma, entrada in list(self.entradas.items()):
                    self._entrenar_nucleo(entrada["coords"], entrada["query_norm"],
                                          firma, entrada["tokens"])
                    reentrenadas += 1
            self._reconstruir_indices()
            aviso = None
            lado_guardado = (datos.get("config") or {}).get("lado_cubo")
            if lado_guardado is not None and lado_guardado != self.config["lado_cubo"]:
                aviso = (f"el estado se guardo con lado_cubo={lado_guardado} y el "
                         f"actual es {self.config['lado_cubo']}; firmas recalculadas")
            return {"restaurado": True, "path": os.path.abspath(path),
                    "entradas": restauradas, "descartadas": descartadas,
                    "reentrenadas": reentrenadas, "aviso": aviso}


def _leer_skill_md(archivo: str) -> tuple:
    """Lee un `SKILL.md` y devuelve (metadatos del frontmatter, cuerpo).

    No es un parser YAML: extrae solo las tres claves que el catálogo necesita
    (`name`, `description`, `whenToUse`) del bloque `---` inicial. Un
    frontmatter complejo se ignora en silencio; el índice es una ayuda de
    enrutado, no la fuente de verdad de la skill.
    """
    with open(archivo, "r", encoding="utf-8", errors="replace") as fh:
        texto = fh.read()
    metadatos = {}
    cuerpo = texto
    if texto.lstrip().startswith("---"):
        inicio = texto.find("---") + 3
        fin = texto.find("\n---", inicio)
        if fin != -1:
            cabecera = texto[inicio:fin]
            cuerpo = texto[fin + 4:]
            for linea in cabecera.splitlines():
                if not linea.strip() or linea.startswith((" ", "\t")) or ":" not in linea:
                    continue
                clave, valor = linea.split(":", 1)
                clave = clave.strip()
                if clave in ("name", "description", "whenToUse"):
                    metadatos[clave] = valor.strip().strip("\"'")
    return metadatos, cuerpo


def _extracto_legible(cuerpo: str, limite: int = 420) -> str:
    """Primer texto útil del cuerpo, sin marcas Markdown ni la línea de título."""
    lineas = []
    for linea in (cuerpo or "").splitlines():
        limpia = linea.strip().lstrip("#").strip()
        if not limpia:
            continue
        lineas.append(limpia)
        if sum(len(x) for x in lineas) >= limite:
            break
    texto = " ".join(lineas)
    return texto[:limite]


def _primera_frase(cuerpo: str, limite: int = 300) -> str:
    """Primera frase del documento, para usarla como descripción del recurso."""
    for linea in (cuerpo or "").splitlines():
        limpia = linea.strip().lstrip("#").strip()
        if len(limpia) < 20:
            continue
        corte = limpia.find(". ")
        frase = limpia if corte == -1 else limpia[:corte + 1]
        return frase[:limite]
    return ""


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


def _asegurar_estado(es_init: bool, params: dict) -> EstadoVOS:
    """Crea el estado en el primer uso, o lo reconfigura SOLO con `init`.

    Antes se reconfiguraba con cualquier petición que trajera `config`, lo que
    recreaba el núcleo y perdía el aprendizaje conservando entradas con firmas
    de la geometría anterior.
    """
    global _ESTADO
    config = params.get("config") or {}
    if _ESTADO is None:
        _ESTADO = EstadoVOS(config)
    elif es_init and config and _ESTADO.config != EstadoVOS._normalizar_config(config):
        # `init` con una configuración distinta reconstruye el núcleo.
        entradas = _ESTADO.entradas
        t_inicio = _ESTADO.t_inicio
        nuevo = EstadoVOS(config)
        nuevo.t_inicio = t_inicio
        nuevo.entradas = entradas
        _ESTADO = nuevo
    return _ESTADO


def _exigir_texto(params: dict, clave: str) -> None:
    """Valida que un parámetro sea texto, con un error legible."""
    valor = params.get(clave)
    if valor is None:
        raise ValueError(f"falta el parametro obligatorio '{clave}'")
    if not isinstance(valor, str):
        raise ValueError(f"'{clave}' debe ser texto, no {type(valor).__name__}")


def _manejar(peticion: dict) -> dict:
    metodo = peticion.get("method")
    if not isinstance(metodo, str):
        raise ValueError("'method' debe ser texto")
    params = peticion.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("'params' debe ser un objeto")
    estado = _asegurar_estado(peticion.get("method") == "init", params)

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
            "memoria": {
                "disponible": estado.memoria is not None,
                "ruta": estado.ruta_memoria,
                "motivo": estado.motivo_memoria,
                "capacidades": {
                    "procesos": estado.memoria is not None,
                    "lecciones": estado.memoria is not None,
                    "recursos": estado.memoria is not None,
                },
            },
            "catalogo_indexado": dict(estado.catalogo),
        }
    if metodo == "status":
        return estado.metricas()

    # `query` debe ser texto: un número hacía fallar `_normalizar` con
    # AttributeError y el plugin solo veía un error opaco.
    if metodo in ("firma", "cache_check", "cache_store",
                  "proceso_buscar", "recurso_buscar"):
        _exigir_texto(params, "query")
    if metodo == "proceso_guardar":
        _exigir_texto(params, "intencion")
        _exigir_texto(params, "resultado")
    if metodo == "firma":
        return {
            "firma_w": _redondear(estado.firma_de(params["query"])),
            "espacios_w": list(estado.espacios_de(params["query"])),
        }
    if metodo == "cache_check":
        return estado._buscar(params["query"])
    if metodo == "cache_store":
        return estado.guardar_valor(
            params["query"],
            params.get("value"),
            params.get("tokens", 0),
            params.get("metadata"),
        )
    if metodo == "proceso_guardar":
        return estado.guardar_proceso(params)
    if metodo == "proceso_buscar":
        return estado.buscar_proceso(params)
    if metodo == "recurso_buscar":
        return estado.buscar_recurso(params)
    if metodo == "catalogo_reindexar":
        return estado.catalogo_reindexar()
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

        # Una línea JSON válida que no sea un objeto (`[1,2]`, `null`, `"x"`)
        # no tiene `.get` y mataba el proceso con AttributeError. El plugin lo
        # veía como «el puente terminó» y perdía el estado.
        if not isinstance(peticion, dict):
            _emitir({"id": None, "ok": False,
                     "error": "el mensaje debe ser un objeto JSON"})
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
