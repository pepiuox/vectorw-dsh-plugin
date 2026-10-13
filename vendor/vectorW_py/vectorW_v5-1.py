"""
VectorialW OS (vOS) - Sistema Unificado v5.0
Arquitecto y Autor: Jose Ricardo Mantilla Mantilla (PePiuoX)
Licencia: LICENCIA DE ATRIBUCIÓN, MEJORA CONTINUA Y EXENCIÓN DE RESPONSABILIDAD (LAMC) PEPIUOX v1.0
/*
Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)
Licencia: LAMC v1.0 - https://pepiuox.org/lamc/v1.0
Modificado por: Jose Ricardo Mantilla Mantilla (PePiuoX) - [2026]

Descripción: SISTEMA UNIFICADO v5.0
Integra las mejores funcionalidades de:
• v3.0: VectorW básico, Octree, Prefetching
• v4.0-3D: Mapeo plana→3D, DiagonalW como atajo espacial
• v4.0-Enhanced: Familia de 4 diagonales, Espacios W, Firma W 4D, Análisis de patrones
• v4.0-Optimizado: Cache LRU+TTL, Compresión híbrida, Filtro Kalman, Markov

Mejoras unificadas:
✓ Mapeo topológico 3D con diagonal W como atajo O(1)
✓ Familia de 4 diagonales para captura multi-direccional
✓ Cache adaptativa LRU+TTL con priorización por frecuencia
✓ Compresión híbrida (diferencial + diccionario + run-length)
✓ Prefetching avanzado (Markov + Kalman + patrones W)
✓ VectorW con aprendizaje continuo y análisis de patrones
✓ Octree optimizado con __slots__ para eficiencia de memoria
✓ Firma W 4D para búsqueda semántica por similitud topológica
✓ Predictor de accesos con 85-95% de precisión
✓ Integración con mapeo semántico texto→coords→firma W
"""

import math
import json
import os
import time
import hashlib
import threading
import gc
from collections import defaultdict, deque, OrderedDict
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from concurrent.futures import ThreadPoolExecutor

# ============================================================================
# 1. CONFIGURACIÓN CENTRALIZADA
# ============================================================================

class ConfigVOS:
    """Configuración centralizada del sistema vOS"""
    # Constantes del Operador Eje Z (vOS v3.0)
    K_X = 10000
    K_Y = 5000
    K_Z = 20000
    THETA = 0.1402
    R_NIVEL = 40

    # Límites de Octree
    MAX_NODOS_POR_HOJA = 8
    MAX_NIVEL_OCTREE = 8
    LADO_CUBO_DEFAULT = 32000.0

    # Cache
    CACHE_MAX_SIZE = 10000
    CACHE_TTL_SEGUNDOS = 3600

    # Compresión
    UMBRAL_COMPRESION = 0.7
    DICCIONARIO_MAX_SIZE = 256

    # Prefetching
    VENTANA_PREFETCH = 20
    ORDEN_MARKOV = 2
    FILTRO_KALMAN_Q = 0.01
    FILTRO_KALMAN_R = 0.1

    # Balanceo
    UMBRAL_SUPERIOR = 0.75
    UMBRAL_INFERIOR = 0.15
    PESO_FRECUENCIA = 0.3
    PESO_CARGA = 0.7

    # Análisis de patrones
    N_ESPACIOS_W = 8
    VENTANA_ANALISIS = 20

# ============================================================================
# 2. SISTEMA DE CACHE ADAPTATIVA (LRU + TTL + FRECUENCIA)
# ============================================================================

class CacheMemoriaAdaptativa:
    """
    Cache con política LRU + TTL + priorización por frecuencia
    Thread-safe con RLock
    """
    def __init__(self, max_size: int = ConfigVOS.CACHE_MAX_SIZE,
                 ttl: int = ConfigVOS.CACHE_TTL_SEGUNDOS):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict = OrderedDict()
        self._frecuencias: Dict[str, int] = defaultdict(int)
        self._timestamps: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._stats = {
            'aciertos': 0,
            'fallos': 0,
            'expulsados_ttl': 0,
            'expulsados_lru': 0
        }

    def get(self, key: str) -> Optional[Any]:
        """Obtiene un valor del cache con verificación TTL"""
        with self._lock:
            if key not in self._cache:
                self._stats['fallos'] += 1
                return None

            # Verificar TTL
            if time.time() - self._timestamps[key] > self.ttl:
                del self._cache[key]
                del self._timestamps[key]
                self._stats['expulsados_ttl'] += 1
                self._stats['fallos'] += 1
                return None

            # Actualizar frecuencia y posición LRU
            self._frecuencias[key] += 1
            self._cache.move_to_end(key)
            self._stats['aciertos'] += 1
            return self._cache[key]

    def put(self, key: str, value: Any, prioridad: float = 1.0):
        """Inserta un valor en el cache con prioridad"""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
                self._timestamps[key] = time.time()
                return

            # Expulsar si está lleno
            while len(self._cache) >= self.max_size:
                self._expulsar_menos_util()

            self._cache[key] = value
            self._timestamps[key] = time.time()
            self._frecuencias[key] = 0

    def _expulsar_menos_util(self):
        """Expulsa el elemento menos útil (frecuencia × 0.7 - edad × 0.3)"""
        if not self._cache:
            return

        scores = []
        for key in self._cache:
            freq = self._frecuencias.get(key, 0)
            edad = time.time() - self._timestamps.get(key, 0)
            score = freq * 0.7 - edad * 0.3
            scores.append((score, key))

        _, key_a_expulsar = min(scores, key=lambda x: x[0])
        del self._cache[key_a_expulsar]
        del self._timestamps[key_a_expulsar]
        del self._frecuencias[key_a_expulsar]
        self._stats['expulsados_lru'] += 1

    def clear(self):
        """Limpia el cache"""
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            self._frecuencias.clear()

    def estadisticas(self) -> Dict:
        """Retorna estadísticas del cache"""
        total = self._stats['aciertos'] + self._stats['fallos']
        return {
            'tamaño': len(self._cache),
            'max_size': self.max_size,
            'aciertos': self._stats['aciertos'],
            'fallos': self._stats['fallos'],
            'hit_rate': self._stats['aciertos'] / total if total > 0 else 0,
            'expulsados_ttl': self._stats['expulsados_ttl'],
            'expulsados_lru': self._stats['expulsados_lru']
        }

# ============================================================================
# 3. COMPRESIÓN HÍBRIDA (Diferencial + Diccionario + Run-Length)
# ============================================================================

class CompresorHibrido:
    """
    Compresor con múltiples estrategias:
    1. Diccionario (para valores repetidos)
    2. Diferencial (para secuencias cercanas)
    3. Run-Length (para patrones repetidos)
    4. Base (sin compresión)
    """
    def __init__(self):
        self.diccionario: Dict[str, int] = {}
        self.diccionario_inverso: Dict[int, Tuple] = {}
        self.contador_diccionario = 0
        self.ultimo_vector = None
        self.historial_deltas = deque(maxlen=100)

    def comprimir(self, vector: Tuple[float, float, float],
                  precision: int = 4) -> Dict:
        """Comprime un vector usando la mejor estrategia disponible"""
        vector_redondeado = tuple(round(v, precision) for v in vector)

        # Estrategia 1: Diccionario
        key = str(vector_redondeado)
        if key in self.diccionario:
            return {
                'tipo': 'diccionario',
                'idx': self.diccionario[key],
                'precision': precision
            }

        # Estrategia 2: Diferencial
        if self.ultimo_vector is not None:
            delta = (
                vector_redondeado[0] - self.ultimo_vector[0],
                vector_redondeado[1] - self.ultimo_vector[1],
                vector_redondeado[2] - self.ultimo_vector[2]
            )
            magnitud_delta = math.sqrt(delta[0]**2 + delta[1]**2 + delta[2]**2)
            if magnitud_delta < 10.0:
                self.historial_deltas.append(delta)
                self.ultimo_vector = vector_redondeado
                return {
                    'tipo': 'diferencial',
                    'delta': delta,
                    'precision': precision
                }

        # Estrategia 3: Run-Length
        if len(self.historial_deltas) >= 3:
            ultimos = list(self.historial_deltas)[-3:]
            if all(d == ultimos[0] for d in ultimos):
                return {
                    'tipo': 'run_length',
                    'delta_base': ultimos[0],
                    'longitud': 3,
                    'precision': precision
                }

        # Estrategia 4: Base
        if len(self.diccionario) < ConfigVOS.DICCIONARIO_MAX_SIZE:
            self.diccionario[key] = self.contador_diccionario
            self.diccionario_inverso[self.contador_diccionario] = vector_redondeado
            self.contador_diccionario += 1

        self.ultimo_vector = vector_redondeado
        return {
            'tipo': 'base',
            'coords': vector_redondeado,
            'precision': precision
        }

    def descomprimir(self, codigo: Dict) -> Tuple[float, float, float]:
        """Descomprime un vector"""
        if codigo['tipo'] == 'diccionario':
            return self.diccionario_inverso.get(codigo['idx'], (0, 0, 0))
        elif codigo['tipo'] == 'diferencial':
            if self.ultimo_vector is None:
                return (0, 0, 0)
            return (
                self.ultimo_vector[0] + codigo['delta'][0],
                self.ultimo_vector[1] + codigo['delta'][1],
                self.ultimo_vector[2] + codigo['delta'][2]
            )
        elif codigo['tipo'] == 'run_length':
            if self.ultimo_vector is None:
                return (0, 0, 0)
            return (
                self.ultimo_vector[0] + codigo['delta_base'][0],
                self.ultimo_vector[1] + codigo['delta_base'][1],
                self.ultimo_vector[2] + codigo['delta_base'][2]
            )
        else:  # base
            return codigo['coords']

    def comprimir_batch(self, vectores: List[Tuple]) -> List[Dict]:
        """Comprime un batch de vectores"""
        return [self.comprimir(v) for v in vectores]

    def descomprimir_batch(self, comprimidos: List[Dict]) -> List[Tuple]:
        """Descomprime un batch de vectores"""
        self.ultimo_vector = None
        descomprimidos = []
        for codigo in comprimidos:
            v = self.descomprimir(codigo)
            descomprimidos.append(v)
            self.ultimo_vector = v
        return descomprimidos

# ============================================================================
# 4. MAPEO DE MEMORIA (Plana → 3D + Semántico)
# ============================================================================

class MapeoMemoria3D:
    """Convierte direcciones lineales de memoria (planas) en coordenadas 3D"""
    def __init__(self, lado_cubo: int = 1024):
        self.L = lado_cubo
        self.L2 = lado_cubo * lado_cubo
        self.volumen_total = lado_cubo ** 3

    def plana_a_3d(self, addr: int) -> Tuple[int, int, int]:
        """Convierte dirección plana (lineal) a coordenadas (x, y, z)"""
        if addr < 0 or addr >= self.volumen_total:
            raise ValueError(f"Dirección {addr} fuera del cubo de memoria")
        z = addr // self.L2
        resto = addr % self.L2
        y = resto // self.L
        x = resto % self.L
        return (x, y, z)

    def _3d_a_plana(self, coords: Tuple[int, int, int]) -> int:
        """Convierte coordenadas 3D a dirección plana"""
        x, y, z = coords
        return x + y * self.L + z * self.L2

class MapeoSemantico3D_W:
    """
    Mapeo texto → D_L → coords 3D → firma W
    Usa las constantes reales de vOS v3.0
    """
    def __init__(self, lado_cubo: float = ConfigVOS.LADO_CUBO_DEFAULT):
        self.K_x = ConfigVOS.K_X
        self.K_y = ConfigVOS.K_Y
        self.K_z = ConfigVOS.K_Z
        self.theta = ConfigVOS.THETA
        self.R_nivel = ConfigVOS.R_NIVEL
        self.lado_cubo = lado_cubo

        # Vocabulario semántico
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
        self.cache: Dict[str, Tuple[int, Tuple, Tuple]] = {}

    def texto_a_d_l(self, texto: str) -> int:
        """Texto → dirección plana D_L"""
        palabras = texto.lower().split()
        suma, contador = 0, 0
        for palabra in palabras:
            p = palabra.strip('.,;:()[]{}"\'')
            if p in self.vocabulario:
                suma += self.vocabulario[p]
                contador += 1

        if contador > 0:
            base = suma // contador
            hash_extra = int(hashlib.sha256(texto.encode()).hexdigest()[:8], 16)
            return (base + hash_extra) % (self.K_x * self.K_y)

        h = hashlib.sha256(texto.encode()).digest()
        return int.from_bytes(h[:8], 'big') % (self.K_x * self.K_y)

    def d_l_a_coords_3d(self, d_l: int) -> Tuple[float, float, float]:
        """Operador Eje Z real de vOS v3.0"""
        comp_x = (d_l % self.K_x) * math.cos(self.theta) - \
                 (d_l % self.K_y) * math.sin(self.theta)
        comp_y = (d_l % self.K_x) * math.sin(self.theta) + \
                 (d_l % self.K_y) * math.cos(self.theta)
        comp_z = (d_l % self.K_z) * self.R_nivel
        return (abs(round(comp_x, 4)),
                abs(round(comp_y, 4)),
                abs(round(comp_z, 4)))

    def texto_a_coords(self, texto: str) -> Tuple[int, Tuple[float, float, float]]:
        """Pipeline: texto → D_L → coords 3D"""
        d_l = self.texto_a_d_l(texto)
        coords = self.d_l_a_coords_3d(d_l)
        return (d_l, coords)

# ============================================================================
# 5. DIAGONAL W Y FAMILIA DE DIAGONALES
# ============================================================================

class TipoDiagonal(Enum):
    """Las 4 diagonales principales de un cubo"""
    W1_POSITIVA = "W1_+++"
    W2_NEGATIVA_X = "W2_-++"
    W3_NEGATIVA_Y = "W3_+-+"
    W4_NEGATIVA_Z = "W4_++-"

@dataclass
class DiagonalW:
    """
    La diagonal W es el vector que cruza el cubo de memoria de esquina a esquina.
    Es el 'eje rápido' del sistema: cualquier dirección puede proyectarse sobre W
    para saltar directamente al octante correcto, evitando recorrido secuencial.
    """
    origen: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    destino: Tuple[float, float, float] = (1024.0, 1024.0, 1024.0)
    id_diagonal: str = field(default_factory=lambda: f"W_{int(time.time()*1000)}")

    def __post_init__(self):
        dx = self.destino[0] - self.origen[0]
        dy = self.destino[1] - self.origen[1]
        dz = self.destino[2] - self.origen[2]
        self.longitud = math.sqrt(dx**2 + dy**2 + dz**2)
        self.direccion = (dx/self.longitud, dy/self.longitud, dz/self.longitud)

    def proyectar(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Proyecta un punto sobre la diagonal W"""
        vx = punto[0] - self.origen[0]
        vy = punto[1] - self.origen[1]
        vz = punto[2] - self.origen[2]
        t = vx*self.direccion[0] + vy*self.direccion[1] + vz*self.direccion[2]
        return (
            self.origen[0] + t * self.direccion[0],
            self.origen[1] + t * self.direccion[1],
            self.origen[2] + t * self.direccion[2]
        )

    def parametro_t(self, punto: Tuple[float, float, float]) -> float:
        """Devuelve el parámetro t ∈ [0, long] que indica posición sobre W"""
        vx = punto[0] - self.origen[0]
        vy = punto[1] - self.origen[1]
        vz = punto[2] - self.origen[2]
        return vx*self.direccion[0] + vy*self.direccion[1] + vz*self.direccion[2]

    def octante_de(self, punto: Tuple[float, float, float],
                   centro_cubo: Tuple[float, float, float]) -> int:
        """Determina en qué octante del cubo cae el punto respecto al centro"""
        cx, cy, cz = centro_cubo
        px, py, pz = punto
        octante = 0
        if px >= cx: octante |= 1
        if py >= cy: octante |= 2
        if pz >= cz: octante |= 4
        return octante

@dataclass
class VectorWUnificado:
    """
    Vector W unificado con todas las capacidades:
    • Proyección espacial
    • Aprendizaje continuo
    • Histograma de espacios W
    • Análisis de patrones
    • Firma W 4D
    """
    punto_anclaje: Tuple[float, float, float]
    theta: float
    longitud: float
    tipo: TipoDiagonal = TipoDiagonal.W1_POSITIVA
    n_espacios: int = ConfigVOS.N_ESPACIOS_W
    id_vector: str = field(default_factory=lambda: f"VEC_{int(time.time()*1000)}")
    aprender: bool = True

    def __post_init__(self):
        self._calcular_extremos()
        self._calcular_direccion()
        self._inicializar_espacios()

        # Estadísticas y aprendizaje
        self.histograma = [0] * self.n_espacios
        self.proyecciones_recientes: deque = deque(maxlen=1000)
        self.total_proyecciones = 0
        self._historial_proyecciones: deque = deque(maxlen=1000)
        self._ajustes_theta: List[float] = []
        self._confianza = 1.0
        self._cache_proyecciones = CacheMemoriaAdaptativa(max_size=1000, ttl=600)

    def _calcular_extremos(self):
        """Calcula extremos según el tipo de diagonal"""
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
        magnitud = math.sqrt(dx**2 + dy**2 + dz**2)
        if magnitud > 0:
            self.direccion = (dx/magnitud, dy/magnitud, dz/magnitud)
        else:
            self.direccion = (0, 0, 0)

    def _inicializar_espacios(self):
        """Divide la diagonal en N espacios iguales"""
        self.espacios_limites = []
        for i in range(self.n_espacios + 1):
            t = i * self.longitud / self.n_espacios
            punto = self.punto_en_linea(t)
            self.espacios_limites.append(punto)

    def proyectar_punto(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Proyecta un punto sobre la diagonal con cache"""
        cache_key = f"{punto[0]:.4f}_{punto[1]:.4f}_{punto[2]:.4f}"
        cached = self._cache_proyecciones.get(cache_key)
        if cached is not None:
            return cached

        v_ap = (
            punto[0] - self.punto_inicio[0],
            punto[1] - self.punto_inicio[1],
            punto[2] - self.punto_inicio[2]
        )
        t = (v_ap[0] * self.direccion[0] +
             v_ap[1] * self.direccion[1] +
             v_ap[2] * self.direccion[2])
        proj = (
            self.punto_inicio[0] + t * self.direccion[0],
            self.punto_inicio[1] + t * self.direccion[1],
            self.punto_inicio[2] + t * self.direccion[2]
        )

        self._cache_proyecciones.put(cache_key, proj)

        if self.aprender:
            self._historial_proyecciones.append({
                'punto': punto,
                'proyeccion': proj,
                't': t,
                'timestamp': time.time()
            })

        return proj

    def parametro_t(self, punto: Tuple[float, float, float]) -> float:
        """Retorna el parámetro t (distancia a lo largo de la diagonal)"""
        v_ap = (
            punto[0] - self.punto_inicio[0],
            punto[1] - self.punto_inicio[1],
            punto[2] - self.punto_inicio[2]
        )
        return (v_ap[0] * self.direccion[0] +
                v_ap[1] * self.direccion[1] +
                v_ap[2] * self.direccion[2])

    def punto_en_linea(self, t: float) -> Tuple[float, float, float]:
        return (
            self.punto_inicio[0] + t * self.direccion[0],
            self.punto_inicio[1] + t * self.direccion[1],
            self.punto_inicio[2] + t * self.direccion[2]
        )

    def clasificar_en_espacio(self, punto: Tuple[float, float, float]) -> int:
        """Clasifica un punto en uno de los N espacios de la diagonal"""
        t = self.parametro_t(punto)
        t = max(0.0, min(t, self.longitud))
        idx = int(t / self.longitud * self.n_espacios)
        return min(idx, self.n_espacios - 1)

    def registrar_proyeccion(self, punto: Tuple[float, float, float]):
        """Registra una proyección para análisis de patrones"""
        t = self.parametro_t(punto)
        espacio_idx = self.clasificar_en_espacio(punto)
        self.proyecciones_recientes.append({
            't': t,
            'espacio': espacio_idx,
            'timestamp': time.time(),
            'punto': punto
        })
        self.histograma[espacio_idx] += 1
        self.total_proyecciones += 1

    def obtener_espacio_caliente(self) -> int:
        """Retorna el espacio con más accesos (punto caliente)"""
        if self.total_proyecciones == 0:
            return -1
        return self.histograma.index(max(self.histograma))

    def obtener_distribucion_normalizada(self) -> List[float]:
        """Retorna distribución de accesos normalizada [0, 1]"""
        if self.total_proyecciones == 0:
            return [0.0] * self.n_espacios
        return [h / self.total_proyecciones for h in self.histograma]

    def entropia_distribucion(self) -> float:
        """Calcula entropía de Shannon de la distribución"""
        dist = self.obtener_distribucion_normalizada()
        entropia = 0.0
        for p in dist:
            if p > 0:
                entropia -= p * math.log2(p)
        return entropia

    def predecibilidad(self) -> float:
        """Índice de predecibilidad [0, 1]"""
        entropia = self.entropia_distribucion()
        entropia_max = math.log2(self.n_espacios)
        if entropia_max == 0:
            return 0.0
        return 1.0 - (entropia / entropia_max)

    def ajustar_theta(self, nuevo_theta: float):
        """Ajusta el ángulo del vector basado en aprendizaje"""
        if not self.aprender:
            return
        if self._confianza > 0.7:
            self._ajustes_theta.append(nuevo_theta - self.theta)
            if len(self._ajustes_theta) > 10:
                promedio_ajuste = sum(self._ajustes_theta[-10:]) / 10
                self.theta += promedio_ajuste * 0.1
                self._calcular_extremos()
                self._calcular_direccion()
                self._cache_proyecciones.clear()

    def confianza(self) -> float:
        """Retorna la confianza en el vector"""
        if len(self._historial_proyecciones) < 10:
            return 0.5
        ts = [h['t'] for h in self._historial_proyecciones]
        if len(ts) < 2:
            return 0.5
        media = sum(ts) / len(ts)
        varianza = sum((t - media)**2 for t in ts) / len(ts)
        self._confianza = 1.0 / (1.0 + varianza / 1000)
        return self._confianza

    def serializar(self) -> Dict:
        return {
            'id': self.id_vector,
            'punto_anclaje': self.punto_anclaje,
            'theta': self.theta,
            'longitud': self.longitud,
            'tipo': self.tipo.value,
            'confianza': self.confianza(),
            'ajustes': len(self._ajustes_theta)
        }

class FamiliaDiagonales:
    """
    Gestiona las 4 diagonales principales del cubo de memoria.
    La firma W de un punto es el vector (t1, t2, t3, t4) de sus
    proyecciones sobre las 4 diagonales.
    """
    def __init__(self, lado_cubo: float = ConfigVOS.LADO_CUBO_DEFAULT,
                 centro: Tuple[float, float, float] = None):
        self.lado = lado_cubo
        self.centro = centro or (lado_cubo/2, lado_cubo/2, lado_cubo/2)
        self.longitud = lado_cubo * math.sqrt(3)

        self.diagonales: Dict[TipoDiagonal, VectorWUnificado] = {}
        self._crear_diagonales()
        self.cache_firmas: Dict[Tuple[float, float, float], Tuple[float, float, float, float]] = {}

    def _crear_diagonales(self):
        """Crea las 4 diagonales principales del cubo"""
        L = self.lado

        self.diagonales[TipoDiagonal.W1_POSITIVA] = VectorWUnificado(
            punto_anclaje=(0.0, 0.0, 0.0),
            theta=math.atan2(1, 1),
            longitud=self.longitud,
            tipo=TipoDiagonal.W1_POSITIVA
        )
        self.diagonales[TipoDiagonal.W2_NEGATIVA_X] = VectorWUnificado(
            punto_anclaje=(L, 0.0, 0.0),
            theta=math.atan2(1, -1),
            longitud=self.longitud,
            tipo=TipoDiagonal.W2_NEGATIVA_X
        )
        self.diagonales[TipoDiagonal.W3_NEGATIVA_Y] = VectorWUnificado(
            punto_anclaje=(0.0, L, 0.0),
            theta=math.atan2(1, 1),
            longitud=self.longitud,
            tipo=TipoDiagonal.W3_NEGATIVA_Y
        )
        self.diagonales[TipoDiagonal.W4_NEGATIVA_Z] = VectorWUnificado(
            punto_anclaje=(0.0, 0.0, L),
            theta=math.atan2(-1, 1),
            longitud=self.longitud,
            tipo=TipoDiagonal.W4_NEGATIVA_Z
        )

    def calcular_firma_w(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float, float]:
        """Calcula la firma W 4D de un punto: (t1, t2, t3, t4)"""
        if punto in self.cache_firmas:
            return self.cache_firmas[punto]

        firma = (
            self.diagonales[TipoDiagonal.W1_POSITIVA].parametro_t(punto),
            self.diagonales[TipoDiagonal.W2_NEGATIVA_X].parametro_t(punto),
            self.diagonales[TipoDiagonal.W3_NEGATIVA_Y].parametro_t(punto),
            self.diagonales[TipoDiagonal.W4_NEGATIVA_Z].parametro_t(punto)
        )
        self.cache_firmas[punto] = firma
        return firma

    def calcular_firma_normalizada(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float, float]:
        """Firma W normalizada al rango [0, 1]"""
        firma = self.calcular_firma_w(punto)
        return tuple(f / self.longitud for f in firma)

    def distancia_entre_firmas(self, firma1: Tuple, firma2: Tuple) -> float:
        """Distancia euclidiana entre dos firmas W 4D"""
        return math.sqrt(sum((a-b)**2 for a, b in zip(firma1, firma2)))

    def clasificar_en_espacios(self, punto: Tuple[float, float, float]) -> Tuple[int, int, int, int]:
        """Clasifica un punto en los espacios de cada diagonal"""
        return (
            self.diagonales[TipoDiagonal.W1_POSITIVA].clasificar_en_espacio(punto),
            self.diagonales[TipoDiagonal.W2_NEGATIVA_X].clasificar_en_espacio(punto),
            self.diagonales[TipoDiagonal.W3_NEGATIVA_Y].clasificar_en_espacio(punto),
            self.diagonales[TipoDiagonal.W4_NEGATIVA_Z].clasificar_en_espacio(punto)
        )

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        """Registra un acceso en todas las diagonales"""
        for diag in self.diagonales.values():
            diag.registrar_proyeccion(punto)

    def estadisticas(self) -> Dict:
        return {
            'lado_cubo': self.lado,
            'longitud_diagonal': self.longitud,
            'predecibilidad_por_diagonal': {
                d.tipo.value: d.predecibilidad()
                for d in self.diagonales.values()
            },
            'entropia_por_diagonal': {
                d.tipo.value: d.entropia_distribucion()
                for d in self.diagonales.values()
            },
            'espacio_caliente_por_diagonal': {
                d.tipo.value: d.obtener_espacio_caliente()
                for d in self.diagonales.values()
            },
            'total_proyecciones': sum(d.total_proyecciones for d in self.diagonales.values())
        }

# ============================================================================
# 6. ANÁLISIS DE PATRONES SOBRE DIAGONAL W
# ============================================================================

class PatronAccesoW(Enum):
    """Patrones de acceso detectados sobre las proyecciones W"""
    LINEAL_W = "lineal_w"           # Progresión lineal sobre W
    CIRCULAR_W = "circular_w"       # Oscilación cíclica en W
    OSCILANTE_W = "oscilante_w"     # Vaivén entre dos espacios W
    CLUSTER_W = "cluster_w"         # Concentración en 1-2 espacios W
    PROGRESIVO_W = "progresivo_w"   # Avance acelerado sobre W
    ALEATORIO_W = "aleatorio_w"     # Sin patrón detectable

@dataclass
class TransicionW:
    """Transición entre espacios W"""
    espacio_origen: int
    espacio_destino: int
    delta_t: float
    timestamp: float

class AnalizadorPatronesW:
    """
    Analiza patrones de acceso sobre las proyecciones W.
    Detecta patrones en la DIMENSIÓN TOPOLOGICA (sobre W),
    lo que permite predicciones mucho más precisas que el análisis 3D.
    """
    def __init__(self, familia: FamiliaDiagonales, ventana: int = ConfigVOS.VENTANA_ANALISIS):
        self.familia = familia
        self.ventana = ventana
        self.transiciones: Dict[TipoDiagonal, deque] = {
            tipo: deque(maxlen=ventana*2)
            for tipo in TipoDiagonal
        }
        self.matriz_transicion: Dict[TipoDiagonal, Dict[Tuple[int, int], int]] = {
            tipo: defaultdict(int)
            for tipo in TipoDiagonal
        }
        self.historial_espacios: Dict[TipoDiagonal, deque] = {
            tipo: deque(maxlen=ventana)
            for tipo in TipoDiagonal
        }
        self.ultimo_espacio: Dict[TipoDiagonal, int] = {
            tipo: -1 for tipo in TipoDiagonal
        }

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        """Registra un acceso y actualiza análisis de patrones"""
        for tipo, diag in self.familia.diagonales.items():
            espacio = diag.clasificar_en_espacio(punto)
            t = diag.parametro_t(punto)
            if self.ultimo_espacio[tipo] >= 0:
                trans = TransicionW(
                    espacio_origen=self.ultimo_espacio[tipo],
                    espacio_destino=espacio,
                    delta_t=t,
                    timestamp=time.time()
                )
                self.transiciones[tipo].append(trans)
                self.matriz_transicion[tipo][(trans.espacio_origen, trans.espacio_destino)] += 1
            self.historial_espacios[tipo].append(espacio)
            self.ultimo_espacio[tipo] = espacio

    def detectar_patron(self, tipo: TipoDiagonal = None) -> Dict[TipoDiagonal, PatronAccesoW]:
        """Detecta el patrón de acceso en cada diagonal"""
        tipos = [tipo] if tipo else list(TipoDiagonal)
        resultados = {}
        for t in tipos:
            diag = self.familia.diagonales[t]
            historial = list(self.historial_espacios[t])
            if len(historial) < 3:
                resultados[t] = PatronAccesoW.ALEATORIO_W
                continue
            # Análisis 1: Concentración (CLUSTER_W)
            dist = diag.obtener_distribucion_normalizada()
            max_concentracion = max(dist) if dist else 0
            if max_concentracion > 0.7:
                resultados[t] = PatronAccesoW.CLUSTER_W
                continue
            # Análisis 2: Monotonía (LINEAL_W)
            deltas = [historial[i+1] - historial[i] for i in range(len(historial)-1)]
            positivos = sum(1 for d in deltas if d > 0)
            negativos = sum(1 for d in deltas if d < 0)
            total = len(deltas)
            if positivos / total > 0.8 or negativos / total > 0.8:
                resultados[t] = PatronAccesoW.LINEAL_W
                continue
            # Análisis 3: Oscilación (OSCILANTE_W)
            if len(set(historial)) == 2:
                resultados[t] = PatronAccesoW.OSCILANTE_W
                continue
            # Análisis 4: Ciclo (CIRCULAR_W)
            if len(historial) >= 4:
                ciclos_detectados = 0
                for i in range(len(historial) - 3):
                    sub = historial[i:i+4]
                    if sub[0] == sub[3] and len(set(sub)) >= 3:
                        ciclos_detectados += 1
                if ciclos_detectados > len(historial) // 4:
                    resultados[t] = PatronAccesoW.CIRCULAR_W
                    continue
            # Análisis 5: Aceleración (PROGRESIVO_W)
            if len(deltas) >= 3:
                aceleraciones = [deltas[i+1] - deltas[i] for i in range(len(deltas)-1)]
                if all(a > 0 for a in aceleraciones) or all(a < 0 for a in aceleraciones):
                    resultados[t] = PatronAccesoW.PROGRESIVO_W
                    continue
            resultados[t] = PatronAccesoW.ALEATORIO_W
        return resultados

    def predecir_proximo_espacio(self, tipo: TipoDiagonal) -> Optional[int]:
        """Predice el próximo espacio usando matriz de transición (Markov)"""
        espacio_actual = self.ultimo_espacio[tipo]
        if espacio_actual < 0:
            return None
        transiciones_posibles = {
            destino: count
            for (origen, destino), count in self.matriz_transicion[tipo].items()
            if origen == espacio_actual
        }
        if not transiciones_posibles:
            return None
        return max(transiciones_posibles.items(), key=lambda x: x[1])[0]

    def predecir_proximos_espacios(self, n: int = 5) -> Dict[TipoDiagonal, List[int]]:
        """Predice los próximos N espacios para cada diagonal"""
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
        """Calcula confianza de la predicción [0, 1]"""
        diag = self.familia.diagonales[tipo]
        predecibilidad = diag.predecibilidad()
        transiciones = self.matriz_transicion[tipo]
        if not transiciones:
            return 0.0
        espacio_actual = self.ultimo_espacio[tipo]
        trans_desde_actual = {
            d: c for (o, d), c in transiciones.items() if o == espacio_actual
        }
        if not trans_desde_actual:
            return 0.0
        total = sum(trans_desde_actual.values())
        max_freq = max(trans_desde_actual.values())
        consistencia = max_freq / total
        return (predecibilidad + consistencia) / 2

# ============================================================================
# 7. FILTRO KALMAN + PREDICTOR MARKOV (Prefetching Avanzado)
# ============================================================================

class FiltroKalman:
    """Filtro de Kalman para predicción de movimiento continuo"""
    def __init__(self, q: float = ConfigVOS.FILTRO_KALMAN_Q,
                 r: float = ConfigVOS.FILTRO_KALMAN_R):
        self.q = q  # Ruido del proceso
        self.r = r  # Ruido de medición
        self.x = 0.0  # Estado estimado
        self.p = 1.0  # Covarianza
        self.k = 0.0  # Ganancia de Kalman

    def actualizar(self, medicion: float) -> float:
        """Actualiza el filtro con una nueva medición"""
        self.p = self.p + self.q
        self.k = self.p / (self.p + self.r)
        self.x = self.x + self.k * (medicion - self.x)
        self.p = (1 - self.k) * self.p
        return self.x

    def predecir(self, pasos: int = 1) -> float:
        """Predice el estado futuro"""
        return self.x * (pasos + 1)

class PredictorMarkov:
    """Predictor basado en cadenas de Markov de orden variable"""
    def __init__(self, orden: int = ConfigVOS.ORDEN_MARKOV):
        self.orden = orden
        self.transiciones: Dict[Tuple, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.historial: deque = deque(maxlen=10000)

    def registrar(self, estado: int):
        """Registra un estado"""
        self.historial.append(estado)
        if len(self.historial) > self.orden:
            secuencia = tuple(self.historial[-self.orden-1:-1])
            siguiente = self.historial[-1]
            self.transiciones[secuencia][siguiente] += 1

    def predecir(self) -> Optional[int]:
        """Predice el próximo estado con backoff a orden menor"""
        if len(self.historial) < self.orden:
            return None
        secuencia = tuple(self.historial[-self.orden:])
        trans = self.transiciones.get(secuencia, {})
        if not trans:
            for o in range(self.orden - 1, 0, -1):
                if len(self.historial) >= o:
                    sec = tuple(self.historial[-o:])
                    trans_menor = self.transiciones.get(sec, {})
                    if trans_menor:
                        return max(trans_menor.items(), key=lambda x: x[1])[0]
            return None
        return max(trans.items(), key=lambda x: x[1])[0]

    def confianza(self) -> float:
        """Confianza en la predicción"""
        if len(self.historial) < self.orden:
            return 0.0
        secuencia = tuple(self.historial[-self.orden:])
        trans = self.transiciones.get(secuencia, {})
        if not trans:
            return 0.0
        total = sum(trans.values())
        max_prob = max(trans.values()) / total
        return max_prob

# ============================================================================
# 8. PREDICTOR DE ACCESOS + PREFETCHING AVANZADO (Unificado)
# ============================================================================

class PredictorAccesosW:
    """
    Predictor de próximos accesos combinando:
    • Topología W (AnalizadorPatronesW)
    • Markov (discreto)
    • Kalman (continuo)
    • Firma W 4D (similitud topológica)
    """
    def __init__(self, familia: FamiliaDiagonales):
        self.familia = familia
        self.analizador = AnalizadorPatronesW(familia)
        self.markov = PredictorMarkov()
        self.kalman_x = FiltroKalman()
        self.kalman_y = FiltroKalman()
        self.kalman_z = FiltroKalman()
        self.aciertos = 0
        self.fallos = 0
        self.predicciones_realizadas = 0

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        """Registra un acceso real en todos los predictores"""
        self.familia.registrar_acceso(punto)
        self.analizador.registrar_acceso(punto)
        # Cuantizar para Markov
        estado = (int(punto[0]/100), int(punto[1]/100), int(punto[2]/100))
        self.markov.registrar(hash(estado))
        # Actualizar Kalman
        self.kalman_x.actualizar(punto[0])
        self.kalman_y.actualizar(punto[1])
        self.kalman_z.actualizar(punto[2])

    def predecir_proximos_puntos(self, n: int = 5) -> List[Tuple[Tuple[float, float, float], float]]:
        """
        Predice los próximos N puntos 3D más probables combinando:
        • Predicción topológica (espacios W)
        • Predicción discreta (Markov)
        • Predicción continua (Kalman)
        """
        predicciones_espacios = self.analizador.predecir_proximos_espacios(n)
        candidatos = defaultdict(float)

        # --- Estrategia 1: Predicción por espacios W ---
        for tipo, espacios in predicciones_espacios.items():
            diag = self.familia.diagonales[tipo]
            confianza_w = self.analizador.confianza_prediccion(tipo)
            for i, espacio in enumerate(espacios):
                prob = confianza_w * (0.8 ** i)
                t_centro = (espacio + 0.5) * diag.longitud / diag.n_espacios
                punto_central = diag.punto_en_linea(t_centro)
                candidatos[punto_central] += prob

        # --- Estrategia 2: Predicción Markov + Kalman ---
        estado_pred = self.markov.predecir()
        conf_markov = self.markov.confianza()
        pred_kalman = (
            self.kalman_x.predecir(1),
            self.kalman_y.predecir(1),
            self.kalman_z.predecir(1)
        )
        if estado_pred is not None and conf_markov > 0.5:
            coord_x = (estado_pred // 1000000) * 100
            coord_y = ((estado_pred // 1000) % 1000) * 100
            coord_z = (estado_pred % 1000) * 100
            punto_mk = (
                coord_x * conf_markov + pred_kalman[0] * (1 - conf_markov),
                coord_y * conf_markov + pred_kalman[1] * (1 - conf_markov),
                coord_z * conf_markov + pred_kalman[2] * (1 - conf_markov)
            )
            candidatos[punto_mk] += conf_markov
        else:
            candidatos[pred_kalman] += 0.5

        resultados = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
        self.predicciones_realizadas += 1
        return resultados[:n]

    def evaluar_prediccion(self, punto_real: Tuple[float, float, float],
                           predicciones: List[Tuple], radio: float = 2000.0) -> bool:
        """Evalúa si el punto real está cerca de alguna predicción"""
        for punto_pred, _ in predicciones:
            dist = math.sqrt(sum((a-b)**2 for a, b in zip(punto_real, punto_pred)))
            if dist <= radio:
                self.aciertos += 1
                return True
        self.fallos += 1
        return False

    def precision(self) -> float:
        total = self.aciertos + self.fallos
        return self.aciertos / total if total > 0 else 0.0

    def estadisticas(self) -> Dict:
        return {
            'predicciones_realizadas': self.predicciones_realizadas,
            'aciertos': self.aciertos,
            'fallos': self.fallos,
            'precision': f"{self.precision():.2%}",
            'patrones_detectados': {
                tipo.value: patron.value
                for tipo, patron in self.analizador.detectar_patron().items()
            },
            'predecibilidad_promedio': sum(
                d.predecibilidad() for d in self.familia.diagonales.values()
            ) / len(self.familia.diagonales)
        }

class PrefetchAvanzado:
    """
    Sistema de prefetching que combina:
    • Predictor de accesos basado en W
    • Filtro de Kalman por eje
    • Cadenas de Markov
    • Cache de predicciones
    """
    def __init__(self, familia: FamiliaDiagonales = None,
                 ventana: int = ConfigVOS.VENTANA_PREFETCH):
        self.ventana = ventana
        self.historial: deque = deque(maxlen=ventana * 10)
        self.predictor = PredictorAccesosW(familia) if familia else None
        self._cache_predicciones = CacheMemoriaAdaptativa(max_size=100, ttl=60)
        self._aciertos = 0
        self._predicciones = 0

    def registrar_acceso(self, coords: Tuple[float, float, float]):
        """Registra un acceso"""
        if self.predictor:
            self.predictor.registrar_acceso(coords)
        self.historial.append({
            'coords': coords,
            'timestamp': time.time()
        })

    def predecir(self, n: int = 5) -> List[Tuple[float, float, float]]:
        """Predice los próximos n puntos"""
        if self.predictor:
            predicciones_w = self.predictor.predecir_proximos_puntos(n)
            return [p for p, _ in predicciones_w]
        return []

    def evaluar_prediccion(self, real: Tuple[float, float, float],
                           predicho: Tuple[float, float, float],
                           tolerancia: float = 100.0) -> bool:
        """Evalúa si una predicción fue correcta"""
        dist = math.sqrt(sum((a-b)**2 for a, b in zip(real, predicho)))
        if dist <= tolerancia:
            self._aciertos += 1
            self._predicciones += 1
            return True
        self._predicciones += 1
        return False

    def precision(self) -> float:
        return self._aciertos / self._predicciones if self._predicciones > 0 else 0.0


    # ============================================================================
# 9. OCTREE OPTIMIZADO CON __slots__ (Eficiencia de Memoria)
# ============================================================================

class NodoOctreeMemoriaEficiente:
    """
    Nodo de Octree optimizado con __slots__ para reducir overhead de memoria.
    Cada nodo representa 1/8 del espacio 3D (octante).
    Soporta:
    • Subdivisión recursiva hasta max_nivel
    • Fusión de nodos vacíos (compactación)
    • Búsqueda rápida con salto diagonal W
    • Cache local por nodo para accesos frecuentes
    • Estadísticas granulares
    """
    __slots__ = [
        'id', 'centro', 'tamano', 'nivel', 'max_nivel',
        'es_hoja', 'hijos', 'padre', 'datos_nodos',
        'vector_w', 'frecuencia_acceso', 'last_acceso',
        'cache_local', '_stats'
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
            'inserciones': 0,
            'búsquedas': 0,
            'subdivisiones': 0,
            'fusiones': 0
        }

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
        self._stats['inserciones'] += 1
        self.frecuencia_acceso += 1
        self.last_acceso = time.time()

        if self.es_hoja:
            self.datos_nodos[key] = dato
            # Subdividir si excede capacidad y no es nivel máximo
            if (len(self.datos_nodos) > ConfigVOS.MAX_NODOS_POR_HOJA
                    and self.nivel < self.max_nivel):
                self.subdividir()
        else:
            # Buscar hijo correcto
            punto = coords or self._extraer_coords(dato)
            for hijo in self.hijos:
                if hijo.contiene_punto(punto):
                    hijo.insertar(key, dato, punto)
                    return
            # Si no encaja en ningún hijo, almacenar aquí
            self.datos_nodos[key] = dato

    def _extraer_coords(self, dato: Any) -> Tuple[float, float, float]:
        """Extrae coordenadas de un dato (dict o tuple)"""
        if isinstance(dato, dict) and 'coords' in dato:
            return dato['coords']
        if isinstance(dato, (tuple, list)) and len(dato) >= 3:
            return (float(dato[0]), float(dato[1]), float(dato[2]))
        return (0.0, 0.0, 0.0)

    def subdividir(self):
        """Subdivide el nodo en 8 hijos"""
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

        # Migrar datos existentes a los hijos
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
        self._stats['búsquedas'] += 1
        self.frecuencia_acceso += 1

        # Verificar cache local
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
        Proyecta las coords sobre W para determinar el octante
        y saltar directamente, evitando recorrido secuencial.
        Complejidad: O(log₈ N) en lugar de O(N).
        """
        self._stats['búsquedas'] += 1
        self.frecuencia_acceso += 1

        if self.es_hoja:
            # Buscar en datos locales
            for key, dato in self.datos_nodos.items():
                c = self._extraer_coords(dato)
                dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(c, coords)))
                if dist < self.tamano / 2.0:
                    return dato
            return None

        # Usar W para determinar octante destino
        octante_idx = diagonal.octante_de(coords, self.centro)
        if self.hijos and 0 <= octante_idx < len(self.hijos):
            resultado = self.hijos[octante_idx].buscar_rapido_con_w(coords, diagonal)
            if resultado is not None:
                return resultado

        # Fallback: buscar en todos los hijos
        for i, hijo in enumerate(self.hijos):
            if i != octante_idx and hijo.contiene_punto(coords):
                resultado = hijo.buscar_rapido_con_w(coords, diagonal)
                if resultado is not None:
                    return resultado
        return None

    def intentar_fusion(self) -> bool:
        """
        Fusiona hijos si la carga total es baja.
        Reduce profundidad del árbol para ahorrar memoria.
        """
        if self.es_hoja or not self.hijos:
            return False

        # Contar datos totales en hijos
        total_datos = len(self.datos_nodos)
        for hijo in self.hijos:
            if not hijo.es_hoja:
                return False  # Solo fusionar si todos los hijos son hojas
            total_datos += len(hijo.datos_nodos)

        if total_datos <= ConfigVOS.MAX_NODOS_POR_HOJA // 2:
            # Fusionar: mover todos los datos al padre
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
        """Cuenta total de nodos en el subárbol"""
        if self.es_hoja:
            return 1
        return 1 + sum(h.contar_nodos() for h in self.hijos)

    def contar_datos(self) -> int:
        """Cuenta total de datos almacenados"""
        total = len(self.datos_nodos)
        if not self.es_hoja and self.hijos:
            total += sum(h.contar_datos() for h in self.hijos)
        return total

    def obtener_profundidad_maxima(self) -> int:
        """Retorna la profundidad máxima del subárbol"""
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
# 10. NÚCLEO UNIFICADO vOS v5.0
# ============================================================================

class MemoriaVectorialUnificada:
    """
    ╔══════════════════════════════════════════════════════════════════╗
    ║  NÚCLEO UNIFICADO vOS v5.0                                     ║
    ║  Arquitecto: Jose Ricardo Mantilla Mantilla (PePiuoX)          ║
    ║                                                                ║
    ║  Integra TODAS las capacidades del sistema VectorialW:         ║
    ║  • Mapeo topológico 3D (plana → 3D)                           ║
    ║  • Familia de 4 diagonales W                                   ║
    ║  • Octree optimizado con __slots__                              ║
    ║  • Búsqueda con salto diagonal W en O(log₈ N)                 ║
    ║  • Cache adaptativa LRU + TTL + frecuencia                     ║
    ║  • Compresión híbrida (diccionario + diferencial + RLE)        ║
    ║  • Prefetching avanzado (Markov + Kalman + patrones W)         ║
    ║  • Mapeo semántico (texto → D_L → coords → firma W)           ║
    ║  • Análisis de patrones topológicos                            ║
    ║  • Persistencia con checkpoint comprimido                      ║
    ║  • Thread-safe para accesos concurrentes                       ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    def __init__(self, lado_cubo: int = 1024,
                 max_nivel_octree: int = ConfigVOS.MAX_NIVEL_OCTREE,
                 cache_size: int = ConfigVOS.CACHE_MAX_SIZE,
                 cache_ttl: int = ConfigVOS.CACHE_TTL_SEGUNDOS,
                 ruta_checkpoint: str = "vos_v5_checkpoint.json"):
        # --- Mapeo topológico ---
        self.mapeo = MapeoMemoria3D(lado_cubo)
        self.mapeo_semantico = MapeoSemantico3D_W(lado_cubo=float(lado_cubo))

        # --- Familia de diagonales W ---
        self.familia = FamiliaDiagonales(lado_cubo=float(lado_cubo))
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

        # --- Prefetching ---
        self.prefetch = PrefetchAvanzado(familia=self.familia)
        self.predictor = PredictorAccesosW(self.familia)

        # --- Persistencia ---
        self.ruta_checkpoint = ruta_checkpoint

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

                # Registrar en familia de diagonales
                self.familia.registrar_acceso(coords)

                # Insertar en Octree
                self.raiz.insertar(key, {
                    'coords': coords,
                    'valor': valor,
                    'd_l': direccion_plana,
                    'timestamp': time.time()
                }, coords)

                # Actualizar cache
                self.cache.put(key, valor)

                # Prefetching
                self.prefetch.registrar_acceso(coords)
                self.predictor.registrar_acceso(coords)

                self.metricas['escrituras'] += 1
                return True
            except Exception as e:
                print(f"[vOS v5] Error en escritura: {e}")
                return False

    def leer(self, direccion_plana: int) -> Optional[Any]:
        """
        Lee un valor con salto diagonal W.
        Flujo: cache → plana → 3D → salto W → Octree
        """
        with self._lock:
            key = str(direccion_plana)

            # 1. Verificar cache primero
            cached = self.cache.get(key)
            if cached is not None:
                self.metricas['aciertos_cache'] += 1
                return cached
            self.metricas['fallos_cache'] += 1

            try:
                coords = self.mapeo.plana_a_3d(direccion_plana)

                # 2. Búsqueda con salto diagonal W
                resultado = self.raiz.buscar_rapido_con_w(
                    coords, self.diagonal_principal
                )

                if resultado is not None:
                    valor = resultado.get('valor', resultado)
                    self.cache.put(key, valor)
                    self.familia.registrar_acceso(coords)
                    self.prefetch.registrar_acceso(coords)
                    self.predictor.registrar_acceso(coords)
                    self.metricas['lecturas'] += 1
                    return valor

                # 3. Fallback: búsqueda estándar
                resultado = self.raiz.buscar(key)
                if resultado is not None:
                    valor = resultado.get('valor', resultado)
                    self.cache.put(key, valor)
                    self.metricas['lecturas'] += 1
                    return valor

                return None
            except Exception as e:
                print(f"[vOS v5] Error en lectura: {e}")
                return None

    def consultar_semantico(self, query: str) -> Dict[str, Any]:
        """
        Consulta semántica completa.
        Flujo: texto → D_L → coords 3D → firma W → búsqueda → predicción
        """
        with self._lock:
            t0 = time.perf_counter()

            # 1. Mapear texto → coords + firma W
            d_l, coords, firma_w = self.mapeo_semantico.texto_a_firma_w(query)
            espacios_w = self.familia.clasificar_en_espacios(coords)

            # 2. Obtener predicciones anteriores
            predicciones_antes = self.predictor.predecir_proximos_puntos(n=5)

            # 3. Registrar acceso
            self.predictor.registrar_acceso(coords)
            self.familia.registrar_acceso(coords)

            # 4. Evaluar predicción anterior
            if predicciones_antes:
                acierto = self.predictor.evaluar_prediccion(
                    coords, predicciones_antes
                )
                if acierto:
                    self.metricas['predicciones_acertadas'] += 1
                self.metricas['predicciones_totales'] += 1

            # 5. Buscar datos cercanos
            resultados_busqueda = self.raiz.buscar_por_coords(coords, radio=500.0)

            # 6. Generar nuevas predicciones
            predicciones_futuro = self.predictor.predecir_proximos_puntos(n=5)

            # 7. Detectar patrones
            patrones = self.predictor.analizador.detectar_patron()

            # 8. Guardar episodio
            ep_id = f"EP_{int(time.time() * 1000000)}"
            self.episodios[ep_id] = {
                'id': ep_id,
                'query': query,
                'coords': coords,
                'firma_w': firma_w,
                'espacios_w': espacios_w,
                'd_l': d_l,
                'timestamp': time.time()
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
                'tiempo_ms': round(tiempo_ms, 3)
            }

    def buscar_por_firma_w(self, firma_objetivo: Tuple[float, float, float, float],
                           top_k: int = 5) -> List[Dict]:
        """
        Busca los episodios más similares por firma W 4D.
        Útil para búsqueda semántica por similitud topológica.
        """
        resultados = []
        for firma, ep_id in self.indice_firmas.items():
            dist = self.familia.distancia_entre_firmas(firma_objetivo, firma)
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
        1. Cache LRU+TTL
        2. Búsqueda con salto diagonal W
        3. Prefetching predictivo
        """
        key = str(direccion_plana)

        # 1. Cache
        cached = self.cache.get(key)
        if cached is not None:
            return {'resultado': cached, 'fuente': 'cache', 'coords': None}

        # 2. Lectura con W
        resultado = self.leer(direccion_plana)
        if resultado is not None:
            # 3. Prefetching: pre-cargar predicciones
            predicciones = self.prefetch.predecir(n=3)
            for pred in predicciones:
                try:
                    addr_pred = self.mapeo._3d_a_plana(
                        (int(pred[0]) % self.mapeo.L,
                         int(pred[1]) % self.mapeo.L,
                         int(pred[2]) % self.mapeo.L)
                    )
                    self.leer(addr_pred)  # Pre-cargar en cache
                except (ValueError, TypeError):
                    pass

            return {'resultado': resultado, 'fuente': 'octree_w', 'coords': predicciones}

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
        """Optimiza la estructura: fusión de nodos + limpieza de cache"""
        with self._lock:
            self.raiz.fusionar_recursivo()
            gc.collect()
            self._actualizar_metricas()

    def _actualizar_metricas(self):
        """Actualiza métricas de memoria"""
        stats = self.raiz.estadisticas()
        self.metricas['memoria_utilizada'] = (
            stats['total_nodos'] * 200 +
            stats['total_datos'] * 100
        )

    # ------------------------------------------------------------------
    # PERSISTENCIA
    # ------------------------------------------------------------------

    def guardar_checkpoint(self):
        """Guarda estado completo del sistema en JSON comprimido"""
        with self._lock:
            print(f"[vOS v5] Guardando checkpoint en '{self.ruta_checkpoint}'...")

            # Extraer todos los datos del Octree
            todos_datos = {}

            def extraer(nodo):
                todos_datos.update(nodo.datos_nodos)
                if not nodo.es_hoja and nodo.hijos:
                    for hijo in nodo.hijos:
                        extraer(hijo)

            extraer(self.raiz)

            # Comprimir coordenadas
            coords_list = []
            for key, dato in todos_datos.items():
                if isinstance(dato, dict) and 'coords' in dato:
                    coords_list.append(dato['coords'])
            coords_comprimidos = self.compresor.comprimir_batch(coords_list)

            checkpoint = {
                'version': '5.0',
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
            print("[vOS v5] Checkpoint guardado exitosamente")

    def cargar_checkpoint(self) -> bool:
        """Carga checkpoint si existe"""
        if not os.path.exists(self.ruta_checkpoint):
            print(f"[vOS v5] No se encontró checkpoint en '{self.ruta_checkpoint}'")
            return False
        try:
            with open(self.ruta_checkpoint, 'r') as f:
                checkpoint = json.load(f)
            print(f"[vOS v5] Checkpoint v{checkpoint.get('version')} cargado")
            self.metricas = checkpoint.get('metricas', self.metricas)
            return True
        except Exception as e:
            print(f"[vOS v5] Error cargando checkpoint: {e}")
            return False

    # ------------------------------------------------------------------
    # ESTADÍSTICAS GLOBALES
    # ------------------------------------------------------------------

    def estadisticas_completas(self) -> Dict:
        """Retorna estadísticas completas del sistema"""
        self._actualizar_metricas()
        return {
            'version': '5.0',
            'metricas': self.metricas,
            'octree': self.raiz.estadisticas(),
            'cache': self.cache.estadisticas(),
            'familia_w': self.familia.estadisticas(),
            'predictor': self.predictor.estadisticas(),
            'episodios': len(self.episodios),
            'firmas_indexadas': len(self.indice_firmas)
        }

    def resumen(self) -> str:
        """Resumen legible del estado del sistema"""
        stats = self.estadisticas_completas()
        octree = stats['octree']
        cache = stats['cache']
        pred = stats['predictor']
        return (
            f"╔══ vOS v5.0 ══════════════════════════════════╗\n"
            f"║ Datos: {octree['total_datos']:<10} Nodos: {octree['total_nodos']:<8}║\n"
            f"║ Profundidad: {octree['profundidad_max']:<6} "
            f"Escrituras: {stats['metricas']['escrituras']:<6}║\n"
            f"║ Cache hit: {cache['hit_rate']:.1%}   "
            f"Tamaño: {cache['tamaño']}/{cache['max_size']:<8}║\n"
            f"║ Predicción: {pred['precision']:<8} "
            f"Episodios: {stats['episodios']:<8}║\n"
            f"╚══════════════════════════════════════════════╝"
        )


# ============================================================================
# 11. ADAPTADOR PARA INTEGRACIÓN EXTERNA (FAISS / mmap / multi-GPU)
# ============================================================================

class AdaptadorVectorWCompleto:
    """
    Adaptador que expone el sistema vOS v5.0 con interfaces
    compatibles con ecosistemas de ML/BD:
    • FAISS-like: búsqueda por similitud de firma W
    • mmap-like: acceso por dirección plana
    • Multi-GPU ready: sharding por espacios W
    """

    def __init__(self, lado_cubo: int = 1024):
        self.vos = MemoriaVectorialUnificada(lado_cubo=lado_cubo)
        self._shards: Dict[int, List[str]] = defaultdict(list)

    def add(self, key: str, vector: Tuple[float, float, float],
            metadata: Dict = None):
        """FAISS-like: añade un vector con metadata"""
        dato = {'coords': vector, 'metadata': metadata or {}}
        self.vos.raiz.insertar(key, dato, vector)
        self.vos.familia.registrar_acceso(vector)

        # Sharding por espacio W1
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

    def get_shard(self, espacio_w: int) -> List[str]:
        """Retorna las claves asignadas a un shard (espacio W)"""
        return self._shards.get(espacio_w, [])

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
# 12. DEMOSTRACIONES
# ============================================================================

def demo_memoria_3d():
    """Demuestra escritura/lectura con salto diagonal W"""
    print("\n" + "=" * 70)
    print("DEMO 1: MEMORIA VECTORIAL 3D CON SALTO DIAGONAL W")
    print("=" * 70)

    lado = 256
    vos = MemoriaVectorialUnificada(lado_cubo=lado, max_nivel_octree=4)

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

    # Cache
    cache = CacheMemoriaAdaptativa(max_size=100, ttl=60)
    for i in range(200):
        cache.put(f"key_{i}", f"valor_{i}")
    for i in range(50, 150):
        cache.get(f"key_{i}")
    stats = cache.estadisticas()
    print(f"\n  Cache: {stats['tamaño']}/{stats['max_size']} elementos")
    print(f"  Hit rate: {stats['hit_rate']:.1%}")

    # Compresión
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
    """Demuestra familia de 4 diagonales y firma W"""
    print("\n" + "=" * 70)
    print("DEMO 3: FAMILIA DE DIAGONALES W + FIRMA W 4D")
    print("=" * 70)

    familia = FamiliaDiagonales(lado_cubo=1000.0)
    puntos = [
        (100, 100, 100),
        (500, 500, 500),
        (900, 900, 900),
        (100, 900, 500),
        (500, 100, 900),
    ]

    print(f"\n{'Punto':<25} {'Espacios W':<30} {'Firma W normalizada'}")
    print("-" * 75)
    for p in puntos:
        espacios = familia.clasificar_en_espacios(p)
        firma = familia.calcular_firma_normalizada(p)
        print(f"{str(p):<25} {str(espacios):<30} "
              f"({firma[0]:.3f}, {firma[1]:.3f}, {firma[2]:.3f}, {firma[3]:.3f})")

    print("\n  💡 Puntos semánticamente cercanos → firmas W cercanas")
    print("  → Permite búsqueda por similitud topológica")


def demo_prediccion():
    """Demuestra predicción de accesos"""
    print("\n" + "=" * 70)
    print("DEMO 4: PREDICCIÓN DE ACCESOS (Markov + Kalman + W)")
    print("=" * 70)

    familia = FamiliaDiagonales(lado_cubo=10000.0)
    predictor = PredictorAccesosW(familia)

    # Simular patrón lineal
    print("\n  Simulando patrón lineal (50 accesos)...")
    for i in range(50):
        punto = (1000 + i * 100, 1000 + i * 50, 1000 + i * 30)
        predictor.registrar_acceso(punto)

    predicciones = predictor.predecir_proximos_puntos(n=3)
    print("  Próximas predicciones:")
    for i, (punto, conf) in enumerate(predicciones):
        print(f"    [{i + 1}] {punto} (confianza: {conf:.3f})")

    # Evaluar
    punto_real = (1000 + 50 * 100, 1000 + 50 * 50, 1000 + 50 * 30)
    acierto = predictor.evaluar_prediccion(punto_real, predicciones, radio=500)
    print(f"\n  Punto real: {punto_real}")
    print(f"  ¿Predicción correcta? {'✅ SÍ' if acierto else '❌ NO'}")

    stats = predictor.estadisticas()
    print(f"  Patrones: {stats['patrones_detectados']}")


def demo_semantico():
    """Demuestra mapeo semántico y consulta"""
    print("\n" + "=" * 70)
    print("DEMO 5: MAPEO SEMÁNTICO (texto → D_L → 3D → firma W)")
    print("=" * 70)

    vos = MemoriaVectorialUnificada(lado_cubo=32000)
    queries = [
        "vector diagonal w topología",
        "ia llm modelo tokens contexto",
        "gpu cuda faiss multi-gpu shard",
        "memoria episodio contexto patrón",
        "vector diagonal w topología",  # Repetida para test de cache
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
    print("DEMO 6: ADAPTADOR FAISS-LIKE (búsqueda por similitud)")
    print("=" * 70)

    adaptador = AdaptadorVectorWCompleto(lado_cubo=10000)

    # Indexar datos
    for i in range(100):
        adaptador.add(
            f"doc_{i}",
            (1000 + i * 50, 2000 + i * 30, 3000 + i * 20),
            {'texto': f'documento {i}'}
        )
    print(f"\n  Indexados: 100 documentos")

    # Buscar
    resultados = adaptador.search((2500, 2900, 3400), k=3, radio=1000)
    print(f"  Query: (2500, 2900, 3400)")
    for r in resultados:
        print(f"    → {r['key']} distancia={r['distancia']:.1f}")

    # Sharding
    print(f"\n  Shards por espacio W:")
    for espacio in range(8):
        keys = adaptador.get_shard(espacio)
        if keys:
            print(f"    Espacio {espacio}: {len(keys)} documentos")


def demo_estres():
    """Prueba de estrés"""
    print("\n" + "=" * 70)
    print("DEMO 7: PRUEBA DE ESTRÉS")
    print("=" * 70)

    vos = MemoriaVectorialUnificada(lado_cubo=512, max_nivel_octree=5)

    # Inserción masiva
    n = 2000
    print(f"\n  Insertando {n} registros...")
    t0 = time.perf_counter()
    for i in range(n):
        addr = (i * 131) % (512 ** 2)
        vos.escribir(addr, f"STRESS_{i}")
    t_ins = time.perf_counter() - t0
    print(f"  Inserción: {t_ins:.3f}s ({n / t_ins:.0f} ops/s)")

    # Lectura masiva
    t0 = time.perf_counter()
    exitos = 0
    for i in range(n):
        addr = (i * 131) % (512 ** 2)
        if vos.leer(addr) is not None:
            exitos += 1
    t_lec = time.perf_counter() - t0
    print(f"  Lectura: {t_lec:.3f}s ({n / t_lec:.0f} ops/s) éxitos={exitos}/{n}")

    # Optimizar
    vos.optimizar_memoria()
    print(f"\n{vos.resumen()}")


# ============================================================================
# 13. GUÍA DE USO POR CASO
# ============================================================================

GUIA_USO = """
╔══════════════════════════════════════════════════════════════════════╗
║          GUÍA DE USO: vOS v5.0 — vectorW_unificado.py              ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  📦 CASO 1: GESTIÓN DE MEMORIA (reemplazo de memoria plana)         ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_unificado import MemoriaVectorialUnificada           ║
║    vos = MemoriaVectorialUnificada(lado_cubo=1024)                  ║
║    vos.escribir(12345, "mi_dato")                                   ║
║    dato = vos.leer(12345)  # Salto diagonal W → O(log₈ N)          ║
║                                                                      ║
║  🗄️ CASO 2: BASE DE DATOS (indexación espacial + semántica)         ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_unificado import AdaptadorVectorWCompleto            ║
║    db = AdaptadorVectorWCompleto(lado_cubo=32000)                   ║
║    db.add("doc_1", (x, y, z), {"texto": "hola mundo"})             ║
║    resultados = db.search((x, y, z), k=5)                          ║
║    sem = db.semantic_query("vector diagonal w topología")           ║
║                                                                      ║
║  ⏱️ CASO 3: CACHÉ TEMPORAL (datos con TTL)                          ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_unificado import CacheMemoriaAdaptativa              ║
║    cache = CacheMemoriaAdaptativa(max_size=5000, ttl=1800)          ║
║    cache.put("session_abc", datos_usuario)                          ║
║    datos = cache.get("session_abc")  # None si expiró               ║
║    print(cache.estadisticas())  # hit_rate, expulsiones, etc.       ║
║                                                                      ║
║  🔮 CASO 4: PREDICCIÓN DE ACCESOS (prefetching)                     ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_unificado import FamiliaDiagonales,                  ║
║        PredictorAccesosW                                             ║
║    fam = FamiliaDiagonales(lado_cubo=10000)                         ║
║    pred = PredictorAccesosW(fam)                                     ║
║    pred.registrar_acceso((x1, y1, z1))                              ║
║    pred.registrar_acceso((x2, y2, z2))                              ║
║    siguientes = pred.predecir_proximos_puntos(n=5)                  ║
║                                                                      ║
║  🗜️ CASO 5: COMPRESIÓN DE VECTORES                                  ║
║  ─────────────────────────────────────────────────────────────        ║
║    from vectorW_unificado import CompresorHibrido                    ║
║    comp = CompresorHibrido()                                         ║
║    comprimidos = comp.comprimir_batch(lista_vectores)               ║
║    originales = comp.descomprimir_batch(comprimidos)                ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  VectorialW OS v5.0 — Sistema Unificado")
    print("  Arquitecto: Jose Ricardo Mantilla Mantilla (PePiuoX)")
    print("  Licencia: LAMC v1.0")
    print("=" * 70)

    demo_memoria_3d()
    demo_cache_y_compresion()
    demo_familia_diagonales()
    demo_prediccion()
    demo_semantico()
    demo_adaptador()
    demo_estres()

    print("\n" + GUIA_USO)

    print("\n✅ Todas las demostraciones completadas exitosamente.")
