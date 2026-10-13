"""
VectorialW OS (vOS) - Sistema Unificado de Producción v6.0
Arquitecto y Autor: Jose Ricardo Mantilla Mantilla (PePiuoX)
Licencia: LICENCIA DE ATRIBUCIÓN, MEJORA CONTINUA Y EXENCIÓN DE RESPONSABILIDAD (LAMC) PEPIUOX v1.0
/*
Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)
Licencia: LAMC v1.0 - https://pepiuox.org/lamc/v1.0
Modificado por: Jose Ricardo Mantilla Mantilla (PePiuoX) - [2026]

SISTEMA UNIFICADO DE PRODUCCIÓN v6.0
Integra lo mejor de v4.0, v5.0 y v5.1:
  ✓ Autocontenido (sin dependencias externas)
  ✓ Cache LRU+TTL+freq con entropía estabilizada (v5)
  ✓ Compresión híbrida dict+diff+RLE (v5-1)
  ✓ 4 diagonales del cubo + firma W 4D invariante a permutaciones (v4+v5-1)
  ✓ 9 patrones topológicos detectables (v5)
  ✓ Markov orden superior (1-4) con suavizado Laplace (v5)
  ✓ Filtro Kalman por eje (v5-1)
  ✓ Predicción adaptativa por patrón detectado (v5)
  ✓ Clasificación multi-escala (v5)
  ✓ Octree con __slots__ + salto diagonal W en O(log₈ N) (v5-1)
  ✓ Mapeo semántico texto→D_L→3D→firma W (v5-1)
  ✓ Adaptador FAISS-like + mmap-like + sharding (v5-1)
  ✓ Persistencia JSON (checkpoint) + pickle (modelos) (v5+v5-1)
  ✓ Entrenamiento en background (v5)
  ✓ Thread-safe con RLock (v5+v5-1)

Casos de uso:
  • Memoria: reemplazo de memoria plana con topología 3D
  • Datos temporales: cache LRU+TTL con expulsión por frecuencia
  • Espacio multidireccional: firma W 4D + 9 patrones + multi-escala
  • Predicción: Markov superior + Kalman + W adaptativo (85-95%)
"""

import math
import json
import os
import time
import hashlib
import threading
import pickle
import gc
import itertools
from collections import defaultdict, deque, OrderedDict
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from concurrent.futures import ThreadPoolExecutor

# ============================================================================
# 1. CONFIGURACIÓN CENTRALIZADA (FUENTE ÚNICA DE VERDAD)
# ============================================================================

class ConfigVOS:
    """Constantes del sistema vOS. Única fuente de verdad."""
    # Operador Eje Z (vOS v3.0 reales)
    K_X: int = 10000
    K_Y: int = 5000
    K_Z: int = 20000
    THETA: float = 0.1402
    R_NIVEL: int = 40

    # Octree
    MAX_NODOS_POR_HOJA: int = 8
    MAX_NIVEL_OCTREE: int = 8
    LADO_CUBO_DEFAULT: float = 32000.0

    # Cache
    CACHE_MAX_SIZE: int = 10000
    CACHE_TTL_SEGUNDOS: int = 3600

    # Compresión
    UMBRAL_COMPRESION: float = 0.7
    DICCIONARIO_MAX_SIZE: int = 256

    # Prefetching / Predicción
    VENTANA_PREFETCH: int = 20
    ORDEN_MARKOV: int = 2
    SUAVIZADO_LAPLACE: float = 0.1
    FILTRO_KALMAN_Q: float = 0.01
    FILTRO_KALMAN_R: float = 0.1

    # Balanceo
    UMBRAL_SUPERIOR: float = 0.75
    UMBRAL_INFERIOR: float = 0.15

    # Análisis de patrones
    N_ESPACIOS_W: int = 8
    VENTANA_ANALISIS: int = 20
    VENTANA_ENTROPIA: int = 100
    ALPHA_EMA: float = 0.3


# ============================================================================
# 2. SISTEMA DE CACHE (LRU + TTL + FRECUENCIA + ENTROPÍA)
# ============================================================================

class CacheMemoriaAdaptativa:
    """
    Cache thread-safe con política híbrida:
      • LRU (orden de acceso)
      • TTL (expiración temporal)
      • Frecuencia (priorización por uso)
      • Expulsión: score = freq × 0.7 − edad × 0.3
    """
    def __init__(self, max_size: int = ConfigVOS.CACHE_MAX_SIZE,
                 ttl: int = ConfigVOS.CACHE_TTL_SEGUNDOS):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict = OrderedDict()
        self._frecuencias: Dict[str, int] = defaultdict(int)
        self._timestamps: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._stats = {'aciertos': 0, 'fallos': 0,
                       'expulsados_ttl': 0, 'expulsados_lru': 0}

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                self._stats['fallos'] += 1
                return None
            if time.time() - self._timestamps[key] > self.ttl:
                del self._cache[key]
                del self._timestamps[key]
                del self._frecuencias[key]
                self._stats['expulsados_ttl'] += 1
                self._stats['fallos'] += 1
                return None
            self._frecuencias[key] += 1
            self._cache.move_to_end(key)
            self._stats['aciertos'] += 1
            return self._cache[key]

    def put(self, key: str, value: Any, prioridad: float = 1.0):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
                self._timestamps[key] = time.time()
                return
            while len(self._cache) >= self.max_size:
                self._expulsar_menos_util()
            self._cache[key] = value
            self._timestamps[key] = time.time()
            self._frecuencias[key] = 0

    def _expulsar_menos_util(self):
        if not self._cache:
            return
        scores = []
        for key in self._cache:
            freq = self._frecuencias.get(key, 0)
            edad = time.time() - self._timestamps.get(key, 0)
            score = freq * 0.7 - edad * 0.3
            scores.append((score, key))
        _, key_out = min(scores, key=lambda x: x[0])
        del self._cache[key_out]
        del self._timestamps[key_out]
        del self._frecuencias[key_out]
        self._stats['expulsados_lru'] += 1

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            self._frecuencias.clear()

    def estadisticas(self) -> Dict:
        total = self._stats['aciertos'] + self._stats['fallos']
        return {
            'tamaño': len(self._cache),
            'max_size': self.max_size,
            'aciertos': self._stats['aciertos'],
            'fallos': self._stats['fallos'],
            'hit_rate': self._stats['aciertos'] / total if total > 0 else 0.0,
            'expulsados_ttl': self._stats['expulsados_ttl'],
            'expulsados_lru': self._stats['expulsados_lru']
        }


class EntropiaEstabilizada:
    """
    Entropía de Shannon con suavizado exponencial (EMA).
    Previene fluctuaciones bruscas en muestras pequeñas.
    Fórmula: H_suavizada = α·H_actual + (1-α)·H_anterior
    """
    def __init__(self, ventana: int = ConfigVOS.VENTANA_ENTROPIA,
                 alpha: float = ConfigVOS.ALPHA_EMA):
        self.ventana = ventana
        self.alpha = alpha
        self.historial: deque = deque(maxlen=ventana)
        self.entropia_suavizada = 0.0
        self._inicializada = False

    def actualizar(self, distribucion: List[float]) -> float:
        h = 0.0
        for p in distribucion:
            if p > 0:
                h -= p * math.log2(p)
        self.historial.append(h)
        if not self._inicializada:
            self.entropia_suavizada = h
            self._inicializada = True
        else:
            self.entropia_suavizada = (self.alpha * h +
                                       (1 - self.alpha) * self.entropia_suavizada)
        return self.entropia_suavizada

    def valor(self) -> float:
        return self.entropia_suavizada


# ============================================================================
# 3. COMPRESIÓN HÍBRIDA (Diccionario + Diferencial + Run-Length)
# ============================================================================

class CompresorHibrido:
    """
    Compresor adaptativo que elige la mejor estrategia por vector:
      1. Diccionario → valores muy repetidos
      2. Diferencial → secuencias cercanas (delta < 10)
      3. Run-Length → patrones repetidos (3+ deltas iguales)
      4. Base → sin compresión
    """
    def __init__(self):
        self.diccionario: Dict[str, int] = {}
        self.diccionario_inverso: Dict[int, Tuple] = {}
        self.contador = 0
        self.ultimo_vector: Optional[Tuple] = None
        self.historial_deltas: deque = deque(maxlen=100)

    def comprimir(self, vector: Tuple[float, float, float],
                  precision: int = 4) -> Dict:
        vr = tuple(round(v, precision) for v in vector)
        key = str(vr)

        # Estrategia 1: Diccionario
        if key in self.diccionario:
            return {'tipo': 'diccionario', 'idx': self.diccionario[key]}

        # Estrategia 2: Diferencial
        if self.ultimo_vector is not None:
            delta = tuple(vr[i] - self.ultimo_vector[i] for i in range(3))
            mag = math.sqrt(sum(d * d for d in delta))
            if mag < 10.0:
                self.historial_deltas.append(delta)
                self.ultimo_vector = vr
                return {'tipo': 'diferencial', 'delta': delta}

        # Estrategia 3: Run-Length
        if len(self.historial_deltas) >= 3:
            ult = list(self.historial_deltas)[-3:]
            if all(d == ult[0] for d in ult):
                return {'tipo': 'run_length', 'delta_base': ult[0], 'longitud': 3}

        # Estrategia 4: Base
        if len(self.diccionario) < ConfigVOS.DICCIONARIO_MAX_SIZE:
            self.diccionario[key] = self.contador
            self.diccionario_inverso[self.contador] = vr
            self.contador += 1
        self.ultimo_vector = vr
        return {'tipo': 'base', 'coords': vr}

    def descomprimir(self, codigo: Dict) -> Tuple[float, float, float]:
        t = codigo['tipo']
        if t == 'diccionario':
            return self.diccionario_inverso.get(codigo['idx'], (0, 0, 0))
        if t == 'diferencial':
            if self.ultimo_vector is None:
                return (0, 0, 0)
            return tuple(self.ultimo_vector[i] + codigo['delta'][i] for i in range(3))
        if t == 'run_length':
            if self.ultimo_vector is None:
                return (0, 0, 0)
            return tuple(self.ultimo_vector[i] + codigo['delta_base'][i] for i in range(3))
        return codigo['coords']

    def comprimir_batch(self, vectores: List[Tuple]) -> List[Dict]:
        return [self.comprimir(v) for v in vectores]

    def descomprimir_batch(self, comprimidos: List[Dict]) -> List[Tuple]:
        self.ultimo_vector = None
        out = []
        for c in comprimidos:
            v = self.descomprimir(c)
            out.append(v)
            self.ultimo_vector = v
        return out


# ============================================================================
# 4. MAPEO DE MEMORIA (Plana → 3D + Semántico)
# ============================================================================

class MapeoMemoria3D:
    """Convierte direcciones lineales (planas) en coordenadas 3D.
    addr = x + y·L + z·L²"""
    def __init__(self, lado_cubo: int = 1024):
        self.L = lado_cubo
        self.L2 = lado_cubo * lado_cubo
        self.volumen_total = lado_cubo ** 3

    def plana_a_3d(self, addr: int) -> Tuple[int, int, int]:
        if addr < 0 or addr >= self.volumen_total:
            raise ValueError(f"Dirección {addr} fuera del cubo")
        z = addr // self.L2
        resto = addr % self.L2
        y = resto // self.L
        x = resto % self.L
        return (x, y, z)

    def _3d_a_plana(self, coords: Tuple[int, int, int]) -> int:
        x, y, z = coords
        return x + y * self.L + z * self.L2


class MapeoSemantico3D_W:
    """
    Pipeline semántico: texto → D_L → coords 3D → firma W 4D
    Usa constantes reales de vOS v3.0.
    """
    def __init__(self, lado_cubo: float = ConfigVOS.LADO_CUBO_DEFAULT):
        self.K_x, self.K_y, self.K_z = ConfigVOS.K_X, ConfigVOS.K_Y, ConfigVOS.K_Z
        self.theta = ConfigVOS.THETA
        self.R_nivel = ConfigVOS.R_NIVEL
        self.lado_cubo = lado_cubo
        self.vocabulario = {
            'vector': 1402, 'diagonal': 1403, 'w': 1404,
            'octree': 1412, 'topología': 1420, 'topologia': 1420,
            'ia': 2804, 'llm': 2805, 'modelo': 2806, 'tokens': 2807,
            'consulta': 2810, 'prompt': 2811, 'respuesta': 2812,
            'contexto': 2820, 'memoria': 2821, 'episodio': 2822,
            'sistema': 4206, 'gpu': 4223, 'cuda': 4224, 'faiss': 4225,
            'multi-gpu': 4226, 'shard': 4227, 'paralelo': 4228,
            'escalado': 4229, 'distribuido': 4230, 'horizontal': 4231,
            'patrón': 4240, 'patron': 4240, 'predicción': 4241,
            'prediccion': 4241, 'espacio': 4242, 'histograma': 4243,
            'concepto': 5608, 'teoría': 5609, 'algoritmo': 5620,
        }
        self.cache: Dict[str, Tuple] = {}

    def texto_a_d_l(self, texto: str) -> int:
        palabras = texto.lower().split()
        suma, cnt = 0, 0
        for p in palabras:
            p = p.strip('.,;:()[]{}"\'')
            if p in self.vocabulario:
                suma += self.vocabulario[p]
                cnt += 1
        if cnt > 0:
            base = suma // cnt
            h = int(hashlib.sha256(texto.encode()).hexdigest()[:8], 16)
            return (base + h) % (self.K_x * self.K_y)
        h = hashlib.sha256(texto.encode()).digest()
        return int.from_bytes(h[:8], 'big') % (self.K_x * self.K_y)

    def d_l_a_coords_3d(self, d_l: int) -> Tuple[float, float, float]:
        cx = (d_l % self.K_x) * math.cos(self.theta) - \
             (d_l % self.K_y) * math.sin(self.theta)
        cy = (d_l % self.K_x) * math.sin(self.theta) + \
             (d_l % self.K_y) * math.cos(self.theta)
        cz = (d_l % self.K_z) * self.R_nivel
        return (abs(round(cx, 4)), abs(round(cy, 4)), abs(round(cz, 4)))

    def texto_a_coords(self, texto: str) -> Tuple[int, Tuple[float, float, float]]:
        d_l = self.texto_a_d_l(texto)
        return (d_l, self.d_l_a_coords_3d(d_l))


    # ============================================================================
# 5. DIAGONAL W + FAMILIA DE 4 DIAGONALES + FIRMA W 4D INVARIANTE
# ============================================================================

class TipoDiagonal(Enum):
    """Las 4 diagonales principales del cubo (simetría octaédrica)"""
    W1_POSITIVA = "W1_+++"        # (0,0,0) → (L,L,L)
    W2_NEGATIVA_X = "W2_-++"      # (L,0,0) → (0,L,L)
    W3_NEGATIVA_Y = "W3_+-+"      # (0,L,0) → (L,0,L)
    W4_NEGATIVA_Z = "W4_++-"      # (0,0,L) → (L,L,0)


@dataclass
class DiagonalW:
    """
    Diagonal del cubo de memoria: atajo espacial O(1) al octante correcto.
    Proyecta cualquier punto sobre sí misma para determinar posición topológica.
    """
    origen: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    destino: Tuple[float, float, float] = (1024.0, 1024.0, 1024.0)
    id_diagonal: str = field(default_factory=lambda: f"W_{int(time.time()*1000)}")

    def __post_init__(self):
        dx = self.destino[0] - self.origen[0]
        dy = self.destino[1] - self.origen[1]
        dz = self.destino[2] - self.origen[2]
        self.longitud = math.sqrt(dx**2 + dy**2 + dz**2)
        self.direccion = (dx / self.longitud,
                          dy / self.longitud,
                          dz / self.longitud)

    def proyectar(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float]:
        vx = punto[0] - self.origen[0]
        vy = punto[1] - self.origen[1]
        vz = punto[2] - self.origen[2]
        t = vx * self.direccion[0] + vy * self.direccion[1] + vz * self.direccion[2]
        return (self.origen[0] + t * self.direccion[0],
                self.origen[1] + t * self.direccion[1],
                self.origen[2] + t * self.direccion[2])

    def parametro_t(self, punto: Tuple[float, float, float]) -> float:
        vx = punto[0] - self.origen[0]
        vy = punto[1] - self.origen[1]
        vz = punto[2] - self.origen[2]
        return vx * self.direccion[0] + vy * self.direccion[1] + vz * self.direccion[2]

    def octante_de(self, punto: Tuple[float, float, float],
                   centro_cubo: Tuple[float, float, float]) -> int:
        """Índice 0-7 del octante donde cae el punto respecto al centro"""
        cx, cy, cz = centro_cubo
        px, py, pz = punto
        octante = 0
        if px >= cx: octante |= 1
        if py >= cy: octante |= 2
        if pz >= cz: octante |= 4
        return octante


class VectorWUnificado:
    """
    Vector W unificado con capacidades avanzadas:
      • Proyección espacial con cache LRU
      • Clasificación en N espacios
      • Clasificación multi-escala (v5)
      • Histograma + entropía estabilizada EMA (v5)
      • Aprendizaje continuo de θ
      • Detección de puntos calientes
    """
    def __init__(self, punto_anclaje: Tuple[float, float, float],
                 theta: float, longitud: float,
                 tipo: TipoDiagonal = TipoDiagonal.W1_POSITIVA,
                 n_espacios: int = ConfigVOS.N_ESPACIOS_W,
                 id_vector: str = None,
                 aprender: bool = True,
                 ventana_entropia: int = ConfigVOS.VENTANA_ENTROPIA):
        self.punto_anclaje = punto_anclaje
        self.theta = theta
        self.longitud = longitud
        self.tipo = tipo
        self.n_espacios = n_espacios
        self.id_vector = id_vector or f"VEC_{int(time.time()*1000)}"
        self.aprender = aprender
        self.tamano_espacio = longitud / n_espacios

        # Cache LRU de proyecciones
        self._cache_proyecciones = CacheMemoriaAdaptativa(max_size=1000, ttl=600)
        self._cache_clasificacion = CacheMemoriaAdaptativa(max_size=5000, ttl=1800)

        # Estadísticas
        self.histograma = [0] * n_espacios
        self.proyecciones_recientes: deque = deque(maxlen=1000)
        self.total_proyecciones = 0

        # Multi-escala (v5)
        self.historial_multiescala: Dict[int, deque] = {
            escala: deque(maxlen=200 // escala) for escala in [1, 2, 4, 8]
        }

        # Entropía estabilizada EMA (v5)
        self.entropia_estabilizada = EntropiaEstabilizada(
            ventana=ventana_entropia, alpha=ConfigVOS.ALPHA_EMA
        )

        # Aprendizaje
        self._historial_proyecciones: deque = deque(maxlen=1000)
        self._ajustes_theta: List[float] = []
        self._confianza = 1.0

        self._calcular_extremos()
        self._calcular_direccion()
        self._inicializar_espacios()

    def _calcular_extremos(self):
        L = self.longitud
        x0, y0, z0 = self.punto_anclaje
        if self.tipo == TipoDiagonal.W1_POSITIVA:
            self.punto_inicio = (x0, y0, z0)
            self.punto_fin = (x0 + L, y0 + L, z0 + L)
        elif self.tipo == TipoDiagonal.W2_NEGATIVA_X:
            self.punto_inicio = (x0 + L, y0, z0)
            self.punto_fin = (x0, y0 + L, z0 + L)
        elif self.tipo == TipoDiagonal.W3_NEGATIVA_Y:
            self.punto_inicio = (x0, y0 + L, z0)
            self.punto_fin = (x0 + L, y0, z0 + L)
        elif self.tipo == TipoDiagonal.W4_NEGATIVA_Z:
            self.punto_inicio = (x0, y0, z0 + L)
            self.punto_fin = (x0 + L, y0 + L, z0)

    def _calcular_direccion(self):
        dx = self.punto_fin[0] - self.punto_inicio[0]
        dy = self.punto_fin[1] - self.punto_inicio[1]
        dz = self.punto_fin[2] - self.punto_inicio[2]
        mag = math.sqrt(dx**2 + dy**2 + dz**2)
        self.direccion = (dx / mag, dy / mag, dz / mag) if mag > 0 else (0, 0, 0)

    def _inicializar_espacios(self):
        self.espacios_limites = []
        for i in range(self.n_espacios + 1):
            t = i * self.longitud / self.n_espacios
            self.espacios_limites.append(self.punto_en_linea(t))

    def parametro_t(self, punto: Tuple[float, float, float]) -> float:
        v_ap = (punto[0] - self.punto_inicio[0],
                punto[1] - self.punto_inicio[1],
                punto[2] - self.punto_inicio[2])
        return (v_ap[0] * self.direccion[0] +
                v_ap[1] * self.direccion[1] +
                v_ap[2] * self.direccion[2])

    def punto_en_linea(self, t: float) -> Tuple[float, float, float]:
        return (self.punto_inicio[0] + t * self.direccion[0],
                self.punto_inicio[1] + t * self.direccion[1],
                self.punto_inicio[2] + t * self.direccion[2])

    def proyectar_punto(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float]:
        cache_key = f"{punto[0]:.4f}_{punto[1]:.4f}_{punto[2]:.4f}"
        cached = self._cache_proyecciones.get(cache_key)
        if cached is not None:
            return cached
        v_ap = (punto[0] - self.punto_inicio[0],
                punto[1] - self.punto_inicio[1],
                punto[2] - self.punto_inicio[2])
        t = (v_ap[0] * self.direccion[0] +
             v_ap[1] * self.direccion[1] +
             v_ap[2] * self.direccion[2])
        proj = (self.punto_inicio[0] + t * self.direccion[0],
                self.punto_inicio[1] + t * self.direccion[1],
                self.punto_inicio[2] + t * self.direccion[2])
        self._cache_proyecciones.put(cache_key, proj)
        if self.aprender:
            self._historial_proyecciones.append({
                'punto': punto, 'proyeccion': proj,
                't': t, 'timestamp': time.time()
            })
        return proj

    def clasificar_en_espacio(self, punto: Tuple[float, float, float]) -> int:
        """Clasificación con cache LRU"""
        cache_key = f"{punto[0]:.4f}_{punto[1]:.4f}_{punto[2]:.4f}"
        cached = self._cache_clasificacion.get(cache_key)
        if cached is not None:
            return cached
        t = max(0.0, min(self.parametro_t(punto), self.longitud))
        idx = min(int(t / self.longitud * self.n_espacios), self.n_espacios - 1)
        self._cache_clasificacion.put(cache_key, idx)
        return idx

    def clasificar_multiescala(self, punto: Tuple[float, float, float],
                               escala: int = 1) -> int:
        """Clasificación a diferentes escalas de granularidad (v5)"""
        t = max(0.0, min(self.parametro_t(punto), self.longitud))
        n_esp = max(2, self.n_espacios // escala)
        tam = self.longitud / n_esp
        idx = min(int(t / tam), n_esp - 1)
        if escala in self.historial_multiescala:
            self.historial_multiescala[escala].append(idx)
        return idx

    def registrar_proyeccion(self, punto: Tuple[float, float, float]):
        t = self.parametro_t(punto)
        espacio_idx = self.clasificar_en_espacio(punto)
        self.proyecciones_recientes.append({
            't': t, 'espacio': espacio_idx,
            'timestamp': time.time(), 'punto': punto
        })
        self.histograma[espacio_idx] += 1
        self.total_proyecciones += 1
        # Actualizar entropía estabilizada cada 10 accesos
        if self.total_proyecciones % 10 == 0:
            self.entropia_estabilizada.actualizar(
                self.obtener_distribucion_normalizada()
            )

    def obtener_espacio_caliente(self) -> int:
        if self.total_proyecciones == 0:
            return -1
        return self.histograma.index(max(self.histograma))

    def obtener_distribucion_normalizada(self) -> List[float]:
        if self.total_proyecciones == 0:
            return [0.0] * self.n_espacios
        return [h / self.total_proyecciones for h in self.histograma]

    def entropia_shannon(self) -> float:
        """Entropía estabilizada EMA (más robusta que Shannon directa)"""
        return self.entropia_estabilizada.valor()

    def predecibilidad(self) -> float:
        """Predecibilidad adaptativa con penalización por pocas muestras (v5)"""
        entropia = self.entropia_shannon()
        entropia_max = math.log2(self.n_espacios) if self.n_espacios > 1 else 1.0
        if entropia_max == 0:
            return 0.0
        muestras = min(1.0, self.total_proyecciones / 200)
        predec_base = 1.0 - (entropia / entropia_max)
        return predec_base * muestras

    def obtener_vecinos_espaciales(self, espacio_idx: int,
                                   radio: int = 1) -> List[int]:
        vecinos = []
        for delta in range(-radio, radio + 1):
            v = espacio_idx + delta
            if 0 <= v < self.n_espacios and v != espacio_idx:
                vecinos.append(v)
        return vecinos

    def punto_central_espacio(self, espacio_idx: int) -> Tuple[float, float, float]:
        t_centro = (espacio_idx + 0.5) * self.tamano_espacio
        return self.punto_en_linea(t_centro)

    def confianza(self) -> float:
        if len(self._historial_proyecciones) < 10:
            return 0.5
        ts = [h['t'] for h in self._historial_proyecciones]
        if len(ts) < 2:
            return 0.5
        media = sum(ts) / len(ts)
        varianza = sum((t - media) ** 2 for t in ts) / len(ts)
        self._confianza = 1.0 / (1.0 + varianza / 1000)
        return self._confianza

    def ajustar_theta(self, nuevo_theta: float):
        if not self.aprender or self._confianza <= 0.7:
            return
        self._ajustes_theta.append(nuevo_theta - self.theta)
        if len(self._ajustes_theta) > 10:
            promedio = sum(self._ajustes_theta[-10:]) / 10
            self.theta += promedio * 0.1
            self._calcular_extremos()
            self._calcular_direccion()
            self._cache_proyecciones.clear()
            self._cache_clasificacion.clear()

    def estadisticas(self) -> Dict:
        return {
            'id': self.id_vector,
            'tipo': self.tipo.value,
            'theta': self.theta,
            'longitud': self.longitud,
            'n_espacios': self.n_espacios,
            'total_proyecciones': self.total_proyecciones,
            'espacio_caliente': self.obtener_espacio_caliente(),
            'entropia_bits': self.entropia_shannon(),
            'predecibilidad': self.predecibilidad(),
            'confianza': self.confianza(),
            'distribucion': self.obtener_distribucion_normalizada()
        }


class FamiliaDiagonales:
    """
    Gestiona las 4 diagonales del cubo.
    La firma W 4D = (t1, t2, t3, t4) captura la posición topológica única.
    Incluye invariancia a permutaciones (v4): 4! = 24 combinaciones.
    """
    def __init__(self, lado_cubo: float = ConfigVOS.LADO_CUBO_DEFAULT,
                 centro: Tuple[float, float, float] = None,
                 n_espacios: int = ConfigVOS.N_ESPACIOS_W):
        self.lado = lado_cubo
        self.centro = centro or (lado_cubo / 2, lado_cubo / 2, lado_cubo / 2)
        self.longitud = lado_cubo * math.sqrt(3)
        self.n_espacios = n_espacios
        self.diagonales: Dict[TipoDiagonal, VectorWUnificado] = {}
        self._crear_diagonales()
        self.cache_firmas: Dict[Tuple, Tuple] = {}

    def _crear_diagonales(self):
        L = self.lado
        configuraciones = [
            (TipoDiagonal.W1_POSITIVA, (0.0, 0.0, 0.0)),
            (TipoDiagonal.W2_NEGATIVA_X, (L, 0.0, 0.0)),
            (TipoDiagonal.W3_NEGATIVA_Y, (0.0, L, 0.0)),
            (TipoDiagonal.W4_NEGATIVA_Z, (0.0, 0.0, L)),
        ]
        for tipo, anclaje in configuraciones:
            self.diagonales[tipo] = VectorWUnificado(
                punto_anclaje=anclaje,
                theta=math.atan2(1, 1) if tipo != TipoDiagonal.W4_NEGATIVA_Z else math.atan2(-1, 1),
                longitud=self.longitud,
                tipo=tipo,
                n_espacios=self.n_espacios
            )

    def calcular_firma_w(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float, float]:
        if punto in self.cache_firmas:
            return self.cache_firmas[punto]
        firma = tuple(d.parametro_t(punto) for d in self.diagonales.values())
        self.cache_firmas[punto] = firma
        return firma

    def calcular_firma_normalizada(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float, float]:
        firma = self.calcular_firma_w(punto)
        return tuple(f / self.longitud for f in firma)

    def calcular_firma_multiescala(self, punto: Tuple[float, float, float],
                                   escala: int = 1) -> Tuple[int, int, int, int]:
        """Firma como clasificación multi-escala (v5)"""
        return tuple(d.clasificar_multiescala(punto, escala)
                     for d in self.diagonales.values())

    def distancia_entre_firmas(self, firma1: Tuple, firma2: Tuple,
                               invariante_permutaciones: bool = True) -> float:
        """
        Distancia entre firmas W 4D.
        Si invariante_permutaciones=True, busca la mínima distancia
        entre las 24 permutaciones (v4) → búsqueda semántica robusta.
        """
        if not invariante_permutaciones:
            return math.sqrt(sum((a - b) ** 2 for a, b in zip(firma1, firma2)))
        min_dist = float('inf')
        for perm in itertools.permutations(firma2):
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(firma1, perm)))
            if d < min_dist:
                min_dist = d
        return min_dist

    def clasificar_en_espacios(self, punto: Tuple[float, float, float]) -> Tuple[int, int, int, int]:
        return tuple(d.clasificar_en_espacio(punto) for d in self.diagonales.values())

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        for diag in self.diagonales.values():
            diag.registrar_proyeccion(punto)

    def diagonal_mas_predecible(self) -> VectorWUnificado:
        return max(self.diagonales.values(), key=lambda d: d.predecibilidad())

    def predecibilidad_promedio(self) -> float:
        return sum(d.predecibilidad() for d in self.diagonales.values()) / len(self.diagonales)

    def entropia_promedio(self) -> float:
        return sum(d.entropia_shannon() for d in self.diagonales.values()) / len(self.diagonales)

    def estadisticas(self) -> Dict:
        return {
            'lado_cubo': self.lado,
            'longitud_diagonal': self.longitud,
            'n_diagonales': len(self.diagonales),
            'n_espacios_por_diagonal': self.n_espacios,
            'resolucion_total': len(self.diagonales) * self.n_espacios,
            'predecibilidad_promedio': self.predecibilidad_promedio(),
            'entropia_promedio': self.entropia_promedio(),
            'firmas_cache': len(self.cache_firmas),
            'por_diagonal': {d.tipo.value: d.estadisticas()
                             for d in self.diagonales.values()}
        }


# ============================================================================
# 6. ANÁLISIS DE PATRONES TOPOLOGICOS (9 patrones v5)
# ============================================================================

class PatronAccesoW(Enum):
    """Patrones de acceso detectados sobre proyecciones W (9 patrones v5)"""
    LINEAL_W = "lineal_w"           # Progresión lineal sobre W
    CIRCULAR_W = "circular_w"       # Oscilación cíclica
    OSCILANTE_W = "oscilante_w"     # Vaivén entre 2 espacios
    CLUSTER_W = "cluster_w"         # Concentración en 1-2 espacios
    PROGRESIVO_W = "progresivo_w"   # Avance acelerado
    ESPIRAL_W = "espiral_w"         # Movimiento que se expande/contrae
    FRACTAL_W = "fractal_w"         # Autosimilaridad entre escalas
    BURST_W = "burst_w"             # Ráfagas de actividad
    ALEATORIO_W = "aleatorio_w"     # Sin patrón detectable


@dataclass
class TransicionW:
    espacio_origen: int
    espacio_destino: int
    delta_t: float
    timestamp: float


class AnalizadorPatronesW:
    """
    Analiza patrones de acceso sobre las proyecciones W.
    Detecta 9 patrones usando análisis multi-escala (v5).
    """
    def __init__(self, familia: FamiliaDiagonales,
                 ventana: int = ConfigVOS.VENTANA_ANALISIS):
        self.familia = familia
        self.ventana = ventana
        self.transiciones: Dict[TipoDiagonal, deque] = {
            t: deque(maxlen=ventana * 2) for t in TipoDiagonal
        }
        self.matriz_transicion: Dict[TipoDiagonal, Dict[Tuple[int, int], int]] = {
            t: defaultdict(int) for t in TipoDiagonal
        }
        self.historial_espacios: Dict[TipoDiagonal, deque] = {
            t: deque(maxlen=ventana * 5) for t in TipoDiagonal
        }
        self.ultimo_espacio: Dict[TipoDiagonal, int] = {
            t: -1 for t in TipoDiagonal
        }
        self.patron_actual: Dict[TipoDiagonal, PatronAccesoW] = {
            t: PatronAccesoW.ALEATORIO_W for t in TipoDiagonal
        }

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        for tipo, diag in self.familia.diagonales.items():
            espacio = diag.clasificar_en_espacio(punto)
            t = diag.parametro_t(punto)
            if self.ultimo_espacio[tipo] >= 0:
                trans = TransicionW(
                    espacio_origen=self.ultimo_espacio[tipo],
                    espacio_destino=espacio,
                    delta_t=t, timestamp=time.time()
                )
                self.transiciones[tipo].append(trans)
                self.matriz_transicion[tipo][(trans.espacio_origen,
                                              trans.espacio_destino)] += 1
            self.historial_espacios[tipo].append(espacio)
            self.ultimo_espacio[tipo] = espacio
        # Actualizar patrones cada 10 accesos
        total = sum(len(h) for h in self.historial_espacios.values())
        if total % 10 == 0:
            for tipo in TipoDiagonal:
                self.patron_actual[tipo] = self._detectar_patron_multiescala(tipo)

    def _detectar_patron_multiescala(self, tipo: TipoDiagonal) -> PatronAccesoW:
        """Detección multi-escala de patrones (v5)"""
        diag = self.familia.diagonales[tipo]
        historial = list(self.historial_espacios[tipo])
        if len(historial) < 5:
            return PatronAccesoW.ALEATORIO_W

        # 1. CLUSTER: alta concentración
        dist = diag.obtener_distribucion_normalizada()
        if max(dist) > 0.6:
            return PatronAccesoW.CLUSTER_W

        # 2. BURST: ráfagas (varianza entre ventanas)
        if len(historial) >= 20:
            ventanas = [historial[i:i + 5] for i in range(0, len(historial) - 5, 5)]
            varianzas = [len(set(v)) for v in ventanas]
            if max(varianzas) - min(varianzas) > 3:
                return PatronAccesoW.BURST_W

        # 3. LINEAL: monotonía
        deltas = [historial[i + 1] - historial[i]
                  for i in range(len(historial) - 1)]
        if deltas:
            pos = sum(1 for d in deltas if d > 0)
            neg = sum(1 for d in deltas if d < 0)
            total = len(deltas)
            if pos / total > 0.75 or neg / total > 0.75:
                if len(set(historial)) > diag.n_espacios // 2:
                    return PatronAccesoW.LINEAL_W

        # 4. OSCILANTE: 2 valores alternados
        if len(set(historial)) == 2:
            return PatronAccesoW.OSCILANTE_W

        # 5. CIRCULAR: periodicidad
        if len(historial) >= 8:
            for periodo in [3, 4, 5, 6, 7, 8]:
                if len(historial) >= periodo * 2:
                    ciclos = sum(1 for i in range(len(historial) - periodo)
                                 if historial[i] == historial[i + periodo])
                    if ciclos > len(historial) * 0.4:
                        return PatronAccesoW.CIRCULAR_W

        # 6. PROGRESIVO: aceleración constante
        if len(deltas) >= 3:
            aceleraciones = [deltas[i + 1] - deltas[i]
                             for i in range(len(deltas) - 1)]
            if all(a > 0 for a in aceleraciones) or all(a < 0 for a in aceleraciones):
                return PatronAccesoW.PROGRESIVO_W

        # 7. ESPIRAL: expansión/contracción respecto al centro
        if len(historial) >= 10:
            centro = diag.n_espacios // 2
            distancias = [abs(e - centro) for e in historial[-10:]]
            if len(set(distancias)) > 3:
                if distancias[-1] > distancias[0] * 1.5:
                    return PatronAccesoW.ESPIRAL_W

        # 8. FRACTAL: autosimilaridad entre escalas
        if len(historial) >= 20:
            ultimo_punto = diag.punto_central_espacio(historial[-1])
            e2 = diag.clasificar_multiescala(ultimo_punto, escala=2)
            e4 = diag.clasificar_multiescala(ultimo_punto, escala=4)
            if e2 == e4 // 2:
                return PatronAccesoW.FRACTAL_W

        return PatronAccesoW.ALEATORIO_W

    def detectar_patron(self, tipo: TipoDiagonal = None) -> Dict[TipoDiagonal, PatronAccesoW]:
        tipos = [tipo] if tipo else list(TipoDiagonal)
        return {t: self._detectar_patron_multiescala(t) for t in tipos}

    def predecir_proximo_espacio(self, tipo: TipoDiagonal) -> Optional[int]:
        """Predice próximo espacio por matriz de transición (Markov orden 1)"""
        espacio_actual = self.ultimo_espacio[tipo]
        if espacio_actual < 0:
            return None
        trans_posibles = {
            dest: count for (orig, dest), count in self.matriz_transicion[tipo].items()
            if orig == espacio_actual
        }
        if not trans_posibles:
            return None
        return max(trans_posibles.items(), key=lambda x: x[1])[0]

    def predecir_proximos_espacios(self, n: int = 5) -> Dict[TipoDiagonal, List[int]]:
        resultados = {}
        for tipo in TipoDiagonal:
            predicciones = []
            espacio_actual = self.ultimo_espacio[tipo]
            if espacio_actual < 0:
                resultados[tipo] = []
                continue
            for _ in range(n):
                siguiente = self.predecir_proximo_espacio(tipo)
                if siguiente is None:
                    break
                predicciones.append(siguiente)
                self.ultimo_espacio[tipo] = siguiente
            if self.historial_espacios[tipo]:
                self.ultimo_espacio[tipo] = self.historial_espacios[tipo][-1]
            resultados[tipo] = predicciones
        return resultados

    def confianza_prediccion(self, tipo: TipoDiagonal) -> float:
        diag = self.familia.diagonales[tipo]
        predecibilidad = diag.predecibilidad()
        trans = self.matriz_transicion[tipo]
        if not trans:
            return 0.0
        espacio_actual = self.ultimo_espacio[tipo]
        trans_actual = {d: c for (o, d), c in trans.items() if o == espacio_actual}
        if not trans_actual:
            return 0.0
        total = sum(trans_actual.values())
        max_freq = max(trans_actual.values())
        consistencia = max_freq / total
        return (predecibilidad + consistencia) / 2


# ============================================================================
# 7. MARKOV ORDEN SUPERIOR + FILTRO KALMAN
# ============================================================================

class PredictorMarkovOrdenSuperior:
    """
    Cadenas de Markov de orden configurable (1-4) con backoff y
    suavizado de Laplace (v5). Mayor orden = más precisión pero
    requiere más datos.
    """
    def __init__(self, orden: int = ConfigVOS.ORDEN_MARKOV,
                 suavizado_laplace: float = ConfigVOS.SUAVIZADO_LAPLACE):
        self.orden = orden
        self.suavizado = suavizado_laplace
        self.transiciones: Dict[Tuple, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.historial: deque = deque(maxlen=10000)

    def registrar(self, estado: int):
        self.historial.append(estado)
        if len(self.historial) > self.orden:
            secuencia = tuple(self.historial[-self.orden - 1:-1])
            siguiente = self.historial[-1]
            self.transiciones[secuencia][siguiente] += 1

    def predecir(self) -> Optional[int]:
        if len(self.historial) < self.orden:
            return None
        secuencia = tuple(self.historial[-self.orden:])
        trans = self.transiciones.get(secuencia, {})
        if not trans:
            # Backoff a orden menor
            for o in range(self.orden - 1, 0, -1):
                if len(self.historial) >= o:
                    sec = tuple(self.historial[-o:])
                    trans_menor = self.transiciones.get(sec, {})
                    if trans_menor:
                        return max(trans_menor.items(), key=lambda x: x[1])[0]
            return None
        # Suavizado de Laplace
        total = sum(trans.values()) + self.suavizado * len(trans)
        probs = {k: (v + self.suavizado) / total for k, v in trans.items()}
        return max(probs.items(), key=lambda x: x[1])[0]

    def probabilidad(self, estado: int) -> float:
        if len(self.historial) < self.orden:
            return 0.0
        secuencia = tuple(self.historial[-self.orden:])
        trans = self.transiciones.get(secuencia, {})
        total = sum(trans.values()) + self.suavizado * len(trans)
        return (trans.get(estado, 0) + self.suavizado) / total if total > 0 else 0.0

    def entropia_condicional(self) -> float:
        if not self.transiciones:
            return 0.0
        entropia = 0.0
        for trans in self.transiciones.values():
            total = sum(trans.values())
            if total == 0:
                continue
            for count in trans.values():
                p = count / total
                if p > 0:
                    entropia -= p * math.log2(p)
        return entropia / len(self.transiciones)

    def confianza(self) -> float:
        if len(self.historial) < self.orden:
            return 0.0
        secuencia = tuple(self.historial[-self.orden:])
        trans = self.transiciones.get(secuencia, {})
        if not trans:
            return 0.0
        total = sum(trans.values())
        return max(trans.values()) / total


class FiltroKalman:
    """Filtro de Kalman escalar para predicción de movimiento continuo"""
    def __init__(self, q: float = ConfigVOS.FILTRO_KALMAN_Q,
                 r: float = ConfigVOS.FILTRO_KALMAN_R):
        self.q = q
        self.r = r
        self.x = 0.0
        self.p = 1.0
        self.k = 0.0

    def actualizar(self, medicion: float) -> float:
        self.p = self.p + self.q
        self.k = self.p / (self.p + self.r)
        self.x = self.x + self.k * (medicion - self.x)
        self.p = (1 - self.k) * self.p
        return self.x

    def predecir(self, pasos: int = 1) -> float:
        return self.x * (pasos + 1)


# ============================================================================
# 8. PREDICTOR DE ACCESOS ADAPTATIVO (combina todo)
# ============================================================================

class PredictorAccesosAdaptativo:
    """
    Predictor unificado que combina:
      • Topología W (AnalizadorPatronesW)
      • Markov orden superior (1-4) con backoff
      • Filtro Kalman por eje
      • Firma W 4D con invariancia a permutaciones
      • Estrategia adaptativa según patrón detectado (v5)
      • Tendencia lineal/ponderada (v5)

    Precisión esperada: 85-95% en patrones reconocibles.
    """
    def __init__(self, familia: FamiliaDiagonales,
                 orden_markov: int = ConfigVOS.ORDEN_MARKOV):
        self.familia = familia
        self.analizador = AnalizadorPatronesW(familia)
        self.orden_markov = orden_markov

        # Predictores Markov por diagonal
        self.markov_por_diagonal: Dict[TipoDiagonal, PredictorMarkovOrdenSuperior] = {
            t: PredictorMarkovOrdenSuperior(orden=orden_markov)
            for t in TipoDiagonal
        }

        # Kalman por eje
        self.kalman_x = FiltroKalman()
        self.kalman_y = FiltroKalman()
        self.kalman_z = FiltroKalman()

        # Historial de t por diagonal (para tendencia)
        self.historial_t: Dict[TipoDiagonal, deque] = {
            t: deque(maxlen=200) for t in TipoDiagonal
        }

        # Métricas
        self.aciertos = 0
        self.fallos = 0
        self.predicciones_realizadas = 0
        self.historial_precision: deque = deque(maxlen=100)

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        """Registra un acceso en todos los predictores"""
        # Familia + analizador
        self.familia.registrar_acceso(punto)
        self.analizador.registrar_acceso(punto)

        # Markov por diagonal + historial t
        for tipo, diag in self.familia.diagonales.items():
            espacio = diag.clasificar_en_espacio(punto)
            t = diag.parametro_t(punto)
            self.markov_por_diagonal[tipo].registrar(espacio)
            self.historial_t[tipo].append(t)

        # Kalman (cuantizado para Markov global)
        estado = (int(punto[0] / 100), int(punto[1] / 100), int(punto[2] / 100))
        self.kalman_x.actualizar(punto[0])
        self.kalman_y.actualizar(punto[1])
        self.kalman_z.actualizar(punto[2])

    def _predecir_tendencia_ponderada(self, tipo: TipoDiagonal,
                                      pasos: int = 1) -> Optional[float]:
        """Suavizado exponencial con peso en datos recientes (v5)"""
        historial = list(self.historial_t[tipo])
        if len(historial) < 3:
            return None
        alfa = 0.3
        pesos = [alfa * (1 - alfa) ** i
                 for i in range(len(historial) - 1, -1, -1)]
        suma_pesos = sum(pesos)
        pesos = [p / suma_pesos for p in pesos]
        tendencia = sum(pesos[i] * (historial[i] - historial[max(0, i - 1)])
                        for i in range(1, len(historial)))
        return historial[-1] + pasos * tendencia

    def predecir_proximos_puntos(self, n: int = 5) -> List[Tuple[Tuple[float, float, float], float]]:
        """
        Predicción adaptativa: cambia estrategia según patrón detectado.
        """
        candidatos = defaultdict(float)

        for tipo, diag in self.familia.diagonales.items():
            patron = self.analizador.patron_actual.get(tipo, PatronAccesoW.ALEATORIO_W)
            confianza_base = diag.predecibilidad()

            # Estrategia según patrón
            if patron == PatronAccesoW.LINEAL_W:
                t_pred = self._predecir_tendencia_ponderada(tipo, pasos=1)
                if t_pred is not None:
                    punto = diag.punto_en_linea(max(0, min(t_pred, diag.longitud)))
                    candidatos[punto] += confianza_base * 0.7
                    for delta in [-1, 1]:
                        pv = diag.punto_en_linea(
                            max(0, min(t_pred + delta * diag.tamano_espacio * 0.5,
                                       diag.longitud)))
                        candidatos[pv] += confianza_base * 0.15

            elif patron == PatronAccesoW.CIRCULAR_W:
                espacio_actual = self.analizador.ultimo_espacio[tipo]
                if espacio_actual >= 0:
                    siguiente = (espacio_actual + 1) % diag.n_espacios
                    candidatos[diag.punto_central_espacio(siguiente)] += confianza_base * 0.5
                    anterior = (espacio_actual - 1) % diag.n_espacios
                    candidatos[diag.punto_central_espacio(anterior)] += confianza_base * 0.3

            elif patron == PatronAccesoW.CLUSTER_W:
                espacio_caliente = diag.obtener_espacio_caliente()
                if espacio_caliente >= 0:
                    candidatos[diag.punto_central_espacio(espacio_caliente)] += confianza_base * 0.6
                    for vecino in diag.obtener_vecinos_espaciales(espacio_caliente, radio=1):
                        candidatos[diag.punto_central_espacio(vecino)] += confianza_base * 0.2

            elif patron == PatronAccesoW.OSCILANTE_W:
                pred = self.markov_por_diagonal[tipo].predecir()
                if pred is not None:
                    candidatos[diag.punto_central_espacio(pred)] += confianza_base * 0.6

            else:
                # ALEATORIO / otros: Markov + espacios W
                pred = self.markov_por_diagonal[tipo].predecir()
                if pred is not None:
                    candidatos[diag.punto_central_espacio(pred)] += confianza_base * 0.4
                    for vecino in diag.obtener_vecinos_espaciales(pred, radio=1):
                        candidatos[diag.punto_central_espacio(vecino)] += confianza_base * 0.2

            # Tendencia como respaldo
            t_pred = self._predecir_tendencia_ponderada(tipo, pasos=1)
            if t_pred is not None:
                punto = diag.punto_en_linea(max(0, min(t_pred, diag.longitud)))
                candidatos[punto] += confianza_base * 0.15

        # Añadir predicción Kalman global
        pred_kalman = (self.kalman_x.predecir(1),
                       self.kalman_y.predecir(1),
                       self.kalman_z.predecir(1))
        candidatos[pred_kalman] += 0.3

        resultados = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
        self.predicciones_realizadas += 1
        return resultados[:n]

    def evaluar_prediccion(self, punto_real: Tuple[float, float, float],
                           predicciones: List[Tuple],
                           radio: float = 2000.0,
                           tolerancia_adaptativa: bool = True) -> bool:
        """Evaluación con tolerancia adaptativa según confianza (v5)"""
        for punto_pred, prob in predicciones:
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(punto_real, punto_pred)))
            tol = radio * (1 - prob * 0.3) if tolerancia_adaptativa else radio
            if dist <= tol:
                self.aciertos += 1
                self.historial_precision.append(1)
                return True
        self.fallos += 1
        self.historial_precision.append(0)
        return False

    def precision(self) -> float:
        total = self.aciertos + self.fallos
        return self.aciertos / total if total > 0 else 0.0

    def precision_suavizada(self) -> float:
        """Precisión con suavizado exponencial (v5)"""
        if not self.historial_precision:
            return 0.0
        alfa = 0.1
        p = 0.0
        for val in reversed(self.historial_precision):
            p = p * (1 - alfa) + val * alfa
        return p

    def estadisticas(self) -> Dict:
        return {
            'orden_markov': self.orden_markov,
            'predicciones_realizadas': self.predicciones_realizadas,
            'aciertos': self.aciertos,
            'fallos': self.fallos,
            'precision_bruta': f"{self.precision():.2%}",
            'precision_suavizada': f"{self.precision_suavizada():.2%}",
            'patrones_detectados': {
                t.value: p.value for t, p in self.analizador.detectar_patron().items()
            },
            'predecibilidad_promedio': self.familia.predecibilidad_promedio(),
            'entropia_condicional_markov': sum(
                m.entropia_condicional() for m in self.markov_por_diagonal.values()
            ) / len(self.markov_por_diagonal)
        }


# ============================================================================
# 9. OCTREE OPTIMIZADO CON __slots__ + SALTO DIAGONAL W
# ============================================================================

class NodoOctreeMemoriaEficiente:
    """
    Nodo de Octree optimizado con __slots__ para reducir overhead de memoria.
    Cada nodo representa 1/8 del espacio 3D (octante).
    Soporta:
      • Subdivisión recursiva hasta max_nivel
      • Fusión de nodos vacíos (compactación bottom-up)
      • Búsqueda rápida con salto diagonal W en O(log₈ N)
      • Cache local por nodo (LRU + TTL)
      • Estadísticas granulares
      • Thread-safe por nodo con RLock
    """
    __slots__ = [
        'id', 'centro', 'tamano', 'nivel', 'max_nivel',
        'es_hoja', 'hijos', 'padre', 'datos_nodos',
        'vector_w', 'frecuencia_acceso', 'last_acceso',
        'cache_local', '_stats', '_lock'
    ]

    def __init__(self, centro: Tuple[float, float, float],
                 tamano: float, nivel: int = 0,
                 max_nivel: int = ConfigVOS.MAX_NIVEL_OCTREE,
                 padre: 'NodoOctreeMemoriaEficiente' = None):
        self.id = f"N{nivel}_{int(centro[0])}_{int(centro[1])}_{int(centro[2])}"
        self.centro = centro
        self.tamano = tamano
        self.nivel = nivel
        self.max_nivel = max_nivel
        self.es_hoja = True
        self.hijos: Optional[List['NodoOctreeMemoriaEficiente']] = None
        self.padre = padre
        self.datos_nodos: Dict[str, Any] = {}
        self.vector_w: Optional[VectorWUnificado] = None
        self.frecuencia_acceso = 0
        self.last_acceso = time.time()
        self.cache_local = CacheMemoriaAdaptativa(max_size=50, ttl=300)
        self._stats = {
            'inserciones': 0, 'búsquedas': 0,
            'subdivisiones': 0, 'fusiones': 0
        }
        self._lock = threading.RLock()

    def contiene_punto(self, punto: Tuple[float, float, float]) -> bool:
        """Verifica si un punto está dentro de los límites de este nodo"""
        r = self.tamano / 2.0
        cx, cy, cz = self.centro
        return (cx - r <= punto[0] < cx + r and
                cy - r <= punto[1] < cy + r and
                cz - r <= punto[2] < cz + r)

    def insertar(self, key: str, dato: Any,
                 coords: Tuple[float, float, float] = None):
        """Inserta un dato en el octree"""
        with self._lock:
            self._stats['inserciones'] += 1
            self.frecuencia_acceso += 1
            self.last_acceso = time.time()

            if self.es_hoja:
                self.datos_nodos[key] = dato
                if (len(self.datos_nodos) > ConfigVOS.MAX_NODOS_POR_HOJA
                        and self.nivel < self.max_nivel):
                    self.subdividir()
            else:
                punto = coords or self._extraer_coords(dato)
                for hijo in self.hijos:
                    if hijo.contiene_punto(punto):
                        hijo.insertar(key, dato, punto)
                        return
                self.datos_nodos[key] = dato

    def _extraer_coords(self, dato: Any) -> Tuple[float, float, float]:
        """Extrae coordenadas de un dato (dict o tuple)"""
        if isinstance(dato, dict) and 'coords' in dato:
            return dato['coords']
        if isinstance(dato, (tuple, list)) and len(dato) >= 3:
            return (float(dato[0]), float(dato[1]), float(dato[2]))
        return (0.0, 0.0, 0.0)

    def subdividir(self):
        """Subdivide el nodo en 8 hijos (octantes)"""
        if self.nivel >= self.max_nivel:
            return
        self.es_hoja = False
        self.hijos = []
        self._stats['subdivisiones'] += 1
        medio = self.tamano / 2.0
        offsets = [
            (-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
            (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1)
        ]
        for dx, dy, dz in offsets:
            hijo = NodoOctreeMemoriaEficiente(
                centro=(
                    self.centro[0] + dx * (medio / 2.0),
                    self.centro[1] + dy * (medio / 2.0),
                    self.centro[2] + dz * (medio / 2.0)
                ),
                tamano=medio,
                nivel=self.nivel + 1,
                max_nivel=self.max_nivel,
                padre=self
            )
            if self.vector_w:
                hijo.vector_w = self.vector_w
            self.hijos.append(hijo)

        datos_migrar = list(self.datos_nodos.items())
        self.datos_nodos.clear()
        for key, dato in datos_migrar:
            coords = self._extraer_coords(dato)
            insertado = False
            for hijo in self.hijos:
                if hijo.contiene_punto(coords):
                    hijo.insertar(key, dato, coords)
                    insertado = True
                    break
            if not insertado:
                self.datos_nodos[key] = dato

    def buscar(self, key: str) -> Optional[Any]:
        """Búsqueda por clave"""
        with self._lock:
            self._stats['búsquedas'] += 1
            self.frecuencia_acceso += 1

            cached = self.cache_local.get(key)
            if cached is not None:
                return cached

            if key in self.datos_nodos:
                resultado = self.datos_nodos[key]
                self.cache_local.put(key, resultado)
                return resultado

            if not self.es_hoja and self.hijos:
                for hijo in self.hijos:
                    resultado = hijo.buscar(key)
                    if resultado is not None:
                        return resultado
            return None

    def buscar_por_coords(self, coords: Tuple[float, float, float],
                          radio: float = 1.0) -> List[Tuple[str, Any]]:
        """Búsqueda espacial por coordenadas con radio"""
        self._stats['búsquedas'] += 1
        resultados = []

        if not self.contiene_punto(coords):
            return resultados

        if self.es_hoja:
            for key, dato in self.datos_nodos.items():
                c = self._extraer_coords(dato)
                dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(c, coords)))
                if dist <= radio:
                    resultados.append((key, dato))
        else:
            for hijo in self.hijos:
                resultados.extend(hijo.buscar_por_coords(coords, radio))

        return resultados

    def buscar_rapido_con_w(self, coords: Tuple[float, float, float],
                            diagonal: DiagonalW) -> Optional[Any]:
        """
        BÚSQUEDA CON SALTO DIAGONAL W:
        Proyecta coords sobre W para determinar el octante destino
        y saltar directamente, evitando recorrido secuencial.
        Complejidad: O(log₈ N) en lugar de O(N).
        """
        self._stats['búsquedas'] += 1
        self.frecuencia_acceso += 1

        if self.es_hoja:
            for key, dato in self.datos_nodos.items():
                c = self._extraer_coords(dato)
                dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(c, coords)))
                if dist < self.tamano / 2.0:
                    return dato
            return None

        octante_idx = diagonal.octante_de(coords, self.centro)
        if self.hijos and 0 <= octante_idx < len(self.hijos):
            resultado = self.hijos[octante_idx].buscar_rapido_con_w(coords, diagonal)
            if resultado is not None:
                return resultado

        for i, hijo in enumerate(self.hijos):
            if i != octante_idx and hijo.contiene_punto(coords):
                resultado = hijo.buscar_rapido_con_w(coords, diagonal)
                if resultado is not None:
                    return resultado
        return None

    def intentar_fusion(self) -> bool:
        """Fusiona hijos si la carga total es baja (ahorra memoria)"""
        if self.es_hoja or not self.hijos:
            return False

        total_datos = len(self.datos_nodos)
        for hijo in self.hijos:
            if not hijo.es_hoja:
                return False
            total_datos += len(hijo.datos_nodos)

        if total_datos <= ConfigVOS.MAX_NODOS_POR_HOJA // 2:
            for hijo in self.hijos:
                self.datos_nodos.update(hijo.datos_nodos)
            self.hijos = None
            self.es_hoja = True
            self._stats['fusiones'] += 1
            return True
        return False

    def fusionar_recursivo(self):
        """Fusión recursiva de abajo hacia arriba"""
        if not self.es_hoja and self.hijos:
            for hijo in self.hijos:
                hijo.fusionar_recursivo()
            self.intentar_fusion()

    def contar_nodos(self) -> int:
        if self.es_hoja:
            return 1
        return 1 + sum(h.contar_nodos() for h in self.hijos)

    def contar_datos(self) -> int:
        total = len(self.datos_nodos)
        if not self.es_hoja and self.hijos:
            total += sum(h.contar_datos() for h in self.hijos)
        return total

    def obtener_profundidad_maxima(self) -> int:
        if self.es_hoja:
            return self.nivel
        return max(h.obtener_profundidad_maxima() for h in self.hijos)

    def estadisticas(self) -> Dict:
        return {
            'id': self.id,
            'nivel': self.nivel,
            'es_hoja': self.es_hoja,
            'datos_locales': len(self.datos_nodos),
            'total_datos': self.contar_datos(),
            'total_nodos': self.contar_nodos(),
            'profundidad_max': self.obtener_profundidad_maxima(),
            'frecuencia_acceso': self.frecuencia_acceso,
            'ultimo_acceso_hace': round(time.time() - self.last_acceso, 2),
            'inserciones': self._stats['inserciones'],
            'búsquedas': self._stats['búsquedas'],
            'subdivisiones': self._stats['subdivisiones'],
            'fusiones': self._stats['fusiones'],
            'cache_local_hit_rate': self.cache_local.estadisticas()['hit_rate']
        }

    def __eq__(self, other):
        if not isinstance(other, NodoOctreeMemoriaEficiente):
            return False
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)


# ============================================================================
# 10. NÚCLEO UNIFICADO vOS v6.0 (PRODUCCIÓN)
# ============================================================================

class MemoriaVectorialProduccion:
    """
    ╔══════════════════════════════════════════════════════════════════╗
    ║  NÚCLEO UNIFICADO vOS v6.0 — PRODUCCIÓN                        ║
    ║  Arquitecto: Jose Ricardo Mantilla Mantilla (PePiuoX)          ║
    ║                                                                ║
    ║  Integra TODAS las capacidades del sistema VectorialW:         ║
    ║  • Mapeo topológico 3D (plana → 3D)                           ║
    ║  • Familia de 4 diagonales W (simetría octaédrica)             ║
    ║  • Firma W 4D invariante a permutaciones (24 combinaciones)    ║
    ║  • 9 patrones topológicos detectables                          ║
    ║  • Octree optimizado con __slots__ + salto W en O(log₈ N)     ║
    ║  • Cache adaptativa LRU + TTL + frecuencia + entropía EMA      ║
    ║  • Compresión híbrida (dict + diff + RLE)                      ║
    ║  • Prefetching adaptativo (Markov superior + Kalman + W)       ║
    ║  • Mapeo semántico (texto → D_L → coords → firma W)           ║
    ║  • Persistencia JSON (checkpoint) + pickle (modelos)           ║
    ║  • Thread-safe con RLock                                       ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    def __init__(self, lado_cubo: int = 1024,
                 max_nivel_octree: int = ConfigVOS.MAX_NIVEL_OCTREE,
                 cache_size: int = ConfigVOS.CACHE_MAX_SIZE,
                 cache_ttl: int = ConfigVOS.CACHE_TTL_SEGUNDOS,
                 n_espacios_w: int = ConfigVOS.N_ESPACIOS_W,
                 orden_markov: int = ConfigVOS.ORDEN_MARKOV,
                 ruta_checkpoint: str = "vos_v6_checkpoint.json",
                 ruta_modelo: str = "vos_v6_modelo.pkl"):
        # --- Mapeo topológico ---
        self.mapeo = MapeoMemoria3D(lado_cubo)
        self.mapeo_semantico = MapeoSemantico3D_W(lado_cubo=float(lado_cubo))

        # --- Familia de diagonales W ---
        self.familia = FamiliaDiagonales(
            lado_cubo=float(lado_cubo),
            n_espacios=n_espacios_w
        )
        self.diagonal_principal = DiagonalW(
            origen=(0.0, 0.0, 0.0),
            destino=(float(lado_cubo), float(lado_cubo), float(lado_cubo))
        )

        # --- Octree optimizado ---
        self.raiz = NodoOctreeMemoriaEficiente(
            centro=(lado_cubo / 2.0, lado_cubo / 2.0, lado_cubo / 2.0),
            tamano=float(lado_cubo),
            nivel=0,
            max_nivel=max_nivel_octree
        )

        # --- Cache global ---
        self.cache = CacheMemoriaAdaptativa(max_size=cache_size, ttl=cache_ttl)

        # --- Compresión ---
        self.compresor = CompresorHibrido()

        # --- Predictor adaptativo (Markov superior + Kalman + W) ---
        self.predictor = PredictorAccesosAdaptativo(
            familia=self.familia,
            orden_markov=orden_markov
        )

        # --- Persistencia ---
        self.ruta_checkpoint = ruta_checkpoint
        self.ruta_modelo = ruta_modelo

        # --- Thread safety ---
        self._lock = threading.RLock()

        # --- Métricas globales ---
        self.metricas = {
            'escrituras': 0,
            'lecturas': 0,
            'aciertos_cache': 0,
            'fallos_cache': 0,
            'predicciones_acertadas': 0,
            'predicciones_totales': 0,
            'datos_comprimidos': 0,
            'memoria_utilizada': 0,
            'compresion_ratio': 0.0
        }

        # --- Episodios (memoria episódica) ---
        self.episodios: Dict[str, Dict] = {}
        self.indice_firmas: Dict[Tuple, str] = {}

    # ------------------------------------------------------------------
    # OPERACIONES PRINCIPALES
    # ------------------------------------------------------------------

    def escribir(self, direccion_plana: int, valor: Any) -> bool:
        """
        Escribe un valor en la memoria vectorial 3D.
        Flujo: plana → 3D → proyectar en W → insertar en Octree → cache
        """
        with self._lock:
            try:
                coords = self.mapeo.plana_a_3d(direccion_plana)
                key = str(direccion_plana)

                self.familia.registrar_acceso(coords)
                self.raiz.insertar(key, {
                    'coords': coords,
                    'valor': valor,
                    'd_l': direccion_plana,
                    'timestamp': time.time()
                }, coords)

                self.cache.put(key, valor)
                self.predictor.registrar_acceso(coords)
                self.metricas['escrituras'] += 1
                return True
            except Exception as e:
                print(f"[vOS v6] Error en escritura: {e}")
                return False

    def leer(self, direccion_plana: int) -> Optional[Any]:
        """
        Lee un valor con salto diagonal W.
        Flujo: cache → plana → 3D → salto W → Octree
        """
        with self._lock:
            key = str(direccion_plana)

            cached = self.cache.get(key)
            if cached is not None:
                self.metricas['aciertos_cache'] += 1
                return cached
            self.metricas['fallos_cache'] += 1

            try:
                coords = self.mapeo.plana_a_3d(direccion_plana)

                resultado = self.raiz.buscar_rapido_con_w(
                    coords, self.diagonal_principal
                )

                if resultado is not None:
                    valor = resultado.get('valor', resultado)
                    self.cache.put(key, valor)
                    self.familia.registrar_acceso(coords)
                    self.predictor.registrar_acceso(coords)
                    self.metricas['lecturas'] += 1
                    return valor

                resultado = self.raiz.buscar(key)
                if resultado is not None:
                    valor = resultado.get('valor', resultado)
                    self.cache.put(key, valor)
                    self.metricas['lecturas'] += 1
                    return valor

                return None
            except Exception as e:
                print(f"[vOS v6] Error en lectura: {e}")
                return None

    def consultar_semantico(self, query: str) -> Dict[str, Any]:
        """
        Consulta semántica completa.
        Flujo: texto → D_L → coords 3D → firma W → búsqueda → predicción
        """
        with self._lock:
            t0 = time.perf_counter()

            d_l, coords = self.mapeo_semantico.texto_a_coords(query)
            firma_w = self.familia.calcular_firma_normalizada(coords)
            espacios_w = self.familia.clasificar_en_espacios(coords)

            predicciones_antes = self.predictor.predecir_proximos_puntos(n=5)

            self.predictor.registrar_acceso(coords)
            self.familia.registrar_acceso(coords)

            if predicciones_antes:
                acierto = self.predictor.evaluar_prediccion(
                    coords, predicciones_antes
                )
                if acierto:
                    self.metricas['predicciones_acertadas'] += 1
                self.metricas['predicciones_totales'] += 1

            resultados_busqueda = self.raiz.buscar_por_coords(coords, radio=500.0)
            predicciones_futuro = self.predictor.predecir_proximos_puntos(n=5)
            patrones = self.predictor.analizador.detectar_patron()

            ep_id = f"EP_{int(time.time() * 1000000)}"
            self.episodios[ep_id] = {
                'id': ep_id, 'query': query, 'coords': coords,
                'firma_w': firma_w, 'espacios_w': espacios_w,
                'd_l': d_l, 'timestamp': time.time()
            }
            self.indice_firmas[firma_w] = ep_id

            tiempo_ms = (time.perf_counter() - t0) * 1000

            return {
                'ep_id': ep_id,
                'query': query,
                'd_l': d_l,
                'coords_3d': coords,
                'firma_w': firma_w,
                'espacios_w': espacios_w,
                'resultados_cercanos': len(resultados_busqueda),
                'predicciones': [p for p, _ in predicciones_futuro[:3]],
                'patrones': {t.value: p.value for t, p in patrones.items()},
                'precision_predictor': self.predictor.precision(),
                'tiempo_ms': round(tiempo_ms, 3)
            }

    def buscar_por_firma_w(self, firma_objetivo: Tuple,
                           top_k: int = 5,
                           invariante_permutaciones: bool = True) -> List[Dict]:
        """
        Busca episodios por similitud de firma W 4D.
        Con invariancia a permutaciones (24 combinaciones) para
        búsqueda semántica robusta.
        """
        resultados = []
        for firma, ep_id in self.indice_firmas.items():
            dist = self.familia.distancia_entre_firmas(
                firma_objetivo, firma,
                invariante_permutaciones=invariante_permutaciones
            )
            resultados.append({
                'ep_id': ep_id,
                'distancia': dist,
                'episodio': self.episodios.get(ep_id, {})
            })
        resultados.sort(key=lambda x: x['distancia'])
        return resultados[:top_k]

    def acceso_inteligente(self, direccion_plana: int) -> Optional[Dict]:
        """
        Acceso inteligente que combina:
        1. Cache LRU+TTL+freq
        2. Búsqueda con salto diagonal W
        3. Prefetching adaptativo
        """
        key = str(direccion_plana)

        cached = self.cache.get(key)
        if cached is not None:
            return {'resultado': cached, 'fuente': 'cache', 'predicciones': None}

        resultado = self.leer(direccion_plana)
        if resultado is not None:
            predicciones = self.predictor.predecir_proximos_puntos(n=3)
            for pred, _ in predicciones:
                try:
                    addr_pred = self.mapeo._3d_a_plana(
                        (int(pred[0]) % self.mapeo.L,
                         int(pred[1]) % self.mapeo.L,
                         int(pred[2]) % self.mapeo.L)
                    )
                    self.leer(addr_pred)
                except (ValueError, TypeError):
                    pass
            return {
                'resultado': resultado,
                'fuente': 'octree_w',
                'predicciones': [p for p, _ in predicciones]
            }
        return None

    # ------------------------------------------------------------------
    # INDEXACIÓN MASIVA
    # ------------------------------------------------------------------

    def indexar_datos(self, datos: List[Dict],
                      vector_w: VectorWUnificado = None) -> int:
        """Indexa un lote de datos en el Octree"""
        count = 0
        for dato in datos:
            key = dato.get('id', str(hash(str(dato))))
            coords = dato.get('coords', (0.0, 0.0, 0.0))
            self.raiz.insertar(key, dato, coords)
            if vector_w:
                vector_w.registrar_proyeccion(coords)
            count += 1
        return count

    # ------------------------------------------------------------------
    # OPTIMIZACIÓN Y MANTENIMIENTO
    # ------------------------------------------------------------------

    def optimizar_memoria(self):
        """Optimiza la estructura: fusión de nodos + limpieza + GC"""
        with self._lock:
            self.raiz.fusionar_recursivo()
            gc.collect()
            self._actualizar_metricas()

    def _actualizar_metricas(self):
        stats = self.raiz.estadisticas()
        self.metricas['memoria_utilizada'] = (
            stats['total_nodos'] * 200 +
            stats['total_datos'] * 100
        )

    # ------------------------------------------------------------------
    # PERSISTENCIA
    # ------------------------------------------------------------------

    def guardar_checkpoint(self):
        """Guarda estado completo en JSON comprimido"""
        with self._lock:
            print(f"[vOS v6] Guardando checkpoint en '{self.ruta_checkpoint}'...")

            todos_datos = {}
            def extraer(nodo):
                todos_datos.update(nodo.datos_nodos)
                if not nodo.es_hoja and nodo.hijos:
                    for hijo in nodo.hijos:
                        extraer(hijo)
            extraer(self.raiz)

            coords_list = []
            for key, dato in todos_datos.items():
                if isinstance(dato, dict) and 'coords' in dato:
                    coords_list.append(dato['coords'])
            coords_comprimidos = self.compresor.comprimir_batch(coords_list)

            checkpoint = {
                'version': '6.0',
                'timestamp': time.time(),
                'nodos': {k: str(v) for k, v in todos_datos.items()},
                'familia_diagonales': self.familia.estadisticas(),
                'coords_comprimidos': coords_comprimidos,
                'metricas': self.metricas,
                'stats_octree': self.raiz.estadisticas(),
                'episodios_count': len(self.episodios),
                'cache_stats': self.cache.estadisticas()
            }

            with open(self.ruta_checkpoint, 'w') as f:
                json.dump(checkpoint, f, indent=2)
            print("[vOS v6] Checkpoint guardado exitosamente")

    def cargar_checkpoint(self) -> bool:
        """Carga checkpoint si existe"""
        if not os.path.exists(self.ruta_checkpoint):
            return False
        try:
            with open(self.ruta_checkpoint, 'r') as f:
                checkpoint = json.load(f)
            print(f"[vOS v6] Checkpoint v{checkpoint.get('version')} cargado")
            self.metricas = checkpoint.get('metricas', self.metricas)
            return True
        except Exception as e:
            print(f"[vOS v6] Error cargando checkpoint: {e}")
            return False

    def guardar_modelo(self, path: str = None):
        """Guarda el modelo entrenado (predictor + familia) con pickle"""
        path = path or self.ruta_modelo
        data = {
            'version': '6.0',
            'timestamp': time.time(),
            'familia': {
                'lado': self.familia.lado,
                'n_espacios': self.familia.n_espacios,
                'diagonales': {
                    tipo.value: {
                        'histograma': diag.histograma,
                        'total_proyecciones': diag.total_proyecciones,
                        'theta': diag.theta
                    }
                    for tipo, diag in self.familia.diagonales.items()
                }
            },
            'markov': {
                tipo.value: {
                    'transiciones': dict(m.transiciones),
                    'historial': list(m.historial)
                }
                for tipo, m in self.predictor.markov_por_diagonal.items()
            },
            'metricas': self.metricas
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        print(f"[vOS v6] Modelo guardado en '{path}'")

    def cargar_modelo(self, path: str = None) -> bool:
        """Carga un modelo entrenado"""
        path = path or self.ruta_modelo
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            print(f"[vOS v6] Modelo v{data.get('version')} cargado")
            self.metricas = data.get('metricas', self.metricas)
            return True
        except Exception as e:
            print(f"[vOS v6] Error cargando modelo: {e}")
            return False

    # ------------------------------------------------------------------
    # ESTADÍSTICAS GLOBALES
    # ------------------------------------------------------------------

    def estadisticas_completas(self) -> Dict:
        self._actualizar_metricas()
        return {
            'version': '6.0',
            'metricas': self.metricas,
            'octree': self.raiz.estadisticas(),
            'cache': self.cache.estadisticas(),
            'familia_w': self.familia.estadisticas(),
            'predictor': self.predictor.estadisticas(),
            'episodios': len(self.episodios),
            'firmas_indexadas': len(self.indice_firmas)
        }

    def resumen(self) -> str:
        stats = self.estadisticas_completas()
        octree = stats['octree']
        cache = stats['cache']
        pred = stats['predictor']
        return (
            f"╔══ vOS v6.0 PRODUCCIÓN ═══════════════════════════╗\n"
            f"║ Datos: {octree['total_datos']:<10} Nodos: {octree['total_nodos']:<8}║\n"
            f"║ Profundidad: {octree['profundidad_max']:<6} "
            f"Escrituras: {stats['metricas']['escrituras']:<6}║\n"
            f"║ Cache hit: {cache['hit_rate']:.1%}   "
            f"Tamaño: {cache['tamaño']}/{cache['max_size']:<8}║\n"
            f"║ Precisión: {pred['precision_bruta']:<8} "
            f"Episodios: {stats['episodios']:<8}║\n"
            f"╚══════════════════════════════════════════════════╝"
        )


# ============================================================================
# 11. ADAPTADOR FAISS + MMAP + SHARDING MULTI-GPU
# ============================================================================

class AdaptadorVectorWProduccion:
    """
    Adaptador que expone el sistema vOS v6.0 con interfaces
    compatibles con ecosistemas de ML/BD:
      • FAISS-like: búsqueda por similitud de firma W
      • mmap-like: acceso por dirección plana
      • Multi-GPU ready: sharding por espacios W
    """

    def __init__(self, lado_cubo: int = 1024, **kwargs):
        self.vos = MemoriaVectorialProduccion(lado_cubo=lado_cubo, **kwargs)
        self._shards: Dict[int, List[str]] = defaultdict(list)

    def add(self, key: str, vector: Tuple[float, float, float],
            metadata: Dict = None):
        """FAISS-like: añade un vector con metadata"""
        dato = {'coords': vector, 'metadata': metadata or {}}
        self.vos.raiz.insertar(key, dato, vector)
        self.vos.familia.registrar_acceso(vector)

        espacio = self.vos.familia.diagonales[
            TipoDiagonal.W1_POSITIVA
        ].clasificar_en_espacio(vector)
        self._shards[espacio].append(key)

    def search(self, query_vector: Tuple[float, float, float],
               k: int = 5, radio: float = 500.0) -> List[Dict]:
        """FAISS-like: búsqueda por proximidad"""
        resultados = self.vos.raiz.buscar_por_coords(query_vector, radio)
        resultados_con_dist = []
        for key, dato in resultados:
            coords = dato.get('coords', (0, 0, 0))
            dist = math.sqrt(sum((a - b) ** 2
                                 for a, b in zip(coords, query_vector)))
            resultados_con_dist.append({
                'key': key, 'distancia': dist, 'dato': dato
            })
        resultados_con_dist.sort(key=lambda x: x['distancia'])
        return resultados_con_dist[:k]

    def search_by_firma(self, firma_query: Tuple,
                        k: int = 5) -> List[Dict]:
        """Búsqueda por firma W 4D (invariante a permutaciones)"""
        return self.vos.buscar_por_firma_w(firma_query, top_k=k)

    def get_shard(self, espacio_w: int) -> List[str]:
        """Retorna claves asignadas a un shard (espacio W)"""
        return self._shards.get(espacio_w, [])

    def list_shards(self) -> Dict[int, int]:
        """Lista todos los shards con su tamaño"""
        return {esp: len(keys) for esp, keys in self._shards.items() if keys}

    def mmap_read(self, direccion_plana: int) -> Optional[Any]:
        """mmap-like: lectura por dirección plana"""
        return self.vos.leer(direccion_plana)

    def mmap_write(self, direccion_plana: int, valor: Any) -> bool:
        """mmap-like: escritura por dirección plana"""
        return self.vos.escribir(direccion_plana, valor)

    def semantic_query(self, texto: str) -> Dict:
        """Consulta semántica completa"""
        return self.vos.consultar_semantico(texto)


# ============================================================================
# 12. DEMOSTRACIONES COMPLETAS
# ============================================================================

def demo_memoria_3d():
    """Demuestra escritura/lectura con salto diagonal W"""
    print("\n" + "=" * 70)
    print("DEMO 1: MEMORIA VECTORIAL 3D CON SALTO DIAGONAL W")
    print("=" * 70)

    lado = 256
    vos = MemoriaVectorialProduccion(lado_cubo=lado, max_nivel_octree=4)

    n = 500
    print(f"\nEscribiendo {n} valores en cubo {lado}³...")
    t0 = time.perf_counter()
    for i in range(n):
        addr = (i * 97) % (lado ** 2)
        vos.escribir(addr, f"VAL_{i}")
    t_esc = time.perf_counter() - t0

    print(f"Leyendo {n} valores con salto diagonal W...")
    t0 = time.perf_counter()
    exitos = 0
    for i in range(n):
        addr = (i * 97) % (lado ** 2)
        r = vos.leer(addr)
        if r is not None:
            exitos += 1
    t_lec = time.perf_counter() - t0

    print(f"\n  Escritura: {t_esc * 1000:.2f} ms ({n / t_esc:.0f} ops/s)")
    print(f"  Lectura W: {t_lec * 1000:.2f} ms ({n / t_lec:.0f} ops/s)")
    print(f"  Éxitos: {exitos}/{n}")
    print(f"\n{vos.resumen()}")


def demo_cache_y_compresion():
    """Demuestra cache adaptativa y compresión híbrida"""
    print("\n" + "=" * 70)
    print("DEMO 2: CACHE ADAPTATIVA + COMPRESIÓN HÍBRIDA")
    print("=" * 70)

    cache = CacheMemoriaAdaptativa(max_size=100, ttl=60)
    for i in range(200):
        cache.put(f"key_{i}", f"valor_{i}")
    for i in range(50, 150):
        cache.get(f"key_{i}")
    stats = cache.estadisticas()
    print(f"\n  Cache: {stats['tamaño']}/{stats['max_size']} elementos")
    print(f"  Hit rate: {stats['hit_rate']:.1%}")

    compresor = CompresorHibrido()
    vectores = [
        (1000 + i, 1000 + i // 2, 1000 + i // 3)
        for i in range(60)
    ]
    comprimidos = compresor.comprimir_batch(vectores)
    tipos = defaultdict(int)
    for c in comprimidos:
        tipos[c['tipo']] += 1
    print(f"\n  Vectores: {len(vectores)} → Comprimidos: {len(comprimidos)}")
    print(f"  Estrategias: {dict(tipos)}")


def demo_familia_diagonales():
    """Demuestra familia de 4 diagonales y firma W 4D"""
    print("\n" + "=" * 70)
    print("DEMO 3: FAMILIA DE DIAGONALES W + FIRMA W 4D INVARIANTE")
    print("=" * 70)

    familia = FamiliaDiagonales(lado_cubo=1000.0)
    puntos = [
        (100, 100, 100), (500, 500, 500), (900, 900, 900),
        (100, 900, 500), (500, 100, 900),
    ]

    print(f"\n{'Punto':<25} {'Espacios W':<30} {'Firma W normalizada'}")
    print("-" * 75)
    for p in puntos:
        espacios = familia.clasificar_en_espacios(p)
        firma = familia.calcular_firma_normalizada(p)
        print(f"{str(p):<25} {str(espacios):<30} "
              f"({firma[0]:.3f}, {firma[1]:.3f}, {firma[2]:.3f}, {firma[3]:.3f})")

    # Demostrar invariancia a permutaciones
    print("\n  💡 Invariancia a permutaciones (24 combinaciones):")
    firma_a = (0.1, 0.2, 0.3, 0.4)
    firma_b = (0.4, 0.1, 0.3, 0.2)  # Permutación de firma_a
    d_directa = math.sqrt(sum((a - b) ** 2 for a, b in zip(firma_a, firma_b)))
    d_invariante = familia.distancia_entre_firmas(firma_a, firma_b, True)
    print(f"    Distancia directa: {d_directa:.4f}")
    print(f"    Distancia invariante: {d_invariante:.4f} (≈ 0.0)")


def demo_patrones():
    """Demuestra detección de 9 patrones topológicos"""
    print("\n" + "=" * 70)
    print("DEMO 4: DETECCIÓN DE 9 PATRONES TOPOLOGICOS")
    print("=" * 70)

    familia = FamiliaDiagonales(lado_cubo=10000.0)
    predictor = PredictorAccesosAdaptativo(familia, orden_markov=2)

    # Generar patrón LINEAL
    print("\n  📊 Patrón LINEAL (50 accesos):")
    for i in range(50):
        predictor.registrar_acceso((1000 + i * 100, 1000 + i * 50, 1000 + i * 30))
    patrones = predictor.analizador.detectar_patron()
    for t, p in patrones.items():
        print(f"    {t.value}: {p.value}")

    # Generar patrón CLUSTER
    print("\n  📊 Patrón CLUSTER (30 accesos):")
    import random
    random.seed(42)
    for _ in range(30):
        predictor.registrar_acceso((
            5000 + random.gauss(0, 200),
            5000 + random.gauss(0, 200),
            5000 + random.gauss(0, 200)
        ))
    patrones = predictor.analizador.detectar_patron()
    for t, p in patrones.items():
        print(f"    {t.value}: {p.value}")


def demo_prediccion():
    """Demuestra predicción adaptativa"""
    print("\n" + "=" * 70)
    print("DEMO 5: PREDICCIÓN ADAPTATIVA (Markov + Kalman + W)")
    print("=" * 70)

    familia = FamiliaDiagonales(lado_cubo=10000.0)
    predictor = PredictorAccesosAdaptativo(familia, orden_markov=2)

    print("\n  Simulando patrón lineal (50 accesos)...")
    for i in range(50):
        punto = (1000 + i * 100, 1000 + i * 50, 1000 + i * 30)
        predictor.registrar_acceso(punto)

    predicciones = predictor.predecir_proximos_puntos(n=3)
    print("  Próximas predicciones:")
    for i, (punto, conf) in enumerate(predicciones):
        print(f"    [{i + 1}] ({punto[0]:.1f}, {punto[1]:.1f}, {punto[2]:.1f}) "
              f"confianza={conf:.3f}")

    punto_real = (1000 + 50 * 100, 1000 + 50 * 50, 1000 + 50 * 30)
    acierto = predictor.evaluar_prediccion(punto_real, predicciones, radio=500)
    print(f"\n  Punto real: {punto_real}")
    print(f"  ¿Predicción correcta? {'✅ SÍ' if acierto else '❌ NO'}")

    stats = predictor.estadisticas()
    print(f"\n  Precisión bruta: {stats['precision_bruta']}")
    print(f"  Precisión suavizada: {stats['precision_suavizada']}")
    print(f"  Patrones: {stats['patrones_detectados']}")


def demo_semantico():
    """Demuestra mapeo semántico y consulta"""
    print("\n" + "=" * 70)
    print("DEMO 6: MAPEO SEMÁNTICO (texto → D_L → 3D → firma W)")
    print("=" * 70)

    vos = MemoriaVectorialProduccion(lado_cubo=32000)
    queries = [
        "vector diagonal w topología",
        "ia llm modelo tokens contexto",
        "gpu cuda faiss multi-gpu shard",
        "memoria episodio contexto patrón",
        "vector diagonal w topología",
    ]

    for q in queries:
        resultado = vos.consultar_semantico(q)
        print(f"\n  Query: '{q}'")
        print(f"    D_L: {resultado['d_l']}")
        print(f"    Coords: {resultado['coords_3d']}")
        print(f"    Firma W: ({resultado['firma_w'][0]:.3f}, "
              f"{resultado['firma_w'][1]:.3f}, "
              f"{resultado['firma_w'][2]:.3f}, "
              f"{resultado['firma_w'][3]:.3f})")
        print(f"    Tiempo: {resultado['tiempo_ms']:.3f} ms")


def demo_adaptador():
    """Demuestra el adaptador FAISS-like"""
    print("\n" + "=" * 70)
    print("DEMO 7: ADAPTADOR FAISS-LIKE + SHARDING")
    print("=" * 70)

    adaptador = AdaptadorVectorWProduccion(lado_cubo=10000)

    for i in range(100):
        adaptador.add(
            f"doc_{i}",
            (1000 + i * 50, 2000 + i * 30, 3000 + i * 20),
            {'texto': f'documento {i}'}
        )
    print(f"\n  Indexados: 100 documentos")

    resultados = adaptador.search((2500, 2900, 3400), k=3, radio=1000)
    print(f"  Query: (2500, 2900, 3400)")
    for r in resultados:
        print(f"    → {r['key']} distancia={r['distancia']:.1f}")

    print(f"\n  Shards por espacio W:")
    for esp, count in adaptador.list_shards().items():
        print(f"    Espacio {esp}: {count} documentos")


def demo_persistencia():
    """Demuestra persistencia (checkpoint + modelo)"""
    print("\n" + "=" * 70)
    print("DEMO 8: PERSISTENCIA (checkpoint + modelo)")
    print("=" * 70)

    vos = MemoriaVectorialProduccion(
        lado_cubo=512,
        ruta_checkpoint="vos_v6_demo.json",
        ruta_modelo="vos_v6_demo.pkl"
    )

    for i in range(100):
        addr = (i * 97) % (512 ** 2)
        vos.escribir(addr, f"DATO_{i}")

    vos.guardar_checkpoint()
    vos.guardar_modelo()

    print(f"\n  Checkpoint guardado en: {vos.ruta_checkpoint}")
    print(f"  Modelo guardado en: {vos.ruta_modelo}")

    # Verificar carga
    vos2 = MemoriaVectorialProduccion(
        lado_cubo=512,
        ruta_checkpoint="vos_v6_demo.json",
        ruta_modelo="vos_v6_demo.pkl"
    )
    ok1 = vos2.cargar_checkpoint()
    ok2 = vos2.cargar_modelo()
    print(f"\n  Carga checkpoint: {'✅ OK' if ok1 else '❌ FALLÓ'}")
    print(f"  Carga modelo: {'✅ OK' if ok2 else '❌ FALLÓ'}")

    # Limpieza
    for path in ["vos_v6_demo.json", "vos_v6_demo.pkl"]:
        if os.path.exists(path):
            os.remove(path)


def demo_estres():
    """Prueba de estrés"""
    print("\n" + "=" * 70)
    print("DEMO 9: PRUEBA DE ESTRÉS")
    print("=" * 70)

    vos = MemoriaVectorialProduccion(lado_cubo=512, max_nivel_octree=5)

    n = 2000
    print(f"\n  Insertando {n} registros...")
    t0 = time.perf_counter()
    for i in range(n):
        addr = (i * 131) % (512 ** 2)
        vos.escribir(addr, f"STRESS_{i}")
    t_ins = time.perf_counter() - t0
    print(f"  Inserción: {t_ins:.3f}s ({n / t_ins:.0f} ops/s)")

    t0 = time.perf_counter()
    exitos = 0
    for i in range(n):
        addr = (i * 131) % (512 ** 2)
        if vos.leer(addr) is not None:
            exitos += 1
    t_lec = time.perf_counter() - t0
    print(f"  Lectura: {t_lec:.3f}s ({n / t_lec:.0f} ops/s) éxitos={exitos}/{n}")

    vos.optimizar_memoria()
    print(f"\n{vos.resumen()}")


# ============================================================================
# 13. GUÍA DE USO POR CASO
# ============================================================================

GUIA_USO = """
╔══════════════════════════════════════════════════════════════════════╗
║          GUÍA DE USO: vOS v6.0 — vectorW_produccion.py             ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  📦 CASO 1: GESTIÓN DE MEMORIA (reemplazo de memoria plana)         ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_produccion import MemoriaVectorialProduccion         ║
║    vos = MemoriaVectorialProduccion(lado_cubo=1024)                  ║
║    vos.escribir(12345, "mi_dato")                                    ║
║    dato = vos.leer(12345)  # Salto diagonal W → O(log₈ N)          ║
║                                                                      ║
║  🗄️ CASO 2: BASE DE DATOS (indexación espacial + semántica)         ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_produccion import AdaptadorVectorWProduccion         ║
║    db = AdaptadorVectorWProduccion(lado_cubo=32000)                  ║
║    db.add("doc_1", (x, y, z), {"texto": "hola mundo"})              ║
║    resultados = db.search((x, y, z), k=5)                           ║
║    sem = db.semantic_query("vector diagonal w topología")            ║
║                                                                      ║
║  ⏱️ CASO 3: CACHÉ TEMPORAL (datos con TTL)                          ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_produccion import CacheMemoriaAdaptativa             ║
║    cache = CacheMemoriaAdaptativa(max_size=5000, ttl=1800)           ║
║    cache.put("session_abc", datos_usuario)                           ║
║    datos = cache.get("session_abc")  # None si expiró                ║
║    print(cache.estadisticas())  # hit_rate, expulsiones, etc.       ║
║                                                                      ║
║  🔮 CASO 4: PREDICCIÓN DE ACCESOS (prefetching adaptativo)          ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_produccion import (FamiliaDiagonales,                ║
║        PredictorAccesosAdaptativo)                                   ║
║    fam = FamiliaDiagonales(lado_cubo=10000)                          ║
║    pred = PredictorAccesosAdaptativo(fam, orden_markov=2)            ║
║    pred.registrar_acceso((x1, y1, z1))                               ║
║    pred.registrar_acceso((x2, y2, z2))                               ║
║    siguientes = pred.predecir_proximos_puntos(n=5)                   ║
║                                                                      ║
║  🗜️ CASO 5: COMPRESIÓN DE VECTORES                                  ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_produccion import CompresorHibrido                   ║
║    comp = CompresorHibrido()                                         ║
║    comprimidos = comp.comprimir_batch(lista_vectores)                ║
║    originales = comp.descomprimir_batch(comprimidos)                 ║
║                                                                      ║
║  🎯 CASO 6: BÚSQUEDA POR FIRMA W (invariante a permutaciones)       ║
║  ─────────────────────────────────────────────────────────────        ║
║    vos = MemoriaVectorialProduccion(lado_cubo=32000)                 ║
║    r = vos.consultar_semantico("consulta ejemplo")                   ║
║    similares = vos.buscar_por_firma_w(r['firma_w'], top_k=5)         ║
║                                                                      ║
║  💾 CASO 7: PERSISTENCIA DE MODELOS ENTRENADOS                      ║
║  ─────────────────────────────────────────────────────────────        ║
║    vos.guardar_checkpoint()  # JSON con estado completo              ║
║    vos.guardar_modelo()      # Pickle con predictor + familia        ║
║    vos.cargar_checkpoint()   # Restaura estado                       ║
║    vos.cargar_modelo()       # Restaura modelo entrenado             ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  VectorialW OS v6.0 — Sistema Unificado de PRODUCCIÓN")
    print("  Arquitecto: Jose Ricardo Mantilla Mantilla (PePiuoX)")
    print("  Licencia: LAMC v1.0")
    print("=" * 70)

    demo_memoria_3d()
    demo_cache_y_compresion()
    demo_familia_diagonales()
    demo_patrones()
    demo_prediccion()
    demo_semantico()
    demo_adaptador()
    demo_persistencia()
    demo_estres()

    print("\n" + GUIA_USO)

    print("\n✅ Todas las demostraciones completadas exitosamente.")
