#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memoria_vectorw.py - Memoria de procesos y aprendizaje en SQLite para VectorW.

Autor del núcleo VectorW: Jose Ricardo Mantilla Mantilla (PePiuoX)
https://github.com/PePiuoX - Licencia LAMC v1.0 / LULA v1.1

Este módulo NO reimplementa VectorW. Es la capa de persistencia que el puente
(`bridge_vos.py`) usa para que el agente deje de repetir trabajo:

    procesos   → tareas resueltas con sus pasos y su resultado, reutilizables.
    lecciones  → errores resueltos con causa raíz, corrección y prevención.
    recursos   → catálogo indexado de skills/agentes/documentos/herramientas.
    eventos    → bitácora de aciertos y fallos para medir el ahorro real.

Diseño:

  * SQLite con WAL y `busy_timeout`, de modo que varias sesiones de DSH
    (perfil global + presets) pueden compartir la MISMA base sin bloquearse.
  * Los candidatos se prefiltran en SQL por índice de tokens (tabla
    `*_tokens`), y la puntuación semántica fina la hace el puente, que es quien
    conoce la geometría W 4D. La base no importa el núcleo.
  * Todas las sentencias usan parámetros enlazados; jamás se concatena SQL.
  * Todo texto se redacta antes de escribirse (`_redactar`), de modo que una
    clave API, un token o una contraseña no acaben en un recurso reutilizable.
  * Sin dependencias externas: solo `sqlite3` de la biblioteca estándar.

Contrato de deduplicación: `huella` es una cadena estable (el puente la deriva
de los tokens normalizados y ordenados del texto). `UNIQUE(huella)` hace que
guardar dos veces la misma tarea actualice la entrada en lugar de duplicarla.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone

VERSION_ESQUEMA = "1"
NOMBRE_BASE = "vectorw_memoria.db"

ESTADOS_PROCESO = ("candidato", "validado", "obsoleto", "rechazado")
TIPOS_RECURSO = ("skill", "agente", "documento", "herramienta")
TIPOS_EVENTO = (
    "cache_hit",
    "cache_miss",
    "cache_store",
    "proceso_hit",
    "proceso_miss",
    "proceso_guardar",
    "leccion_hit",
    "recurso_hit",
)

# ---------------------------------------------------------------------------
# Redacción de secretos
# ---------------------------------------------------------------------------

# Solo patrones inequívocos: se prefiere redactar de más a filtrar de menos,
# pero sin destruir texto técnico normal (rutas, hashes, firmas).
_PATRONES_SECRETO = [
    # asignaciones tipo `api_key = "..."`, `password: ...`, `token=...`
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|"
        r"passwd|contrase[nñ]a|client[_-]?secret|private[_-]?key|bearer)\b"
        r"\s*[:=]\s*([^\s,;\"']{6,}|\"[^\"]{6,}\"|'[^']{6,}')"
    ),
    # cabecera Authorization: Bearer xxxxx
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._\-+/=]{8,}"),
    # claves con prefijo conocido
    re.compile(r"\b(sk|pk|rk|ghp|gho|github_pat|xoxb|xoxp|AKIA)[_-]?[A-Za-z0-9]{16,}\b"),
    # cadenas PEM
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]

_MARCA_REDACTADO = "[REDACTADO]"


def _redactar(texto: str, maximo: int | None = None) -> tuple[str, int]:
    """Elimina secretos evidentes. Devuelve (texto, nº de redacciones).

    Args:
        texto: contenido a sanear.
        maximo: si se indica, recorta el resultado a esa cantidad de caracteres
            añadiendo una marca que indica cuánto se recortó.

    Returns:
        Tupla con el texto saneado y el número de coincidencias redactadas.
    """
    if not texto:
        return "", 0
    total = 0
    saneado = texto
    for patron in _PATRONES_SECRETO:
        saneado, n = patron.subn(_MARCA_REDACTADO, saneado)
        total += n
    if maximo is not None and maximo > 0 and len(saneado) > maximo:
        recortado = len(saneado) - maximo
        saneado = saneado[:maximo] + f"\n[... recortado: {recortado} caracteres ...]"
    return saneado, total


def ahora_iso() -> str:
    """Timestamp ISO-8601 UTC con milisegundos (formato del contrato SQLite)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _json(valor) -> str | None:
    """Serializa un valor a JSON, o None si es None."""
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, default=str)


def _deserializar(texto, defecto=None):
    """Deserializa un campo JSON guardado como texto."""
    if texto is None or texto == "":
        return defecto
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return texto


def _hash_contenido(texto: str) -> str:
    """Hash estable del contenido indexado (solo para detectar cambios)."""
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()


class MemoriaVectorW:
    """Base SQLite de procesos, lecciones, recursos y eventos.

    Es segura entre hilos: una única conexión protegida por un `RLock`, que es
    todo lo que necesita el puente (un proceso, peticiones serializadas por el
    protocolo). Entre procesos distintos la seguridad la da SQLite (WAL +
    `busy_timeout`).
    """

    def __init__(self, ruta: str, presupuesto_caracteres: int = 6000,
                 max_procesos: int = 5000, max_eventos: int = 5000):
        self.ruta = os.path.abspath(ruta)
        self.presupuesto = max(500, int(presupuesto_caracteres or 6000))
        self.max_procesos = max(100, int(max_procesos or 5000))
        self.max_eventos = max(100, int(max_eventos or 5000))
        self._lock = threading.RLock()
        self.ultimo_error: str | None = None

        carpeta = os.path.dirname(self.ruta)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        self.con = sqlite3.connect(
            self.ruta, timeout=8.0, check_same_thread=False,
            isolation_level=None,  # autocommit: nosotros gestionamos transacciones
        )
        self.con.row_factory = sqlite3.Row
        self._configurar_conexion()
        self._migrar()

    # -- infraestructura ---------------------------------------------------

    def _configurar_conexion(self) -> None:
        """WAL + busy_timeout: permite que varias sesiones compartan la base."""
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA busy_timeout=8000",
            # El WAL por defecto son 1000 páginas (~4 MB). La memoria recibe
            # escrituras pequeñas y frecuentes; se acota a ~1 MB para que el
            # fichero no crezca sin control entre checkpoints.
            "PRAGMA wal_autocheckpoint=256",
        ):
            try:
                self.con.execute(pragma)
            except sqlite3.DatabaseError:  # pragma: no cover - entorno exótico
                pass

    def _transaccion(self, trabajo):
        """Ejecuta `trabajo` dentro de BEGIN IMMEDIATE / COMMIT."""
        with self._lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                resultado = trabajo()
                self.con.execute("COMMIT")
                return resultado
            except Exception:
                try:
                    self.con.execute("ROLLBACK")
                except sqlite3.DatabaseError:
                    pass
                raise

    # -- esquema -----------------------------------------------------------

    def _migrar(self) -> None:
        """Crea el esquema versionado. Idempotente."""
        with self._lock:
            self.con.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY,"
                " applied_at TEXT NOT NULL)"
            )
            version = self.con.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if version is not None and version["version"] == VERSION_ESQUEMA:
                return

            self.con.executescript(
                """
                CREATE TABLE IF NOT EXISTS procesos (
                  id               INTEGER PRIMARY KEY AUTOINCREMENT,
                  huella           TEXT NOT NULL UNIQUE,
                  intencion        TEXT NOT NULL,
                  contexto         TEXT,
                  pasos            TEXT,
                  resultado        TEXT NOT NULL,
                  referencia       TEXT,
                  estado           TEXT NOT NULL DEFAULT 'candidato'
                                   CHECK (estado IN ('candidato','validado','obsoleto','rechazado')),
                  firma_w          TEXT,
                  espacios_w       TEXT,
                  exitos           INTEGER NOT NULL DEFAULT 0,
                  fallos           INTEGER NOT NULL DEFAULT 0,
                  tokens_ahorrados INTEGER NOT NULL DEFAULT 0,
                  coste_tokens     INTEGER NOT NULL DEFAULT 0,
                  creado_en        TEXT NOT NULL,
                  actualizado_en   TEXT NOT NULL,
                  ultimo_uso       TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_procesos_actualizado
                  ON procesos (actualizado_en DESC);
                CREATE INDEX IF NOT EXISTS idx_procesos_estado ON procesos (estado);

                CREATE TABLE IF NOT EXISTS proceso_tokens (
                  proceso_id INTEGER NOT NULL,
                  token      TEXT NOT NULL,
                  PRIMARY KEY (proceso_id, token),
                  FOREIGN KEY (proceso_id) REFERENCES procesos (id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_proceso_tokens_token ON proceso_tokens (token);

                CREATE TABLE IF NOT EXISTS lecciones (
                  id              INTEGER PRIMARY KEY AUTOINCREMENT,
                  error_signature TEXT NOT NULL UNIQUE,
                  tipo            TEXT,
                  causa           TEXT,
                  correccion      TEXT,
                  prevencion      TEXT,
                  modulo          TEXT,
                  tokens_texto    TEXT,
                  verificado      INTEGER NOT NULL DEFAULT 0,
                  creado_en       TEXT NOT NULL,
                  actualizado_en  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_lecciones_actualizado
                  ON lecciones (actualizado_en DESC);

                CREATE TABLE IF NOT EXISTS leccion_tokens (
                  leccion_id INTEGER NOT NULL,
                  token      TEXT NOT NULL,
                  PRIMARY KEY (leccion_id, token),
                  FOREIGN KEY (leccion_id) REFERENCES lecciones (id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_leccion_tokens_token ON leccion_tokens (token);

                CREATE TABLE IF NOT EXISTS recursos (
                  id              INTEGER PRIMARY KEY AUTOINCREMENT,
                  clave           TEXT NOT NULL UNIQUE,
                  tipo            TEXT NOT NULL
                                  CHECK (tipo IN ('skill','agente','documento','herramienta')),
                  nombre          TEXT NOT NULL,
                  ruta            TEXT,
                  descripcion     TEXT,
                  extracto        TEXT,
                  contenido_hash  TEXT,
                  firma_w         TEXT,
                  espacios_w      TEXT,
                  tokens          INTEGER NOT NULL DEFAULT 0,
                  actualizado_en  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recursos_tipo ON recursos (tipo);

                CREATE TABLE IF NOT EXISTS recurso_tokens (
                  recurso_id INTEGER NOT NULL,
                  token      TEXT NOT NULL,
                  PRIMARY KEY (recurso_id, token),
                  FOREIGN KEY (recurso_id) REFERENCES recursos (id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_recurso_tokens_token ON recurso_tokens (token);

                CREATE TABLE IF NOT EXISTS eventos (
                  id      INTEGER PRIMARY KEY AUTOINCREMENT,
                  tipo    TEXT NOT NULL,
                  consulta TEXT,
                  huella  TEXT,
                  tokens  INTEGER NOT NULL DEFAULT 0,
                  detalle TEXT,
                  ts      TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos (ts DESC);
                """
            )
            self.con.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (VERSION_ESQUEMA, ahora_iso()),
            )

    # -- eventos -----------------------------------------------------------

    def registrar_evento(self, tipo: str, consulta: str = "", huella: str = "",
                         tokens: int = 0, detalle: str = "") -> None:
        """Registra un acceso para poder medir aciertos y ahorro real."""
        try:
            with self._lock:
                self.con.execute(
                    "INSERT INTO eventos (tipo, consulta, huella, tokens, detalle, ts)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (tipo, (consulta or "")[:2000], huella or "",
                     max(0, int(tokens or 0)), (detalle or "")[:2000], ahora_iso()),
                )
                # Poda barata: se conservan los eventos recientes.
                if self.max_eventos:
                    self.con.execute(
                        "DELETE FROM eventos WHERE id <= "
                        "(SELECT MAX(id) - ? FROM eventos)",
                        (self.max_eventos,),
                    )
        except sqlite3.DatabaseError:  # pragma: no cover - best effort
            pass

    # -- procesos ----------------------------------------------------------

    def guardar_proceso(self, intencion: str, resultado: str, huella: str,
                        pasos=None, contexto=None, referencia: str | None = None,
                        estado: str = "candidato", firma_w=None, espacios_w=None,
                        tokens_texto=None, tokens: int = 0,
                        coste_tokens: int = 0) -> dict:
        """Guarda (o actualiza por huella) un proceso reutilizable.

        Args:
            intencion: tarea en lenguaje natural, tal como la formuló el agente.
            resultado: resultado condensado; se redacta y se recorta al
                presupuesto configurado (un recurso debe costar tokens acotados).
            huella: clave semántica estable (tokens normalizados ordenados).
            pasos: lista de pasos o texto con el procedimiento.
            contexto: metadatos libres (repo, archivos, preset, skill...).
            referencia: commit, ruta o URL opcional.
            estado: candidato|validado|obsoleto|rechazado.
            firma_w / espacios_w: geometría W 4D calculada por el puente.
            tokens_texto: tokens normalizados, para el índice de candidatos.
            tokens: coste estimado en tokens de obtener el resultado.
            coste_tokens: coste real por paso (lo aporta el agente si lo sabe).

        Returns:
            dict con id, huella, actualizado, entradas y redacciones.
        """
        if estado not in ESTADOS_PROCESO:
            estado = "candidato"
        intencion_limpia, redacciones_intencion = _redactar(intencion)
        resultado_limpio, redacciones_resultado = _redactar(resultado, self.presupuesto)
        contexto_limpio = _serializar_contexto(contexto)
        pasos_limpios = _serializar_pasos(pasos)
        referencia_limpia = (_redactar(referencia or "")[0] or None)
        tokens_texto = [str(t) for t in (tokens_texto or []) if t]
        firma_json = _json([float(v) for v in (firma_w or [])])
        espacios_json = _json([int(v) for v in (espacios_w or [])])
        ahora = ahora_iso()

        def trabajo():
            fila = self.con.execute(
                "SELECT id, estado, creado_en FROM procesos WHERE huella = ?", (huella,)
            ).fetchone()
            if fila is None:
                # Poda por volumen: se eliminan los procesos más antiguos que no
                # hayan demostrado utilidad y estén fuera del estado validado.
                self.con.execute(
                    "DELETE FROM procesos WHERE id IN ("
                    "  SELECT id FROM procesos"
                    "   WHERE estado NOT IN ('validado') AND exitos = 0"
                    "   ORDER BY actualizado_en ASC LIMIT ?"
                    ")",
                    (max(0, self._contar("procesos") - self.max_procesos + 1),),
                )
                cursor = self.con.execute(
                    "INSERT INTO procesos (huella, intencion, contexto, pasos, resultado,"
                    " referencia, estado, firma_w, espacios_w, exitos, fallos,"
                    " tokens_ahorrados, coste_tokens, creado_en, actualizado_en, ultimo_uso)"
                    " VALUES (?,?,?,?,?,?,?,?,?,0,0,0,?,?,?,NULL)",
                    (huella, intencion_limpia, contexto_limpio, pasos_limpios,
                     resultado_limpio, referencia_limpia, estado, firma_json,
                     espacios_json, max(0, int(coste_tokens or 0)), ahora, ahora),
                )
                proceso_id = int(cursor.lastrowid)
                actualizado = False
            else:
                proceso_id = int(fila["id"])
                # Actualizar conservando la métrica acumulada y respetando un
                # estado ya validado salvo que el agente lo degrade a propósito.
                nuevo_estado = estado if estado != "candidato" else fila["estado"]
                self.con.execute(
                    "UPDATE procesos SET intencion = ?, contexto = ?, pasos = ?,"
                    " resultado = ?, referencia = ?, estado = ?, firma_w = ?,"
                    " espacios_w = ?, actualizado_en = ?,"
                    " coste_tokens = coste_tokens + ?,"
                    " tokens_ahorrados = MAX(tokens_ahorrados, 0),"
                    " exitos = exitos, fallos = fallos"
                    " WHERE id = ?",
                    (intencion_limpia, contexto_limpio, pasos_limpios, resultado_limpio,
                     referencia_limpia, nuevo_estado, firma_json, espacios_json,
                     ahora, max(0, int(coste_tokens or 0)), proceso_id),
                )
                actualizado = True

            self._indexar_tokens("proceso_tokens", "proceso_id", proceso_id, tokens_texto)
            entradas = self._contar("procesos")
            return proceso_id, actualizado, entradas

        with self._lock:
            proceso_id, actualizado, entradas = self._transaccion(trabajo)
        self.registrar_evento("proceso_guardar", intencion,
                              huella, tokens, f"id={proceso_id}")
        return {
            "id": proceso_id,
            "huella": huella,
            "actualizado": actualizado,
            "entradas": entradas,
            "tokens": max(0, int(tokens or 0)),
            "redacciones": redacciones_intencion + redacciones_resultado,
            "truncado": (len(resultado or "") > self.presupuesto),
        }

    def candidatos_procesos(self, tokens_texto, limite: int = 200,
                            min_comunes: int = 1) -> list[dict]:
        """Prefiltro SQL por tokens compartidos; el puente puntúa la geometría.

        Sin tokens de consulta devuelve los procesos más recientes (para que una
        consulta muy corta aún pueda recuperar algo útil).
        """
        tokens = sorted({str(t) for t in (tokens_texto or []) if t})
        with self._lock:
            if not tokens:
                filas = self.con.execute(
                    "SELECT * FROM procesos WHERE estado NOT IN ('obsoleto','rechazado')"
                    " ORDER BY actualizado_en DESC LIMIT ?",
                    (limite,),
                ).fetchall()
            else:
                marcadores = ",".join("?" for _ in tokens)
                filas = self.con.execute(
                    "SELECT p.*, c.comunes FROM ("
                    "  SELECT proceso_id, COUNT(*) AS comunes FROM proceso_tokens"
                    f"  WHERE token IN ({marcadores})"
                    "  GROUP BY proceso_id HAVING COUNT(*) >= ?"
                    "  ORDER BY comunes DESC LIMIT ?"
                    ") c JOIN procesos p ON p.id = c.proceso_id"
                    " WHERE p.estado NOT IN ('obsoleto','rechazado')"
                    " ORDER BY c.comunes DESC, p.actualizado_en DESC",
                    (*tokens, max(1, int(min_comunes)), limite),
                ).fetchall()
            return [self._fila_proceso(f) for f in filas]

    def proceso_por_id(self, proceso_id: int) -> dict | None:
        with self._lock:
            fila = self.con.execute(
                "SELECT * FROM procesos WHERE id = ?", (int(proceso_id),)
            ).fetchone()
        return self._fila_proceso(fila) if fila else None

    def registrar_uso_proceso(self, proceso_id: int, exito: bool = True,
                              tokens_ahorrados: int = 0) -> dict:
        """Feedback explícito: un proceso reutilizado sube (o baja) de confianza."""
        ahora = ahora_iso()
        with self._lock:
            self.con.execute(
                "UPDATE procesos SET"
                " exitos = exitos + ?, fallos = fallos + ?,"
                " tokens_ahorrados = tokens_ahorrados + ?, ultimo_uso = ?"
                " WHERE id = ?",
                (1 if exito else 0, 0 if exito else 1,
                 max(0, int(tokens_ahorrados or 0)), ahora, int(proceso_id)),
            )
            fila = self.con.execute(
                "SELECT id, exitos, fallos, estado FROM procesos WHERE id = ?",
                (int(proceso_id),),
            ).fetchone()
        if fila is None:
            return {"id": int(proceso_id), "actualizado": False}
        # Un proceso que acierta 3 veces sin fallar se promociona a validado: es
        # la señal de que otra sesión puede confiar en él sin revalidar.
        if fila["exitos"] >= 3 and fila["fallos"] == 0 and fila["estado"] == "candidato":
            with self._lock:
                self.con.execute(
                    "UPDATE procesos SET estado = 'validado', actualizado_en = ? WHERE id = ?",
                    (ahora, int(proceso_id)),
                )
        return {
            "id": int(proceso_id),
            "exitos": int(fila["exitos"]),
            "fallos": int(fila["fallos"]),
            "estado": "validado" if (fila["exitos"] >= 3 and fila["fallos"] == 0) else fila["estado"],
        }

    def marcar_proceso(self, proceso_id: int, estado: str) -> dict:
        if estado not in ESTADOS_PROCESO:
            raise ValueError(f"estado invalido: {estado}")
        with self._lock:
            self.con.execute(
                "UPDATE procesos SET estado = ?, actualizado_en = ? WHERE id = ?",
                (estado, ahora_iso(), int(proceso_id)),
            )
        return {"id": int(proceso_id), "estado": estado}

    # -- lecciones ---------------------------------------------------------

    def guardar_leccion(self, error_signature: str, tipo: str = "",
                        causa: str = "", correccion: str = "",
                        prevencion: str = "", modulo: str = "",
                        verificado: bool = False, tokens_texto=None) -> dict:
        """Guarda una lección de error; la clave es la firma del error."""
        error_signature = (error_signature or "").strip()[:512]
        if not error_signature:
            raise ValueError("error_signature vacia")
        campos = {}
        for clave, valor in (("tipo", tipo), ("causa", causa),
                             ("correccion", correccion),
                             ("prevencion", prevencion), ("modulo", modulo)):
            campos[clave] = _redactar(valor or "")[0]
        ahora = ahora_iso()
        tokens_texto = [str(t) for t in (tokens_texto or [])
                        if t][:120]

        def trabajo():
            fila = self.con.execute(
                "SELECT id FROM lecciones WHERE error_signature = ?",
                (error_signature,),
            ).fetchone()
            if fila is None:
                cursor = self.con.execute(
                    "INSERT INTO lecciones (error_signature, tipo, causa, correccion,"
                    " prevencion, modulo, tokens_texto, verificado, creado_en, actualizado_en)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (error_signature, campos["tipo"], campos["causa"],
                     campos["correccion"], campos["prevencion"], campos["modulo"],
                     _json(tokens_texto), 1 if verificado else 0, ahora, ahora),
                )
                leccion_id = int(cursor.lastrowid)
            else:
                leccion_id = int(fila["id"])
                self.con.execute(
                    "UPDATE lecciones SET tipo = COALESCE(NULLIF(?, ''), tipo),"
                    " causa = COALESCE(NULLIF(?, ''), causa),"
                    " correccion = COALESCE(NULLIF(?, ''), correccion),"
                    " prevencion = COALESCE(NULLIF(?, ''), prevencion),"
                    " modulo = COALESCE(NULLIF(?, ''), modulo),"
                    " tokens_texto = COALESCE(NULLIF(?, ''), tokens_texto),"
                    " verificado = MAX(verificado, ?), actualizado_en = ?"
                    " WHERE id = ?",
                    (campos["tipo"], campos["causa"], campos["correccion"],
                     campos["prevencion"], campos["modulo"], _json(tokens_texto),
                     1 if verificado else 0, ahora, leccion_id),
                )
            self._indexar_tokens("leccion_tokens", "leccion_id", leccion_id, tokens_texto)
            return leccion_id

        with self._lock:
            leccion_id = self._transaccion(trabajo)
        return {"id": leccion_id, "error_signature": error_signature}

    def candidatos_lecciones(self, tokens_texto, limite: int = 50,
                             min_comunes: int = 1) -> list[dict]:
        tokens = sorted({str(t) for t in (tokens_texto or []) if t})
        with self._lock:
            if not tokens:
                filas = self.con.execute(
                    "SELECT * FROM lecciones ORDER BY actualizado_en DESC LIMIT ?",
                    (limite,),
                ).fetchall()
            else:
                marcadores = ",".join("?" for _ in tokens)
                filas = self.con.execute(
                    "SELECT l.*, c.comunes FROM ("
                    "  SELECT leccion_id, COUNT(*) AS comunes FROM leccion_tokens"
                    f"  WHERE token IN ({marcadores})"
                    "  GROUP BY leccion_id HAVING COUNT(*) >= ?"
                    "  ORDER BY comunes DESC LIMIT ?"
                    ") c JOIN lecciones l ON l.id = c.leccion_id"
                    " ORDER BY c.comunes DESC, l.actualizado_en DESC",
                    (*tokens, max(1, int(min_comunes)), limite),
                ).fetchall()
            return [self._fila_leccion(f) for f in filas]

    def _fila_leccion(self, fila) -> dict:
        datos = dict(fila)
        datos["tokens_texto"] = _deserializar(datos.get("tokens_texto"), [])
        datos["verificado"] = bool(datos.get("verificado"))
        return datos

    # -- recursos (catálogo de skills/agentes/documentos/herramientas) -----

    def indexar_recurso(self, clave: str, tipo: str, nombre: str,
                        ruta: str = "", descripcion: str = "",
                        extracto: str = "", contenido_hash: str = "",
                        firma_w=None, espacios_w=None, tokens_texto=None) -> dict:
        """Inserta o actualiza un recurso del catálogo (idempotente por clave)."""
        if tipo not in TIPOS_RECURSO:
            tipo = "documento"
        descripcion_limpia = _redactar(descripcion or "")[0][:2000]
        extracto_limpio = _redactar(extracto or "")[0][:1200]
        ahora = ahora_iso()
        firma_json = _json([float(v) for v in (firma_w or [])])
        espacios_json = _json([int(v) for v in (espacios_w or [])])
        tokens_texto = [str(t) for t in (tokens_texto or []) if t][:200]

        with self._lock:
            self.con.execute(
                "INSERT INTO recursos (clave, tipo, nombre, ruta, descripcion,"
                " extracto, contenido_hash, firma_w, espacios_w, tokens, actualizado_en)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT (clave) DO UPDATE SET"
                "  tipo = excluded.tipo, nombre = excluded.nombre, ruta = excluded.ruta,"
                "  descripcion = excluded.descripcion, extracto = excluded.extracto,"
                "  contenido_hash = excluded.contenido_hash, firma_w = excluded.firma_w,"
                "  espacios_w = excluded.espacios_w, tokens = excluded.tokens,"
                "  actualizado_en = excluded.actualizado_en",
                (clave, tipo, nombre[:300], ruta or "", descripcion_limpia,
                 extracto_limpio, contenido_hash or "", firma_json, espacios_json,
                 len(tokens_texto), ahora),
            )
            fila = self.con.execute(
                "SELECT id FROM recursos WHERE clave = ?", (clave,)
            ).fetchone()
            recurso_id = int(fila["id"])
            self._indexar_tokens("recurso_tokens", "recurso_id", recurso_id, tokens_texto)
            return {"id": recurso_id, "clave": clave}

    def candidatos_recursos(self, tokens_texto, tipo: str | None = None,
                            limite: int = 100, min_comunes: int = 1) -> list[dict]:
        tokens = sorted({str(t) for t in (tokens_texto or []) if t})
        filtro_tipo = " AND r.tipo = ?" if tipo and tipo in TIPOS_RECURSO else ""
        with self._lock:
            if not tokens:
                sql = ("SELECT r.* FROM recursos r WHERE 1=1" + filtro_tipo +
                       " ORDER BY r.actualizado_en DESC LIMIT ?")
                parametros = ([tipo] if filtro_tipo else []) + [limite]
                filas = self.con.execute(sql, parametros).fetchall()
            else:
                marcadores = ",".join("?" for _ in tokens)
                sql = (
                    "SELECT r.*, c.comunes FROM ("
                    "  SELECT recurso_id, COUNT(*) AS comunes FROM recurso_tokens"
                    f"  WHERE token IN ({marcadores})"
                    "  GROUP BY recurso_id HAVING COUNT(*) >= ?"
                    "  ORDER BY comunes DESC LIMIT ?"
                    ") c JOIN recursos r ON r.id = c.recurso_id WHERE 1=1"
                    + filtro_tipo +
                    " ORDER BY c.comunes DESC, r.actualizado_en DESC"
                )
                parametros = list(tokens) + [max(1, int(min_comunes)), limite]
                if filtro_tipo:
                    parametros.append(tipo)
                filas = self.con.execute(sql, parametros).fetchall()
            return [self._fila_recurso(f) for f in filas]

    def recursos_por_tipo(self, tipo: str) -> list[dict]:
        with self._lock:
            filas = self.con.execute(
                "SELECT * FROM recursos WHERE tipo = ?", (tipo,)
            ).fetchall()
        return [self._fila_recurso(f) for f in filas]

    # -- utilidades internas ----------------------------------------------

    def _indexar_tokens(self, tabla: str, columna: str, id_: int, tokens) -> None:
        """Reemplaza el índice de tokens de una fila (tabla ya validada)."""
        self.con.execute(f"DELETE FROM {tabla} WHERE {columna} = ?", (id_,))
        unicos = sorted({str(t)[:64] for t in (tokens or []) if t})
        if unicos:
            self.con.executemany(
                f"INSERT OR IGNORE INTO {tabla} ({columna}, token) VALUES (?, ?)",
                [(id_, t) for t in unicos],
            )

    def _contar(self, tabla: str) -> int:
        fila = self.con.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()
        return int(fila["n"]) if fila else 0

    def _fila_proceso(self, fila) -> dict:
        return {
            "id": int(fila["id"]),
            "huella": fila["huella"],
            "intencion": fila["intencion"],
            "contexto": _deserializar(fila["contexto"], {}),
            "pasos": _deserializar(fila["pasos"], []),
            "resultado": fila["resultado"],
            "referencia": fila["referencia"],
            "estado": fila["estado"],
            "firma_w": _deserializar(fila["firma_w"], []),
            "espacios_w": _deserializar(fila["espacios_w"], []),
            "exitos": int(fila["exitos"]),
            "fallos": int(fila["fallos"]),
            "tokens_ahorrados": int(fila["tokens_ahorrados"]),
            "coste_tokens": int(fila["coste_tokens"]),
            "creado_en": fila["creado_en"],
            "actualizado_en": fila["actualizado_en"],
            "ultimo_uso": fila["ultimo_uso"],
        }

    def _fila_recurso(self, fila) -> dict:
        return {
            "id": int(fila["id"]),
            "clave": fila["clave"],
            "tipo": fila["tipo"],
            "nombre": fila["nombre"],
            "ruta": fila["ruta"],
            "descripcion": fila["descripcion"],
            "extracto": fila["extracto"],
            "firma_w": _deserializar(fila["firma_w"], []),
            "espacios_w": _deserializar(fila["espacios_w"], []),
            "actualizado_en": fila["actualizado_en"],
        }

    # -- mantenimiento / métricas -----------------------------------------

    def estadisticas(self) -> dict:
        """Métricas de la memoria: volumen, aciertos y ahorro acumulado."""
        with self._lock:
            procesos = self._contar("procesos")
            validados = self.con.execute(
                "SELECT COUNT(*) AS n FROM procesos WHERE estado = 'validado'"
            ).fetchone()["n"]
            lecciones = self._contar("lecciones")
            recursos = self._contar("recursos")
            eventos = self._contar("eventos")
            aciertos = self.con.execute(
                "SELECT COUNT(*) AS n FROM eventos WHERE tipo IN"
                " ('cache_hit','proceso_hit','leccion_hit','recurso_hit')"
            ).fetchone()["n"]
            fallos = self.con.execute(
                "SELECT COUNT(*) AS n FROM eventos WHERE tipo IN"
                " ('cache_miss','proceso_miss')"
            ).fetchone()["n"]
            tokens_procesos = self.con.execute(
                "SELECT COALESCE(SUM(tokens_ahorrados), 0) AS n FROM procesos"
            ).fetchone()["n"]
            tokens_eventos = self.con.execute(
                "SELECT COALESCE(SUM(tokens), 0) AS n FROM eventos"
            ).fetchone()["n"]
            por_tipo = {
                fila["tipo"]: int(fila["n"])
                for fila in self.con.execute(
                    "SELECT tipo, COUNT(*) AS n FROM recursos GROUP BY tipo"
                ).fetchall()
            }
            tamano = 0
            for sufijo in ("", "-wal", "-shm"):
                ruta = self.ruta + sufijo
                try:
                    tamano += os.path.getsize(ruta)
                except OSError:
                    pass
            return {
                "ruta": self.ruta,
                "version_esquema": VERSION_ESQUEMA,
                "procesos": procesos,
                "procesos_validados": int(validados),
                "lecciones": lecciones,
                "recursos": recursos,
                "recursos_por_tipo": por_tipo,
                "eventos": eventos,
                "aciertos": aciertos,
                "fallos": fallos,
                "hit_rate": (aciertos / (aciertos + fallos)) if (aciertos + fallos) else 0.0,
                "tokens_ahorrados_procesos": int(tokens_procesos),
                "tokens_eventos": int(tokens_eventos),
                "presupuesto_caracteres": self.presupuesto,
                "tamano_bytes": tamano,
            }

    def cerrar(self) -> None:
        """Cierra la conexión y consolida el WAL."""
        with self._lock:
            try:
                self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.DatabaseError:  # pragma: no cover
                pass
            try:
                self.con.close()
            except sqlite3.DatabaseError:  # pragma: no cover
                pass


# ---------------------------------------------------------------------------
# Helpers de serialización
# ---------------------------------------------------------------------------


def _serializar_pasos(pasos) -> str | None:
    """Normaliza los pasos a texto legible (JSON serializado si es lista)."""
    if pasos is None:
        return None
    if isinstance(pasos, str):
        limpio, _ = _redactar(pasos)
        return limpio
    try:
        limpio, _ = _redactar(json.dumps(pasos, ensure_ascii=False, default=str))
        return limpio
    except (TypeError, ValueError):
        return _redactar(str(pasos))[0]


def _serializar_contexto(contexto) -> str | None:
    if contexto is None:
        return None
    if isinstance(contexto, str):
        return _redactar(contexto)[0] or None
    try:
        texto = json.dumps(contexto, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        texto = str(contexto)
    limpio, _ = _redactar(texto)
    return limpio or None


def resolver_ruta_memoria(ruta_configurada: str | None,
                          carpeta_paquete: str) -> str:
    """Resuelve la ruta de la base: configuración, o `<paquete>/memoria/`."""
    if ruta_configurada and str(ruta_configurada).strip():
        return os.path.abspath(os.path.expanduser(str(ruta_configurada).strip()))
    return os.path.join(os.path.abspath(carpeta_paquete), "memoria", NOMBRE_BASE)


if __name__ == "__main__":  # pragma: no cover - utilidad manual
    import sys

    ruta = sys.argv[1] if len(sys.argv) > 1 else resolver_ruta_memoria(None, ".")
    memoria = MemoriaVectorW(ruta)
    print(json.dumps(memoria.estadisticas(), ensure_ascii=False, indent=2))
    memoria.cerrar()
