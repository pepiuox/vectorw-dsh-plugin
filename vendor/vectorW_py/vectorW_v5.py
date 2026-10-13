"""
VectorW Enhanced v5.0 - Predicción Topológica Avanzada con Memoria Adaptativa
Arquitecto y Autor: Jose Ricaro Mantilla Mantilla (PePiuoX)
Licencia: LICENCIA DE ATRIBUCIÓN, MEJORA CONTINUA Y EXENCIÓN DE RESPONSABILIDAD (LAMC) PEPIUOX v1.0

/*
 * Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)
 * Licencia: LAMC v1.0 - https://pepiuox.org/lamc/v1.0
 *
 * Modificado por: Jose Ricardo Mantilla Mantilla (PePiuoX) - [2026]
 * Descripción:
 * MEJORAS SOBRE v4.0:
  • Markov de Orden Superior (configurable hasta orden 4)
  • Cache LRU con política de expiración temporal
  • Predicción Multi-Escala (granularidad variable)
  • Persistencia de modelos entrenados (pickle)
  • Estabilización de entropía con ventana deslizante
  • Prefetching adaptativo basado en patrón detectado
  • Métricas de confianza refinadas
"""
import math
import time
import hashlib
import itertools
import pickle
import os
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict, deque, OrderedDict
from enum import Enum
from functools import lru_cache
import threading

# Importar núcleo vOS v3.0 REAL
from vectorW import (
    VectorW,
    PrefetchVectorial,
    PatronAcceso,
    CompresorEspacial,
    BalanceadorOctree,
    NodoOctreeOptimizado,
    NúcleoVectorialOSOptimizado
)


# ============================================================
# 0. UTILIDADES MEJORADAS
# ============================================================
class LRUCache:
    """Cache con política LRU y expiración temporal"""
    def __init__(self, max_size: int = 10000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self.cache = OrderedDict()
        self.timestamps = {}
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            if key not in self.cache:
                return None
            if time.time() - self.timestamps[key] > self.ttl:
                del self.cache[key]
                del self.timestamps[key]
                return None
            self.cache.move_to_end(key)
            return self.cache[key]

    def put(self, key, value):
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            elif len(self.cache) >= self.max_size:
                oldest = next(iter(self.cache))
                del self.cache[oldest]
                del self.timestamps[oldest]
            self.cache[key] = value
            self.timestamps[key] = time.time()

    def clear(self):
        with self._lock:
            self.cache.clear()
            self.timestamps.clear()

    def size(self) -> int:
        return len(self.cache)


class EntropiaEstabilizada:
    """
    Entropía con ventana deslizante y suavizado exponencial.
    Previene fluctuaciones bruscas en muestras pequeñas.
    """
    def __init__(self, ventana: int = 100, alpha: float = 0.3):
        self.ventana = ventana
        self.alpha = alpha
        self.historial = deque(maxlen=ventana)
        self.entropia_suavizada = 0.0
        self.primer_valor = True

    def actualizar(self, distribucion: List[float]) -> float:
        """Actualiza la entropía con suavizado exponencial"""
        # Calcular entropía actual
        entropia = 0.0
        for p in distribucion:
            if p > 0:
                entropia -= p * math.log2(p)

        self.historial.append(entropia)

        if self.primer_valor:
            self.entropia_suavizada = entropia
            self.primer_valor = False
        else:
            self.entropia_suavizada = (self.alpha * entropia +
                                       (1 - self.alpha) * self.entropia_suavizada)

        return self.entropia_suavizada

    def valor(self) -> float:
        return self.entropia_suavizada


class PatronAcceso(Enum):
    """Patrones de acceso detectables con mayor granularidad"""
    ALEATORIO = "ALEATORIO"
    LINEAL = "LINEAL"
    CIRCULAR = "CIRCULAR"
    OSCILANTE = "OSCILANTE"
    CLUSTER = "CLUSTER"
    ESPIRAL = "ESPIRAL"
    FRACTAL = "FRACTAL"
    BURST = "BURST"  # Ráfagas de actividad
    ESTACIONARIO = "ESTACIONARIO"  # Sin cambios significativos


# ============================================================
# 1. VECTORW 3D MEJORADO CON MEMORIA ADAPTATIVA
# ============================================================
class VectorW3D_MemoriaAdaptativa(VectorW):
    """
    Extiende VectorW3D_AltaResolucion con:
      • Entropía estabilizada por ventana
      • Cache LRU para clasificación
      • Detección de patrones multi-escala
      • Predicción con ventana adaptativa
    """
    def __init__(self, punto_anclaje: Tuple[float, float, float],
                 theta: float, longitud: float,
                 n_espacios: int = 8,
                 ventana_entropia: int = 100,
                 id_vector: str = None,
                 cache_size: int = 5000):
        super().__init__(punto_anclaje, theta, longitud, n_espacios, id_vector)

        # Reemplazar cache simple por LRU
        self._cache_lru = LRUCache(max_size=cache_size, ttl_seconds=1800)

        # Entropía estabilizada
        self.entropia_estabilizada = EntropiaEstabilizada(ventana=ventana_entropia)

        # Historial multi-escala
        self.historial_espacios_multiescala: Dict[int, deque] = {
            escala: deque(maxlen=200 // escala)
            for escala in [1, 2, 4, 8]
        }

        # Últimas predicciones para validación
        self.ultimas_predicciones: deque = deque(maxlen=20)

    def clasificar_punto(self, punto: Tuple[float, float, float]) -> int:
        """Clasificación con cache LRU"""
        # Cache LRU
        cached = self._cache_lru.get(punto)
        if cached is not None:
            return cached

        # Calcular t
        t = self._calcular_parametro_t(punto)
        t_clamped = max(0.0, min(t, self.longitud))
        idx = int(t_clamped / self.tamano_espacio)
        idx = min(idx, self.n_espacios - 1)

        self._cache_lru.put(punto, idx)
        return idx

    def clasificar_punto_multiescala(self, punto: Tuple[float, float, float],
                                     escala: int = 1) -> int:
        """
        Clasifica a diferentes escalas de granularidad.
        escala=1: granularidad fina, escala=8: granularidad gruesa
        """
        t = self._calcular_parametro_t(punto)
        t_clamped = max(0.0, min(t, self.longitud))

        # Ajustar número de espacios por escala
        n_espacios_escala = max(2, self.n_espacios // escala)
        tamano_espacio_escala = self.longitud / n_espacios_escala

        idx = int(t_clamped / tamano_espacio_escala)
        idx = min(idx, n_espacios_escala - 1)

        # Registrar en historial multi-escala
        self.historial_espacios_multiescala[escala].append(idx)

        return idx

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        """Registro con actualización de entropía estabilizada"""
        espacio_idx = self.clasificar_punto(punto)
        t = self._calcular_parametro_t(punto)

        self.proyecciones_recientes.append({
            't': t,
            'espacio': espacio_idx,
            'timestamp': time.time(),
            'punto': punto
        })
        self.tiempos_acceso.append(time.time())

        self.histograma[espacio_idx] += 1
        self.total_proyecciones += 1

        # Actualizar entropía estabilizada
        if self.total_proyecciones % 10 == 0:  # Actualizar cada 10 accesos
            dist = self.obtener_distribucion_normalizada()
            self.entropia_estabilizada.actualizar(dist)

    def entropia_shannon(self) -> float:
        """Entropía estabilizada (más robusta)"""
        return self.entropia_estabilizada.valor()

    def predecibilidad_adaptativa(self) -> float:
        """
        Predecibilidad que se ajusta según la estabilidad de la entropía.
        Penaliza si la entropía está aún convergiendo.
        """
        entropia = self.entropia_shannon()
        entropia_max = math.log2(self.n_espacios) if self.n_espacios > 1 else 1.0

        if entropia_max == 0:
            return 0.0

        # Factor de confianza basado en número de muestras
        muestras = min(1.0, self.total_proyecciones / 200)  # 200 muestras para confianza total

        # Si hay pocas muestras, penalizar la predecibilidad
        predec_base = 1.0 - (entropia / entropia_max)
        return predec_base * muestras

    def resetear_estadisticas(self):
        """Reset con limpieza de cache LRU"""
        super().resetear_estadisticas()
        self._cache_lru.clear()
        self.entropia_estabilizada = EntropiaEstabilizada(ventana=100)

    def estadisticas(self) -> Dict:
        return {
            'id': self.id_vector,
            'theta': self.theta,
            'longitud': self.longitud,
            'n_espacios': self.n_espacios,
            'tamano_espacio': self.tamano_espacio,
            'total_proyecciones': self.total_proyecciones,
            'espacio_caliente': self.obtener_espacio_caliente(),
            'entropia_bits': self.entropia_shannon(),
            'predecibilidad_adaptativa': self.predecibilidad_adaptativa(),
            'distribucion': self.obtener_distribucion_normalizada(),
            'cache_usage': f"{self._cache_lru.size()}/{self._cache_lru.max_size}"
        }


# ============================================================
# 2. VECTORW 4D FIRMA CON PERSISTENCIA
# ============================================================
class VectorW4D_FirmaPersistente:
    """
    Versión con persistencia de modelos entrenados.
    """
    def __init__(self, nucleo_vos: NúcleoVectorialOSOptimizado,
                 lado_cubo: float = 32000.0,
                 n_espacios_por_diagonal: int = 8,
                 modelo_path: Optional[str] = None):
        self.nucleo = nucleo_vos
        self.lado = lado_cubo
        self.centro = (lado_cubo/2, lado_cubo/2, lado_cubo/2)
        self.n_espacios = n_espacios_por_diagonal
        self.modelo_path = modelo_path

        # Constantes vOS v3.0 reales
        self.K_x = nucleo_vos.K_x
        self.K_y = nucleo_vos.K_y
        self.K_z = nucleo_vos.K_z
        self.theta_base = nucleo_vos.theta
        self.R_nivel = nucleo_vos.R_nivel

        self.longitud_diagonal = lado_cubo * math.sqrt(3)

        # Diagonales con memoria adaptativa
        self.diagonales: Dict[str, VectorW3D_MemoriaAdaptativa] = {}
        self._crear_diagonales()

        # Cache LRU para firmas
        self.cache_firmas = LRUCache(max_size=10000, ttl_seconds=1800)

        # Estadísticas
        self.stats = {
            'firmas_calculadas': 0,
            'tiempo_total_ms': 0.0,
            'aciertos_cache': 0
        }

        # Cargar modelo si existe
        if modelo_path and os.path.exists(modelo_path):
            self.cargar_modelo(modelo_path)

    def _crear_diagonales(self):
        """Crea las 4 diagonales con memoria adaptativa"""
        configuraciones = [
            ("W1_BASE", 0.0, (0.0, 0.0, self.centro[2])),
            ("W2_90", math.pi/2, (self.lado, 0.0, self.centro[2])),
            ("W3_180", math.pi, (self.lado, self.lado, self.centro[2])),
            ("W4_270", 3*math.pi/2, (0.0, self.lado, self.centro[2]))
        ]

        for nombre, delta_theta, anclaje in configuraciones:
            diagonal = VectorW3D_MemoriaAdaptativa(
                punto_anclaje=anclaje,
                theta=self.theta_base + delta_theta,
                longitud=self.longitud_diagonal,
                n_espacios=self.n_espacios,
                id_vector=nombre,
                ventana_entropia=100
            )
            self.diagonales[nombre] = diagonal
            self.nucleo.cache_vectores_w[nombre] = diagonal

    def calcular_firma(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float, float]:
        """Firma con cache LRU"""
        cached = self.cache_firmas.get(punto)
        if cached is not None:
            self.stats['aciertos_cache'] += 1
            return cached

        t0 = time.perf_counter()
        firma = tuple(d.parametro_t(punto) for d in self.diagonales.values())

        self.cache_firmas.put(punto, firma)
        self.stats['firmas_calculadas'] += 1
        self.stats['tiempo_total_ms'] += (time.perf_counter() - t0) * 1000

        return firma

    def calcular_firma_multiescala(self, punto: Tuple[float, float, float],
                                   escala: int = 1) -> Tuple:
        """Firma a diferentes escalas de granularidad"""
        return tuple(d.clasificar_punto_multiescala(punto, escala)
                     for d in self.diagonales.values())

    def guardar_modelo(self, path: str):
        """Guarda el estado entrenado a disco"""
        data = {
            'diagonales': {
                nombre: {
                    'histograma': d.histograma,
                    'total_proyecciones': d.total_proyecciones,
                    'historial_espacios': list(d.historial_espacios_multiescala[1])
                }
                for nombre, d in self.diagonales.items()
            },
            'n_espacios': self.n_espacios,
            'timestamp': time.time()
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)

    def cargar_modelo(self, path: str):
        """Carga un modelo guardado"""
        with open(path, 'rb') as f:
            data = pickle.load(f)

        for nombre, diag_data in data['diagonales'].items():
            if nombre in self.diagonales:
                diagonal = self.diagonales[nombre]
                diagonal.histograma = diag_data['histograma']
                diagonal.total_proyecciones = diag_data['total_proyecciones']
                # Reconstruir historial
                for espacio in diag_data['historial_espacios']:
                    diagonal.historial_espacios_multiescala[1].append(espacio)

    def estadisticas(self) -> Dict:
        return {
            'n_diagonales': len(self.diagonales),
            'n_espacios_por_diagonal': self.n_espacios,
            'resolucion_topologica_total': len(self.diagonales) * self.n_espacios,
            'longitud_diagonal': self.longitud_diagonal,
            'predecibilidad_promedio': self.predecibilidad_promedio(),
            'entropia_promedio': self.entropia_promedio(),
            'firmas_cache': self.cache_firmas.size(),
            'aciertos_cache': self.stats['aciertos_cache'],
            'por_diagonal': {
                nombre: d.estadisticas()
                for nombre, d in self.diagonales.items()
            }
        }

    # Métodos delegados
    def predecibilidad_promedio(self) -> float:
        return sum(d.predecibilidad_adaptativa() for d in self.diagonales.values()) / 4

    def entropia_promedio(self) -> float:
        return sum(d.entropia_shannon() for d in self.diagonales.values()) / 4

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        for diagonal in self.diagonales.values():
            diagonal.registrar_acceso(punto)

    def clasificar_en_espacios_4d(self, punto: Tuple[float, float, float]) -> Tuple[int, int, int, int]:
        return tuple(d.clasificar_punto(punto) for d in self.diagonales.values())

    def diagonal_mas_predecible(self) -> VectorW3D_MemoriaAdaptativa:
        return max(self.diagonales.values(), key=lambda d: d.predecibilidad_adaptativa())


# ============================================================
# 3. PREDICTOR MARKOV DE ORDEN SUPERIOR
# ============================================================
class PredictorMarkovOrdenSuperior:
    """
    Predictor basado en cadenas de Markov de orden configurable.

    Orden 1: P(x_{t+1} | x_t)
    Orden 2: P(x_{t+1} | x_t, x_{t-1})
    Orden 3: P(x_{t+1} | x_t, x_{t-1}, x_{t-2})
    Orden 4: P(x_{t+1} | x_t, x_{t-1}, x_{t-2}, x_{t-3})

    Mayor orden = más precisión pero más datos necesarios.
    """
    def __init__(self, orden: int = 2, suavizado_laplace: float = 0.1):
        self.orden = orden
        self.suavizado = suavizado_laplace
        self.transiciones: Dict[Tuple, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.historial: deque = deque(maxlen=10000)

    def registrar(self, estado: int):
        """Registra un estado en el historial"""
        self.historial.append(estado)

        if len(self.historial) > self.orden:
            # Crear secuencia de orden 'orden'
            secuencia = tuple(self.historial[-self.orden-1:-1])
            siguiente = self.historial[-1]
            self.transiciones[secuencia][siguiente] += 1

    def predecir(self) -> Optional[int]:
        """Predice el próximo estado usando el historial actual"""
        if len(self.historial) < self.orden:
            return None

        secuencia = tuple(self.historial[-self.orden:])
        trans = self.transiciones.get(secuencia, {})

        if not trans:
            # Intentar con orden menor (backoff)
            for orden_menor in range(self.orden - 1, 0, -1):
                if len(self.historial) >= orden_menor:
                    secuencia_menor = tuple(self.historial[-orden_menor:])
                    trans_menor = self.transiciones.get(secuencia_menor, {})
                    if trans_menor:
                        # Suavizar con el contexto parcial
                        return max(trans_menor.items(), key=lambda x: x[1])[0]
            return None

        # Aplicar suavizado de Laplace para manejar estados no vistos
        total = sum(trans.values()) + self.suavizado * len(trans)
        probs = {k: (v + self.suavizado) / total for k, v in trans.items()}
        return max(probs.items(), key=lambda x: x[1])[0]

    def probabilidad(self, estado: int) -> float:
        """Probabilidad del próximo estado"""
        if len(self.historial) < self.orden:
            return 0.0

        secuencia = tuple(self.historial[-self.orden:])
        trans = self.transiciones.get(secuencia, {})
        total = sum(trans.values()) + self.suavizado * len(trans)
        return (trans.get(estado, 0) + self.suavizado) / total if total > 0 else 0.0

    def entropia_condicional(self) -> float:
        """Entropía condicional del modelo"""
        entropia = 0.0
        for secuencia, trans in self.transiciones.items():
            total = sum(trans.values())
            for count in trans.values():
                p = count / total
                entropia -= p * math.log2(p)
        return entropia / max(1, len(self.transiciones))

    def reset(self):
        self.transiciones.clear()
        self.historial.clear()


# ============================================================
# 4. PREDICTOR W TOPOLOGICO AVANZADO
# ============================================================
class PredictorW_TopologicoAvanzado:
    """
    Predictor mejorado con:
      • Markov de orden superior
      • Análisis multi-escala
      • Prefetching adaptativo según patrón
      • Confianza bayesiana
    """
    def __init__(self, firma_4d: VectorW4D_FirmaPersistente,
                 orden_markov: int = 2,
                 ventana_prediccion: int = 50):
        self.firma_4d = firma_4d
        self.orden_markov = orden_markov
        self.ventana_prediccion = ventana_prediccion

        # Predictores Markov por diagonal
        self.predictores_markov: Dict[str, PredictorMarkovOrdenSuperior] = {
            nombre: PredictorMarkovOrdenSuperior(orden=orden_markov)
            for nombre in firma_4d.diagonales.keys()
        }

        # Historial de espacios por diagonal
        self.historial_espacios: Dict[str, deque] = {
            nombre: deque(maxlen=500)
            for nombre in firma_4d.diagonales.keys()
        }

        # Último espacio por diagonal
        self.ultimo_espacio: Dict[str, int] = {
            nombre: -1 for nombre in firma_4d.diagonales.keys()
        }

        # Historial de parámetros t
        self.historial_t: Dict[str, deque] = {
            nombre: deque(maxlen=200)
            for nombre in firma_4d.diagonales.keys()
        }

        # Métricas del predictor
        self.predicciones_realizadas = 0
        self.aciertos = 0
        self.fallos = 0
        self.historial_precision = deque(maxlen=100)

        # Detección de patrones
        self.patron_actual: Dict[str, PatronAcceso] = {
            nombre: PatronAcceso.ALEATORIO
            for nombre in firma_4d.diagonales.keys()
        }

        # Patrones detectados históricamente
        self.historial_patrones: Dict[str, List[PatronAcceso]] = {
            nombre: []
            for nombre in firma_4d.diagonales.keys()
        }

    def registrar_acceso(self, punto: Tuple[float, float, float]):
        """Registro con actualización de Markov"""
        for nombre, diagonal in self.firma_4d.diagonales.items():
            espacio = diagonal.clasificar_punto(punto)
            t = diagonal.parametro_t(punto)

            # Actualizar Markov
            self.predictores_markov[nombre].registrar(espacio)

            # Actualizar historiales
            self.historial_espacios[nombre].append(espacio)
            self.historial_t[nombre].append(t)
            self.ultimo_espacio[nombre] = espacio

        self.firma_4d.registrar_acceso(punto)

        # Actualizar detección de patrones (cada 10 accesos)
        if len(self.historial_espacios[nombre]) % 10 == 0:
            for nombre in self.firma_4d.diagonales.keys():
                patron = self._detectar_patron_multiescala(nombre)
                self.patron_actual[nombre] = patron
                self.historial_patrones[nombre].append(patron)

    def predecir_siguiente_espacio(self, nombre_diagonal: str) -> Optional[int]:
        """Predicción usando Markov de orden superior"""
        return self.predictores_markov[nombre_diagonal].predecir()

    def predecir_siguiente_espacio_confianza(self, nombre_diagonal: str) -> Tuple[Optional[int], float]:
        """Predicción con nivel de confianza"""
        pred = self.predecir_siguiente_espacio(nombre_diagonal)
        if pred is None:
            return None, 0.0

        prob = self.predictores_markov[nombre_diagonal].probabilidad(pred)
        confianza = prob * self.firma_4d.diagonales[nombre_diagonal].predecibilidad_adaptativa()

        return pred, confianza

    def predecir_proximos_puntos_adaptativo(self, n: int = 5) -> List[Tuple[Tuple[float, float, float], float]]:
        """
        Predicción adaptativa que cambia estrategia según el patrón detectado.
        """
        candidatos = defaultdict(float)

        for nombre, diagonal in self.firma_4d.diagonales.items():
            patron = self.patron_actual.get(nombre, PatronAcceso.ALEATORIO)
            confianza_base = diagonal.predecibilidad_adaptativa()

            # Estrategia según patrón
            if patron == PatronAcceso.LINEAL:
                # Predicción por tendencia (más confiable para lineal)
                t_pred = self._predecir_tendencia_lineal(nombre, pasos=1)
                if t_pred is not None:
                    punto = diagonal.punto_en_linea(t_pred)
                    candidatos[punto] += confianza_base * 0.7
                    # Vecinos cercanos
                    for delta in [-1, 1]:
                        punto_vecino = diagonal.punto_en_linea(t_pred + delta * diagonal.tamano_espacio * 0.5)
                        candidatos[punto_vecino] += confianza_base * 0.15

            elif patron == PatronAcceso.CIRCULAR:
                # Predicción usando vecinos cíclicos
                espacio_actual = self.ultimo_espacio[nombre]
                if espacio_actual >= 0:
                    # Predice el siguiente en el ciclo
                    siguiente = (espacio_actual + 1) % diagonal.n_espacios
                    punto = diagonal.punto_central_espacio(siguiente)
                    candidatos[punto] += confianza_base * 0.5
                    # También el anterior (posible ciclo inverso)
                    anterior = (espacio_actual - 1) % diagonal.n_espacios
                    punto_anterior = diagonal.punto_central_espacio(anterior)
                    candidatos[punto_anterior] += confianza_base * 0.3

            elif patron == PatronAcceso.CLUSTER:
                # Predicción centrada en el punto caliente
                espacio_caliente = diagonal.obtener_espacio_caliente()
                if espacio_caliente >= 0:
                    punto = diagonal.punto_central_espacio(espacio_caliente)
                    candidatos[punto] += confianza_base * 0.6
                    # Vecinos del punto caliente
                    for vecino in diagonal.obtener_vecinos_espaciales(espacio_caliente, radio=1):
                        punto_vecino = diagonal.punto_central_espacio(vecino)
                        candidatos[punto_vecino] += confianza_base * 0.2

            elif patron == PatronAcceso.OSCILANTE:
                # Predicción alternante
                espacio_actual = self.ultimo_espacio[nombre]
                if espacio_actual >= 0:
                    # Buscar el espacio más frecuente que no sea el actual
                    trans = self.predictores_markov[nombre].transiciones
                    # Buscar destino más probable desde el estado actual
                    secuencia = tuple(self.historial_espacios[nombre])[-self.orden_markov:]
                    if secuencia in trans:
                        destinos = trans[secuencia]
                        if destinos:
                            destino_mas_probable = max(destinos.items(), key=lambda x: x[1])[0]
                            punto = diagonal.punto_central_espacio(destino_mas_probable)
                            candidatos[punto] += confianza_base * 0.6

            else:  # ALEATORIO o desconocido
                # Usar Markov de orden superior
                pred = self.predecir_siguiente_espacio(nombre)
                if pred is not None:
                    punto = diagonal.punto_central_espacio(pred)
                    candidatos[punto] += confianza_base * 0.4
                    # Vecinos con menor peso
                    for vecino in diagonal.obtener_vecinos_espaciales(pred, radio=1):
                        punto_vecino = diagonal.punto_central_espacio(vecino)
                        candidatos[punto_vecino] += confianza_base * 0.2

            # Siempre añadir predicción por tendencia como respaldo
            t_pred = self._predecir_tendencia_ponderada(nombre, pasos=1)
            if t_pred is not None:
                punto = diagonal.punto_en_linea(t_pred)
                candidatos[punto] += confianza_base * 0.15

        # Ordenar y limitar
        resultados = sorted(candidatos.items(), key=lambda x: x[1], reverse=True)
        self.predicciones_realizadas += 1
        return resultados[:n]

    def _predecir_tendencia_lineal(self, nombre_diagonal: str, pasos: int = 1) -> Optional[float]:
        """Predicción por regresión lineal simple"""
        historial = list(self.historial_t[nombre_diagonal])
        if len(historial) < 3:
            return None

        # Regresión lineal simple
        n = len(historial)
        x = list(range(n))
        y = historial

        # Calcular pendiente y intercepto
        x_mean = sum(x) / n
        y_mean = sum(y) / n

        numerador = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominador = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominador == 0:
            return None

        pendiente = numerador / denominador
        intercepto = y_mean - pendiente * x_mean

        return intercepto + pendiente * (n + pasos - 1)

    def _predecir_tendencia_ponderada(self, nombre_diagonal: str, pasos: int = 1) -> Optional[float]:
        """Predicción con ponderación exponencial (más peso a datos recientes)"""
        historial = list(self.historial_t[nombre_diagonal])
        if len(historial) < 3:
            return None

        # Ponderación exponencial
        alfa = 0.3
        pesos = [alfa * (1 - alfa) ** i for i in range(len(historial) - 1, -1, -1)]
        pesos = [p / sum(pesos) for p in pesos]

        # Suavizado exponencial simple
        ultimo_valor = historial[-1]
        tendencia = sum(pesos[i] * (historial[i] - historial[max(0, i-1)])
                        for i in range(1, len(historial)))

        return ultimo_valor + pasos * tendencia

    def _detectar_patron_multiescala(self, nombre_diagonal: str) -> PatronAcceso:
        """
        Detección de patrones usando múltiples escalas para mayor robustez.
        """
        diagonal = self.firma_4d.diagonales[nombre_diagonal]
        historial = list(self.historial_espacios[nombre_diagonal])

        if len(historial) < 5:
            return PatronAcceso.ALEATORIO

        # Análisis a escala fina (espacios individuales)
        dist = diagonal.obtener_distribucion_normalizada()
        max_prob = max(dist) if dist else 0

        # CLUSTER: alta concentración
        if max_prob > 0.6:
            return PatronAcceso.CLUSTER

        # BURST: ráfagas de actividad (detección por varianza en ventanas)
        if len(historial) >= 20:
            ventanas = [historial[i:i+5] for i in range(0, len(historial)-5, 5)]
            varianzas = [len(set(v)) for v in ventanas]
            if max(varianzas) - min(varianzas) > 3:
                return PatronAcceso.BURST

        # Análisis de diferencias
        deltas = [historial[i+1] - historial[i] for i in range(len(historial)-1)]
        if not deltas:
            return PatronAcceso.ALEATORIO

        positivos = sum(1 for d in deltas if d > 0)
        negativos = sum(1 for d in deltas if d < 0)
        ceros = sum(1 for d in deltas if d == 0)
        total = len(deltas)

        # LINEAL: movimiento consistente en una dirección
        if positivos / total > 0.75:
            # Verificar que no sea cíclico
            if len(set(historial)) > diagonal.n_espacios // 2:
                return PatronAcceso.LINEAL

        if negativos / total > 0.75:
            if len(set(historial)) > diagonal.n_espacios // 2:
                return PatronAcceso.LINEAL

        # OSCILANTE: alternancia entre 2 valores
        if len(set(historial)) == 2:
            return PatronAcceso.OSCILANTE

        # CIRCULAR: patrón cíclico
        if len(historial) >= 8:
            # Buscar periodicidad
            for periodo in [3, 4, 5, 6, 7, 8]:
                if len(historial) >= periodo * 2:
                    ciclos = 0
                    for i in range(len(historial) - periodo):
                        if historial[i] == historial[i + periodo]:
                            ciclos += 1
                    if ciclos > len(historial) * 0.4:
                        return PatronAcceso.CIRCULAR

        # ESPIRAL: movimiento en espiral (patrón que se expande o contrae)
        if len(historial) >= 10:
            # Detectar si hay un movimiento que se aleja o acerca al centro
            centro_espacio = diagonal.n_espacios // 2
            distancias = [abs(e - centro_espacio) for e in historial[-10:]]
            if len(set(distancias)) > 3:
                # Verificar si las distancias tienden a aumentar o disminuir
                if distancias[-1] > distancias[0] * 1.5:
                    return PatronAcceso.ESPIRAL

        # FRACTAL: patrón autosimilar a diferentes escalas
        if len(historial) >= 20:
            # Verificar si el patrón se repite a diferentes escalas
            escala_2 = diagonal.clasificar_punto_multiescala(
                diagonal.punto_central_espacio(historial[-1]), escala=2
            )
            escala_4 = diagonal.clasificar_punto_multiescala(
                diagonal.punto_central_espacio(historial[-1]), escala=4
            )
            # Si las clasificaciones en diferentes escalas son consistentes
            if escala_2 == escala_4 // 2:
                return PatronAcceso.FRACTAL

        return PatronAcceso.ALEATORIO

    def evaluar_prediccion_avanzada(self, punto_real: Tuple[float, float, float],
                                    predicciones: List[Tuple],
                                    radio_espacio: float = None,
                                    tolerancia_adaptativa: bool = True) -> bool:
        """Evaluación con tolerancia adaptativa según confianza"""
        if radio_espacio is None:
            diagonal_ppal = self.firma_4d.diagonal_mas_predecible()
            radio_espacio = diagonal_ppal.tamano_espacio

        # Si el punto real está en alguna predicción
        for punto_pred, prob in predicciones:
            dist = math.sqrt(sum((a-b)**2 for a, b in zip(punto_real, punto_pred)))

            # Tolerancia adaptativa: si la probabilidad es alta, tolerancia más estricta
            tolerancia = radio_espacio * (1 - prob * 0.3) if tolerancia_adaptativa else radio_espacio

            if dist <= tolerancia:
                self.aciertos += 1
                self.historial_precision.append(1)
                return True

        self.fallos += 1
        self.historial_precision.append(0)
        return False

    def precision_ajustada(self) -> float:
        """Precisión con suavizado exponencial"""
        if not self.historial_precision:
            return 0.0

        alfa = 0.1
        precision = 0.0
        for val in reversed(self.historial_precision):
            precision = precision * (1 - alfa) + val * alfa
        return precision

    def estadisticas(self) -> Dict:
        return {
            'orden_markov': self.orden_markov,
            'predicciones_realizadas': self.predicciones_realizadas,
            'aciertos': self.aciertos,
            'fallos': self.fallos,
            'precision_bruta': f"{self.aciertos / max(1, self.aciertos + self.fallos):.2%}",
            'precision_ajustada': f"{self.precision_ajustada():.2%}",
            'patrones_actuales': {
                nombre: patron.value
                for nombre, patron in self.patron_actual.items()
            },
            'confianza_promedio': f"{self._confianza_promedio():.2%}",
            'entropia_condicional_promedio': sum(
                p.entropia_condicional() for p in self.predictores_markov.values()
            ) / max(1, len(self.predictores_markov))
        }

    def _confianza_promedio(self) -> float:
        """Confianza promedio en las predicciones"""
        confianzas = []
        for nombre in self.firma_4d.diagonales.keys():
            _, conf = self.predecir_siguiente_espacio_confianza(nombre)
            confianzas.append(conf)
        return sum(confianzas) / max(1, len(confianzas))


# ============================================================
# 5. NÚCLEO MEJORADO v5.0
# ============================================================
class NucleoVectorialOS_Avanzado(NúcleoVectorialOSOptimizado):
    """
    Versión avanzada con todas las mejoras:
      • Memoria adaptativa (cache LRU, entropía estabilizada)
      • Markov de orden superior
      • Predicción multi-escala
      • Persistencia de modelos
      • Detección de patrones avanzada
    """
    def __init__(self, n_espacios: int = 8,
                 orden_markov: int = 2,
                 modelo_path: Optional[str] = None,
                 **kwargs):
        super().__init__(**kwargs)

        # Sistema de alta resolución con persistencia
        self.firma_4d = VectorW4D_FirmaPersistente(
            nucleo_vos=self,
            lado_cubo=32000.0,
            n_espacios_por_diagonal=n_espacios,
            modelo_path=modelo_path
        )

        # Predictor topológico avanzado
        self.predictor = PredictorW_TopologicoAvanzado(
            self.firma_4d,
            orden_markov=orden_markov
        )

        # Índice de episodios por firma W
        self.indice_firmas: Dict[Tuple, str] = {}

        # Métricas adicionales
        self.metricas_alta_resolucion = {
            'accesos_con_firma': 0,
            'predicciones_acertadas': 0,
            'predicciones_totales': 0,
            'cache_aciertos': 0,
            'cache_fallos': 0
        }

        # Hilo de auto-entrenamiento
        self._training_thread = None
        self._training_running = False

    def acceso_inteligente_alta_resolucion(self, direccion: int) -> Optional[Dict]:
        """Acceso inteligente mejorado"""
        inicio_tiempo = time.time()
        self.metricas['accesos'] += 1
        self.metricas_alta_resolucion['accesos_con_firma'] += 1

        # PASO 1: D_L → coords 3D
        coords = self.operador_eje_z_optimizado(direccion)

        # PASO 2: coords 3D → firma W 4D
        firma = self.firma_4d.calcular_firma_normalizada(coords)
        espacios_4d = self.firma_4d.clasificar_en_espacios_4d(coords)

        # PASO 3: Evaluar predicción anterior
        if self.metricas_alta_resolucion['predicciones_totales'] > 0:
            predicciones = self.predictor.predecir_proximos_puntos_adaptativo(n=3)
            acierto = self.predictor.evaluar_prediccion_avanzada(coords, predicciones)
            self.metricas_alta_resolucion['predicciones_totales'] += 1
            if acierto:
                self.metricas_alta_resolucion['predicciones_acertadas'] += 1

        # PASO 4: Registrar acceso
        self.predictor.registrar_acceso(coords)

        # PASO 5: Buscar en Octree
        n_id, n_info = self.raiz_espacial.buscar_nodo(coords)

        if n_info:
            self.metricas['aciertos_cache'] += 1
            self.metricas_alta_resolucion['cache_aciertos'] += 1
            resultado = {
                'id': n_id,
                'info': n_info,
                'coords': coords,
                'firma_w4d': firma,
                'espacios_w4d': espacios_4d,
                'predicciones_futuro': self.predictor.predecir_proximos_puntos_adaptativo(n=3),
                'patron_actual': self.predictor.patron_actual
            }
        else:
            self.metricas['fallos_cache'] += 1
            self.metricas_alta_resolucion['cache_fallos'] += 1
            resultado = None

        # Actualizar métricas
        tiempo = time.time() - inicio_tiempo
        self.metricas['tiempo_promedio_acceso'] = (
            (self.metricas['tiempo_promedio_acceso'] * (self.metricas['accesos'] - 1) + tiempo) /
            self.metricas['accesos']
        )

        return resultado

    def prefetch_topologico_avanzado(self, n_puntos: int = 5) -> List[Tuple[Tuple, float]]:
        """Prefetching adaptativo según patrón detectado"""
        return self.predictor.predecir_proximos_puntos_adaptativo(n=n_puntos)

    def entrenar_background(self, duracion_segundos: int = 60):
        """Entrenamiento en background para mejorar el modelo"""
        if self._training_running:
            return

        self._training_running = True

        def entrenar():
            import random
            inicio = time.time()
            while self._training_running and (time.time() - inicio) < duracion_segundos:
                # Generar puntos aleatorios con diferentes patrones
                for _ in range(10):
                    # Mezclar diferentes patrones para enriquecer el modelo
                    if random.random() < 0.5:
                        # Patrón lineal
                        t = random.uniform(0, 32000)
                        punto = (t, t * 0.5, t * 0.2 + 5000)
                    else:
                        # Patrón cluster
                        centro = (random.uniform(0, 32000),
                                 random.uniform(0, 32000),
                                 random.uniform(0, 800000))
                        punto = tuple(c + random.gauss(0, 1000) for c in centro)
                    self.predictor.registrar_acceso(punto)
                time.sleep(0.1)

        self._training_thread = threading.Thread(target=entrenar, daemon=True)
        self._training_thread.start()

    def detener_entrenamiento(self):
        self._training_running = False
        if self._training_thread:
            self._training_thread.join(timeout=2)

    def guardar_modelo(self, path: str):
        """Guarda el modelo entrenado"""
        self.firma_4d.guardar_modelo(path)

    def cargar_modelo(self, path: str):
        """Carga un modelo guardado"""
        self.firma_4d.cargar_modelo(path)

    def estadisticas_alta_resolucion(self) -> Dict:
        """Estadísticas completas del sistema"""
        precision_pred = (
            self.metricas_alta_resolucion['predicciones_acertadas'] /
            max(1, self.metricas_alta_resolucion['predicciones_totales'])
        )

        return {
            'metricas_vos_originales': self.metricas,
            'metricas_alta_resolucion': {
                **self.metricas_alta_resolucion,
                'precision_prediccion': f"{precision_pred:.2%}",
                'ratio_cache': f"{self.metricas_alta_resolucion['cache_aciertos'] / max(1, self.metricas_alta_resolucion['cache_aciertos'] + self.metricas_alta_resolucion['cache_fallos']):.2%}"
            },
            'firma_4d': self.firma_4d.estadisticas(),
            'predictor': self.predictor.estadisticas(),
            'episodios_indexados_por_firma': len(self.indice_firmas)
        }


# ============================================================
# 6. DEMOSTRACIÓN COMPLETA v5.0
# ============================================================
def demo_avanzada():
    """Demuestra todas las mejoras de v5.0"""
    print("=" * 70)
    print("DEMO: VectorW Enhanced v5.0 - PREDICCIÓN AVANZADA")
    print("=" * 70)

    # Crear núcleo mejorado
    nucleo = NucleoVectorialOS_Avanzado(
        n_espacios=8,
        orden_markov=2,
        modelo_path="modelo_v5.pkl"
    )

    print(f"\n📐 CONFIGURACIÓN:")
    print(f"   • Orden Markov: {nucleo.predictor.orden_markov}")
    print(f"   • Espacios por diagonal: {nucleo.firma_4d.n_espacios}")
    print(f"   • Resolución total: {nucleo.firma_4d.n_espacios * 4} regiones")

    # Simular secuencia con patrón mixto
    print(f"\n📝 SIMULANDO SECUENCIA DE ACCESOS (patrón mixto)...")
    print("-" * 70)

    # Generar direcciones con diferentes patrones
    import random
    random.seed(1234)

    # Fase 1: Patrón lineal (10 accesos)
    direcciones_lin = [7458921 + i * 800 for i in range(15)]

    # Fase 2: Patrón cluster (10 accesos)
    base = 7458921 + 15 * 800
    direcciones_cluster = [base + random.randint(-1000, 1000) for _ in range(15)]

    # Fase 3: Patrón oscilante (10 accesos)
    base2 = base + 5000
    direcciones_osc = [base2 + (i % 2) * 2000 for i in range(15)]

    todas_direcciones = direcciones_lin + direcciones_cluster + direcciones_osc

    # Iniciar entrenamiento en background
    nucleo.entrenar_background(duracion_segundos=5)

    resultados = []
    for i, dir_addr in enumerate(todas_direcciones, 1):
        resultado = nucleo.acceso_inteligente_alta_resolucion(dir_addr)

        if resultado:
            firma = resultado['firma_w4d']
            espacios = resultado['espacios_w4d']
            patron = resultado.get('patron_actual', {})

            print(f"[{i:2d}] D_L={dir_addr:<10} "
                  f"3D=({resultado['coords'][0]:.0f},"
                  f"{resultado['coords'][1]:.0f},"
                  f"{resultado['coords'][2]:.0f}) "
                  f"patrón={patron.get('W1_BASE', 'N/A').value if 'W1_BASE' in patron else 'N/A'}")
            resultados.append(resultado)

    nucleo.detener_entrenamiento()

    # Estadísticas finales
    print("\n" + "=" * 70)
    print("📊 ESTADÍSTICAS AVANZADAS")
    print("=" * 70)
    stats = nucleo.estadisticas_alta_resolucion()

    print(f"\n🎯 PRECISIÓN DEL PREDICTOR: {stats['metricas_alta_resolucion']['precision_prediccion']}")
    print(f"   Aciertos: {stats['metricas_alta_resolucion']['predicciones_acertadas']}/"
          f"{stats['metricas_alta_resolucion']['predicciones_totales']}")

    print(f"\n📐 PREDECIBILIDAD POR DIAGONAL:")
    for nombre, diag_stats in stats['firma_4d']['por_diagonal'].items():
        print(f"   • {nombre}: predec={diag_stats['predecibilidad_adaptativa']:.2%}, "
              f"entropía={diag_stats['entropia_bits']:.3f} bits")

    print(f"\n🧠 PATRONES DETECTADOS:")
    for nombre, patron in stats['predictor']['patrones_actuales'].items():
        print(f"   • {nombre}: {patron}")

    print(f"\n🔮 PREDICCIONES ADAPTATIVAS:")
    predicciones = nucleo.prefetch_topologico_avanzado(n_puntos=5)
    for i, (punto, prob) in enumerate(predicciones, 1):
        print(f"   {i}. Punto {punto} con probabilidad {prob:.2%}")

    # Guardar modelo entrenado
    nucleo.guardar_modelo("modelo_v5_entrenado.pkl")
    print(f"\n💾 Modelo guardado en 'modelo_v5_entrenado.pkl'")

    print(f"\n📈 MÉTRICAS vOS v3.0 ORIGINALES:")
    for k, v in stats['metricas_vos_originales'].items():
        print(f"   • {k}: {v}")

    print(f"\n📈 MÉTRICAS v5.0 MEJORADAS:")
    for k, v in stats['metricas_alta_resolucion'].items():
        if not k.endswith('_aciertos') and not k.endswith('_fallos'):
            print(f"   • {k}: {v}")


def demo_comparacion_orden_markov():
    """Compara diferentes órdenes de Markov"""
    print("\n" + "=" * 70)
    print("DEMO: COMPARACIÓN DE ÓRDENES DE MARKOV")
    print("=" * 70)

    ordenes = [1, 2, 3, 4]
    resultados = []

    for orden in ordenes:
        print(f"\n📊 Probando orden {orden}...")
        nucleo = NucleoVectorialOS_Avanzado(n_espacios=8, orden_markov=orden)

        # Secuencia de prueba con patrón complejo
        import random
        random.seed(42)

        # Patrón con periodicidad
        direcciones = []
        for i in range(50):
            if i % 10 < 5:
                direcciones.append(100000 + i * 100)
            else:
                direcciones.append(100000 + (i - 5) * 100)

        for dir_addr in direcciones:
            nucleo.acceso_inteligente_alta_resolucion(dir_addr)

        stats = nucleo.estadisticas_alta_resolucion()
        precision = float(stats['metricas_alta_resolucion']['precision_prediccion'].rstrip('%')) / 100
        resultados.append((orden, precision))

    print("\n" + "-" * 70)
    print(f"{'Orden Markov':<15} {'Precisión':<12} {'Mejora vs orden anterior':<25}")
    print("-" * 70)

    mejora_anterior = 0
    for i, (orden, precision) in enumerate(resultados):
        mejora = precision - mejora_anterior if i > 0 else 0
        print(f"{orden:<15} {precision:.2%}        {mejora:+.2%}")
        mejora_anterior = precision

    print("\n💡 Orden 2-3 ofrecen mejor balance precisión/datos")
    print("   Orden 4 requiere muchos datos para ser efectivo")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  VectorW Enhanced v5.0 - PREDICCIÓN TOPOLÓGICA AVANZADA")
    print("  Extensión de vOS v3.0 con Memoria Adaptativa")
    print("=" * 70)

    demo_avanzada()
    demo_comparacion_orden_markov()

    print("\n" + "=" * 70)
    print("✓ DEMOSTRACIÓN COMPLETADA")
    print("  Mejoras implementadas:")
    print("  • Markov de orden superior (configurable 1-4)")
    print("  • Cache LRU con expiración temporal")
    print("  • Entropía estabilizada con ventana deslizante")
    print("  • Predicción multi-escala")
    print("  • Persistencia de modelos entrenados")
    print("  • Prefetching adaptativo según patrón detectado")
    print("  • Entrenamiento en background")
    print("=" * 70)
