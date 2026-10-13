"""
VectorialW OS (vOS) - Núcleo Matemático Optimizado v3.0
Arquitecto y Autor: Jose Ricaro Mantilla Mantilla (PePiuoX)
Licencia: LICENCIA DE ATRIBUCIÓN, MEJORA CONTINUA Y EXENCIÓN DE RESPONSABILIDAD (LAMC) PEPIUOX v1.0

/*
 * Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)
 * Licencia: LAMC v1.0 - https://pepiuox.org/lamc/v1.0
 *
 * Modificado por: Jose Ricardo Mantilla Mantilla (PePiuoX) - [2026]
 * Descripción:
 * Status: Implementación Avanzada con Sistema Vectorial W y Optimizaciones Espaciales
"""

import math
import json
import os
import heapq
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# =============================================
# SISTEMA DE VECTORES ESPACIALES W
# =============================================

@dataclass
class VectorW:
    """
    Vector W: Línea vectorial generada en un ángulo aplicado para la 
    ubicación de datos en el espacio 3D.
    """
    punto_anclaje: Tuple[float, float, float]
    theta: float  # Ángulo en radianes
    longitud: float
    id_vector: str = field(default_factory=lambda: f"VEC_{int(time.time())}")
    
    def __post_init__(self):
        self._calcular_extremos()
        self._calcular_direccion()
        
    def _calcular_extremos(self):
        """Calcula los puntos extremos del vector W"""
        self.punto_inicio = self.punto_anclaje
        self.punto_fin = (
            self.punto_anclaje[0] + self.longitud * math.cos(self.theta),
            self.punto_anclaje[1] + self.longitud * math.sin(self.theta),
            self.punto_anclaje[2]
        )
        
    def _calcular_direccion(self):
        """Calcula el vector unitario de dirección"""
        dx = self.punto_fin[0] - self.punto_inicio[0]
        dy = self.punto_fin[1] - self.punto_inicio[1]
        dz = self.punto_fin[2] - self.punto_inicio[2]
        magnitud = math.sqrt(dx**2 + dy**2 + dz**2)
        if magnitud > 0:
            self.direccion = (dx/magnitud, dy/magnitud, dz/magnitud)
        else:
            self.direccion = (0, 0, 0)
            
    def proyectar_punto(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """
        Proyecta un punto sobre la línea del vector W
        
        Args:
            punto: Coordenadas (x, y, z) del punto a proyectar
            
        Returns:
            Coordenadas del punto proyectado sobre W
        """
        # Vector desde el punto de anclaje al punto
        v_ap = (
            punto[0] - self.punto_inicio[0],
            punto[1] - self.punto_inicio[1],
            punto[2] - self.punto_inicio[2]
        )
        
        # Producto punto con la dirección
        t = (v_ap[0] * self.direccion[0] + 
             v_ap[1] * self.direccion[1] + 
             v_ap[2] * self.direccion[2])
        
        # Punto proyectado
        return (
            self.punto_inicio[0] + t * self.direccion[0],
            self.punto_inicio[1] + t * self.direccion[1],
            self.punto_inicio[2] + t * self.direccion[2]
        )
    
    def distancia_ortogonal(self, punto: Tuple[float, float, float]) -> float:
        """
        Calcula la distancia ortogonal de un punto al vector W
        """
        proj = self.proyectar_punto(punto)
        dx = punto[0] - proj[0]
        dy = punto[1] - proj[1]
        dz = punto[2] - proj[2]
        return math.sqrt(dx**2 + dy**2 + dz**2)
    
    def punto_en_linea(self, t: float) -> Tuple[float, float, float]:
        """
        Obtiene un punto en la línea W dado un parámetro t
        """
        return (
            self.punto_inicio[0] + t * self.direccion[0],
            self.punto_inicio[1] + t * self.direccion[1],
            self.punto_inicio[2] + t * self.direccion[2]
        )

# =============================================
# SISTEMA DE PREFETCHING VECTORIAL
# =============================================

class PatronAcceso(Enum):
    """Patrones de acceso a datos identificados"""
    LINEAL = "lineal"
    CIRCULAR = "circular"
    ESPIRAL = "espiral"
    ALEATORIO = "aleatorio"
    VECTORIAL = "vectorial"

class PrefetchVectorial:
    """
    Sistema de prefetching basado en patrones vectoriales espaciales
    """
    def __init__(self, ventana_tiempo: int = 10, umbral_confianza: float = 0.7):
        self.historial = []
        self.ventana = ventana_tiempo
        self.umbral_confianza = umbral_confianza
        self.patrones_detectados = defaultdict(int)
        self.cache_prefetch = defaultdict(list)
        
    def registrar_acceso(self, coordenadas: Tuple[float, float, float], 
                        timestamp: float = None):
        """Registra un acceso a datos con sus coordenadas"""
        if timestamp is None:
            timestamp = time.time()
        
        self.historial.append({
            'coords': coordenadas,
            'timestamp': timestamp
        })
        
        if len(self.historial) > self.ventana * 10:
            self.historial.pop(0)
            
        # Analizar patrones con cada nuevo acceso
        self._analizar_patrones()
        
    def _analizar_patrones(self):
        """Analiza patrones en el historial de accesos"""
        if len(self.historial) < 3:
            return
            
        # Analizar movimiento entre accesos consecutivos
        patron = self._identificar_patron_movimiento()
        if patron:
            self.patrones_detectados[patron] += 1
            
            # Si el patrón es confiable, generar prefetch
            if self.patrones_detectados[patron] > self.umbral_confianza * len(self.historial):
                self._generar_prefetch(patron)
    
    def _identificar_patron_movimiento(self) -> Optional[PatronAcceso]:
        """Identifica el patrón de movimiento en los accesos"""
        if len(self.historial) < 3:
            return None
            
        ultimos = self.historial[-3:]
        
        # Calcular vectores de movimiento
        v1 = (
            ultimos[1]['coords'][0] - ultimos[0]['coords'][0],
            ultimos[1]['coords'][1] - ultimos[0]['coords'][1],
            ultimos[1]['coords'][2] - ultimos[0]['coords'][2]
        )
        v2 = (
            ultimos[2]['coords'][0] - ultimos[1]['coords'][0],
            ultimos[2]['coords'][1] - ultimos[1]['coords'][1],
            ultimos[2]['coords'][2] - ultimos[1]['coords'][2]
        )
        
        # Calcular producto punto para determinar patrón
        producto_punto = v1[0]*v2[0] + v1[1]*v2[1] + v1[2]*v2[2]
        magnitud_v1 = math.sqrt(v1[0]**2 + v1[1]**2 + v1[2]**2)
        magnitud_v2 = math.sqrt(v2[0]**2 + v2[1]**2 + v2[2]**2)
        
        if magnitud_v1 * magnitud_v2 == 0:
            return None
            
        cos_angulo = producto_punto / (magnitud_v1 * magnitud_v2)
        
        if abs(cos_angulo - 1.0) < 0.1:
            return PatronAcceso.LINEAL
        elif abs(cos_angulo + 1.0) < 0.1:
            return PatronAcceso.CIRCULAR
        elif abs(cos_angulo) < 0.1:
            return PatronAcceso.ESPIRAL
        else:
            return PatronAcceso.VECTORIAL
            
    def _generar_prefetch(self, patron: PatronAcceso):
        """Genera predicciones de prefetch basadas en el patrón identificado"""
        if len(self.historial) < 2:
            return
            
        ultimo = self.historial[-1]
        anterior = self.historial[-2]
        
        # Calcular vector de movimiento actual
        delta = (
            ultimo['coords'][0] - anterior['coords'][0],
            ultimo['coords'][1] - anterior['coords'][1],
            ultimo['coords'][2] - anterior['coords'][2]
        )
        
        # Generar predicciones según el patrón
        predicciones = []
        for i in range(1, 5):  # Predecir los siguientes 4 puntos
            if patron == PatronAcceso.LINEAL:
                pred = (
                    ultimo['coords'][0] + i * delta[0],
                    ultimo['coords'][1] + i * delta[1],
                    ultimo['coords'][2] + i * delta[2]
                )
            elif patron == PatronAcceso.CIRCULAR:
                # Movimiento circular
                angulo = i * 0.5
                pred = (
                    ultimo['coords'][0] + delta[0] * math.cos(angulo),
                    ultimo['coords'][1] + delta[1] * math.sin(angulo),
                    ultimo['coords'][2] + delta[2]
                )
            else:
                # Patrón vectorial o espiral
                pred = (
                    ultimo['coords'][0] + i * delta[0] * (1 + 0.1 * i),
                    ultimo['coords'][1] + i * delta[1] * (1 + 0.1 * i),
                    ultimo['coords'][2] + i * delta[2]
                )
            predicciones.append(pred)
            
        self.cache_prefetch[patron] = predicciones
        
    def obtener_prefetch(self) -> List[Tuple[float, float, float]]:
        """Obtiene las predicciones de prefetch actuales"""
        if not self.patrones_detectados:
            return []
            
        # Obtener el patrón más frecuente
        patron_principal = max(self.patrones_detectados.items(), 
                              key=lambda x: x[1])[0]
        
        return self.cache_prefetch.get(patron_principal, [])

# =============================================
# COMPRESIÓN DE DATOS ESPACIALES
# =============================================

class CompresorEspacial:
    """
    Sistema de compresión/descompresión de datos espaciales
    """
    def __init__(self, umbral_compresion: float = 0.8):
        self.umbral_compresion = umbral_compresion
        self.historial_delta = []
        
    def codificar_diferencial(self, vector_actual: Tuple[float, float, float],
                             vector_anterior: Tuple[float, float, float]) -> Dict:
        """Codificación diferencial de vectores espaciales"""
        return {
            'tipo': 'diferencial',
            'delta_x': vector_actual[0] - vector_anterior[0],
            'delta_y': vector_actual[1] - vector_anterior[1],
            'delta_z': vector_actual[2] - vector_anterior[2],
            'precision': 4  # Decimales de precisión
        }
    
    def decodificar_diferencial(self, codigo: Dict, 
                               vector_base: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Decodificación de codificación diferencial"""
        return (
            vector_base[0] + codigo['delta_x'],
            vector_base[1] + codigo['delta_y'],
            vector_base[2] + codigo['delta_z']
        )
    
    def comprimir_batch(self, vectores: List[Tuple[float, float, float]]) -> List[Dict]:
        """Comprime un batch de vectores usando codificación diferencial"""
        if not vectores:
            return []
            
        comprimidos = []
        comprimidos.append({
            'tipo': 'base',
            'coords': vectores[0]
        })
        
        for i in range(1, len(vectores)):
            # Verificar si la compresión es beneficiosa
            delta = (
                abs(vectores[i][0] - vectores[i-1][0]),
                abs(vectores[i][1] - vectores[i-1][1]),
                abs(vectores[i][2] - vectores[i-1][2])
            )
            
            # Si el delta es pequeño, codificar diferencialmente
            if max(delta) < self.umbral_compresion:
                comprimidos.append(
                    self.codificar_diferencial(vectores[i], vectores[i-1])
                )
            else:
                comprimidos.append({
                    'tipo': 'base',
                    'coords': vectores[i]
                })
                
        return comprimidos
    
    def descomprimir_batch(self, comprimidos: List[Dict]) -> List[Tuple[float, float, float]]:
        """Descomprime un batch de vectores"""
        if not comprimidos:
            return []
            
        descomprimidos = []
        vector_base = None
        
        for item in comprimidos:
            if item['tipo'] == 'base':
                vector_base = item['coords']
                descomprimidos.append(vector_base)
            else:
                if vector_base is not None:
                    vector = self.decodificar_diferencial(item, vector_base)
                    descomprimidos.append(vector)
                    vector_base = vector
                    
        return descomprimidos

# =============================================
# BALANCEADOR DE CARGA EN OCTREE
# =============================================

class BalanceadorOctree:
    """
    Sistema de balanceo de carga para el Octree espacial
    """
    def __init__(self, umbral_superior: float = 0.8, umbral_inferior: float = 0.2):
        self.umbral_superior = umbral_superior
        self.umbral_inferior = umbral_inferior
        self.metricas_carga = defaultdict(float)
        
    def calcular_carga(self, nodo: 'NodoOctreeOptimizado') -> float:
        """Calcula la carga de procesamiento de un nodo"""
        if nodo.es_hoja:
            return float(len(nodo.datos_nodos))
        else:
            # Calcular carga como promedio de los hijos + overhead
            carga_hijos = sum(self.calcular_carga(hijo) for hijo in nodo.hijos)
            return carga_hijos / len(nodo.hijos) + 0.1  # Overhead de gestión
        
    def balancear(self, nodo: 'NodoOctreeOptimizado'):
        """Balancea la distribución de carga en el Octree"""
        if nodo.es_hoja:
            return
            
        carga = self.calcular_carga(nodo)
        self.metricas_carga[nodo.id] = carga
        
        # Si la carga es muy alta, subdividir hijos sobrecargados
        if carga > self.umbral_superior:
            for hijo in nodo.hijos:
                if self.calcular_carga(hijo) > self.umbral_superior:
                    if not hijo.es_hoja:
                        self._redistribuir_carga(hijo)
                        
        # Si la carga es muy baja, considerar fusión
        elif carga < self.umbral_inferior and nodo.nivel > 0:
            self._evaluar_fusion(nodo)
            
    def _redistribuir_carga(self, nodo: 'NodoOctreeOptimizado'):
        """Redistribuye la carga entre los hijos de un nodo"""
        if not nodo.hijos:
            return
            
        # Recolectar todos los datos de los hijos
        todos_datos = []
        for hijo in nodo.hijos:
            if hijo.es_hoja:
                todos_datos.extend(list(hijo.datos_nodos.items()))
            else:
                # Si no es hoja, recursivamente recolectar
                self._recolectar_datos(hijo, todos_datos)
        
        # Limpiar hijos
        for hijo in nodo.hijos:
            hijo.datos_nodos.clear()
        
        # Redistribuir balanceadamente
        num_hijos = len(nodo.hijos)
        for i, (n_id, n_info) in enumerate(todos_datos):
            hijo_idx = i % num_hijos
            nodo.hijos[hijo_idx].insertar(n_id, n_info)
            
    def _recolectar_datos(self, nodo: 'NodoOctreeOptimizado', 
                          lista_datos: List):
        """Recolecta recursivamente todos los datos de un nodo y sus hijos"""
        if nodo.es_hoja:
            lista_datos.extend(list(nodo.datos_nodos.items()))
        else:
            for hijo in nodo.hijos:
                self._recolectar_datos(hijo, lista_datos)
                
    def _evaluar_fusion(self, nodo: 'NodoOctreeOptimizado'):
        """Evalúa si es posible fusionar nodos con baja carga"""
        if nodo.padre is None:
            return
            
        # Verificar si todos los hermanos tienen baja carga
        carga_hermanos = []
        for hermano in nodo.padre.hijos:
            if hermano != nodo:
                carga_hermanos.append(self.calcular_carga(hermano))
        
        # Si todos tienen baja carga y son hojas, fusionar
        if all(c < self.umbral_inferior for c in carga_hermanos):
            if all(h.es_hoja for h in nodo.padre.hijos):
                self._fusionar_nodos(nodo.padre)
                
    def _fusionar_nodos(self, nodo: 'NodoOctreeOptimizado'):
        """Fusiona todos los hijos de un nodo en el mismo"""
        if not nodo.hijos:
            return
            
        # Recolectar todos los datos de los hijos
        todos_datos = {}
        for hijo in nodo.hijos:
            if hijo.es_hoja:
                todos_datos.update(hijo.datos_nodos)
            else:
                self._recolectar_datos(hijo, todos_datos)
        
        # Convertir a hoja con todos los datos
        nodo.hijos = None
        nodo.es_hoja = True
        nodo.datos_nodos = todos_datos

# =============================================
# OCTREE OPTIMIZADO CON VECTOR W
# =============================================

class NodoOctreeOptimizado:
    """
    Implementación avanzada del Octree con integración de Vector W y optimizaciones
    """
    def __init__(self, centro: Tuple[float, float, float], tamano: float, 
                 nivel: int = 0, max_nivel: int = 5, 
                 id_nodo: str = None):
        self.centro = centro
        self.tamano = tamano
        self.nivel = nivel
        self.max_nivel = max_nivel
        self.es_hoja = True
        self.hijos = None
        self.datos_nodos = {}
        self.id = id_nodo or f"NODE_{nivel}_{int(time.time())}"
        self.padre = None
        self.vector_w = None  # Vector W asociado a este nodo
        self.last_acceso = time.time()
        self.frecuencia_acceso = 0
        
        # Sistemas integrados
        self.prefetch = PrefetchVectorial()
        self.balanceador = BalanceadorOctree()
        
    def asociar_vector_w(self, vector_w: VectorW):
        """Asocia un Vector W a este nodo"""
        self.vector_w = vector_w
        
    def subdividir(self):
        """Subdivide el nodo en 8 hijos con optimización de carga"""
        self.es_hoja = False
        self.hijos = []
        medio_tamano = self.tamano / 2.0
        offsets = [
            (-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
            (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1)
        ]
        
        for dx, dy, dz in offsets:
            c_x = self.centro[0] + dx * (medio_tamano / 2.0)
            c_y = self.centro[1] + dy * (medio_tamano / 2.0)
            c_z = self.centro[2] + dz * (medio_tamano / 2.0)
            hijo = NodoOctreeOptimizado(
                (c_x, c_y, c_z), medio_tamano, 
                self.nivel + 1, self.max_nivel
            )
            hijo.padre = self
            # Heredar el Vector W del padre si existe
            if self.vector_w:
                hijo.asociar_vector_w(self.vector_w)
            self.hijos.append(hijo)
        
        # Migrar datos a hijos
        for n_id, n_info in self.datos_nodos.items():
            self._insertar_en_hijos(n_id, n_info)
        self.datos_nodos.clear()
        
    def _insertar_en_hijos(self, nodo_id: str, nodo_info: Dict):
        """Inserta un dato en los hijos apropiados"""
        pos = nodo_info['coords']
        
        # Si hay Vector W, usar proyección para determinar ubicación
        if self.vector_w:
            pos_proyectada = self.vector_w.proyectar_punto(pos)
            pos_usar = pos_proyectada
        else:
            pos_usar = pos
            
        for hijo in self.hijos:
            hs = hijo.tamano / 2.0
            if (hijo.centro[0] - hs <= pos_usar[0] <= hijo.centro[0] + hs and
                hijo.centro[1] - hs <= pos_usar[1] <= hijo.centro[1] + hs and
                hijo.centro[2] - hs <= pos_usar[2] <= hijo.centro[2] + hs):
                hijo.insertar(nodo_id, nodo_info)
                return
                
    def insertar(self, nodo_id: str, nodo_info: Dict):
        """Inserta un nodo con optimizaciones de prefetching y balanceo"""
        self.last_acceso = time.time()
        self.frecuencia_acceso += 1
        
        # Registrar acceso para prefetching
        self.prefetch.registrar_acceso(nodo_info['coords'])
        
        if self.es_hoja:
            self.datos_nodos[nodo_id] = nodo_info
            
            # Subdividir si hay alta densidad y no hemos alcanzado nivel máximo
            if len(self.datos_nodos) > 3 and self.nivel < self.max_nivel:
                self.subdividir()
            # Balancear si hay mucha carga
            elif len(self.datos_nodos) > 5:
                self.balanceador.balancear(self)
        else:
            self._insertar_en_hijos(nodo_id, nodo_info)
            
    def buscar_nodo(self, coords: Tuple[float, float, float]) -> Tuple[Optional[str], Optional[Dict]]:
        """Busca un nodo con prefetching optimizado"""
        self.last_acceso = time.time()
        self.frecuencia_acceso += 1
        
        # Registrar acceso para prefetching
        self.prefetch.registrar_acceso(coords)
        
        if self.es_hoja:
            for n_id, n_info in self.datos_nodos.items():
                if n_info['coords'] == coords:
                    return n_id, n_info
            return None, None
        else:
            # Usar Vector W para optimizar búsqueda
            if self.vector_w:
                coords_busqueda = self.vector_w.proyectar_punto(coords)
            else:
                coords_busqueda = coords
                
            medio_tamano = self.tamano / 2.0
            for hijo in self.hijos:
                if (hijo.centro[0] - medio_tamano <= coords_busqueda[0] <= hijo.centro[0] + medio_tamano and
                    hijo.centro[1] - medio_tamano <= coords_busqueda[1] <= hijo.centro[1] + medio_tamano and
                    hijo.centro[2] - medio_tamano <= coords_busqueda[2] <= hijo.centro[2] + medio_tamano):
                    return hijo.buscar_nodo(coords)
            return None, None
            
    def obtener_vecinos_cercanos(self, coords: Tuple[float, float, float], 
                                radio: float) -> List[Dict]:
        """Obtiene nodos vecinos dentro de un radio dado"""
        vecinos = []
        
        if self.es_hoja:
            for n_id, n_info in self.datos_nodos.items():
                dx = n_info['coords'][0] - coords[0]
                dy = n_info['coords'][1] - coords[1]
                dz = n_info['coords'][2] - coords[2]
                distancia = math.sqrt(dx**2 + dy**2 + dz**2)
                if distancia <= radio:
                    vecinos.append({
                        'id': n_id,
                        'info': n_info,
                        'distancia': distancia
                    })
        else:
            for hijo in self.hijos:
                vecinos.extend(hijo.obtener_vecinos_cercanos(coords, radio))
                
        return sorted(vecinos, key=lambda x: x['distancia'])

# =============================================
# NÚCLEO VECTORIAL OS OPTIMIZADO
# =============================================

class NúcleoVectorialOSOptimizado:
    """
    Versión optimizada del Núcleo Vectorial OS con todas las mejoras implementadas
    """
    def __init__(self, ruta_checkpoint: str = "vos_optimizado.vcf"):
        self.ruta_checkpoint = ruta_checkpoint
        
        # Inicializar Octree optimizado
        self.raiz_espacial = NodoOctreeOptimizado(
            (16000.0, 16000.0, 16000.0), 
            32000.0,
            max_nivel=6
        )
        
        # Constantes del sistema
        self.K_x, self.K_y, self.K_z = 10000, 5000, 20000
        self.theta = 0.1402
        self.R_nivel = 40
        
        # Sistemas integrados
        self.compresor = CompresorEspacial()
        self.prefetch_global = PrefetchVectorial()
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Métricas de rendimiento
        self.metricas = {
            'accesos': 0,
            'aciertos_cache': 0,
            'fallos_cache': 0,
            'tiempo_promedio_acceso': 0.0,
            'memoria_utilizada': 0,
            'compresion_ratio': 0.0
        }
        
        # Cache de vectores W
        self.cache_vectores_w = {}
        
        # Cargar o inicializar
        self.cargar_o_inicializar_nodos()
        
    def crear_vector_w(self, punto_anclaje: Tuple[float, float, float], 
                       theta: float = None, longitud: float = 1000.0) -> VectorW:
        """Crea y registra un nuevo Vector W"""
        if theta is None:
            theta = self.theta
            
        vector_w = VectorW(punto_anclaje, theta, longitud)
        self.cache_vectores_w[vector_w.id_vector] = vector_w
        return vector_w
        
    def indexar_con_vector_w(self, datos: List[Dict], vector_w: VectorW) -> List[Dict]:
        """Indexa datos según su proyección en un Vector W"""
        datos_ordenados = sorted(
            datos,
            key=lambda d: vector_w.proyectar_punto(d['coords'])[0]  # Ordenar por proyección en X
        )
        
        # Asociar Vector W a los nodos
        for dato in datos_ordenados:
            nodo_id = dato.get('id', '')
            # Buscar nodo y asociar vector
            n_id, n_info = self.raiz_espacial.buscar_nodo(dato['coords'])
            if n_id:
                self.raiz_espacial.asociar_vector_w(vector_w)
                
        return datos_ordenados
        
    def operador_eje_z_optimizado(self, D_L: int) -> Tuple[float, float, float]:
        """Operador Eje Z optimizado con Vector W integrado"""
        # Cálculo base
        comp_x = (D_L % self.K_x) * math.cos(self.theta) - (D_L % self.K_y) * math.sin(self.theta)
        comp_y = (D_L % self.K_x) * math.sin(self.theta) + (D_L % self.K_y) * math.cos(self.theta)
        comp_z = (D_L % self.K_z) * self.R_nivel
        
        coords = (abs(round(comp_x, 4)), abs(round(comp_y, 4)), abs(round(comp_z, 4)))
        
        # Registrar acceso para prefetching
        self.prefetch_global.registrar_acceso(coords)
        
        return coords
        
    def acceso_inteligente(self, direccion: int) -> Optional[Dict]:
        """Acceso a datos con optimizaciones de prefetching y caché"""
        inicio_tiempo = time.time()
        self.metricas['accesos'] += 1
        
        # Proyectar dirección a coordenadas 3D
        coords = self.operador_eje_z_optimizado(direccion)
        
        # Buscar en Octree
        n_id, n_info = self.raiz_espacial.buscar_nodo(coords)
        
        if n_info:
            self.metricas['aciertos_cache'] += 1
            resultado = {
                'id': n_id,
                'info': n_info,
                'coords': coords
            }
            
            # Cargar prefetch en background
            self.executor.submit(self._cargar_prefetch, coords)
            
        else:
            self.metricas['fallos_cache'] += 1
            resultado = None
            
        # Actualizar métricas
        tiempo = time.time() - inicio_tiempo
        self.metricas['tiempo_promedio_acceso'] = (
            (self.metricas['tiempo_promedio_acceso'] * (self.metricas['accesos'] - 1) + tiempo) /
            self.metricas['accesos']
        )
        
        return resultado
        
    def _cargar_prefetch(self, coords: Tuple[float, float, float]):
        """Carga datos de prefetch en background"""
        prefetch = self.prefetch_global.obtener_prefetch()
        if prefetch:
            for coord_pred in prefetch[:3]:  # Solo los primeros 3 para no sobrecargar
                # Simular carga en caché
                self.metricas['memoria_utilizada'] += len(str(coord_pred))
                
    def guardar_checkpoint_optimizado(self):
        """Guarda checkpoint con compresión y optimizaciones"""
        print(f"[vOS Optimizado] Guardando checkpoint en '{self.ruta_checkpoint}'...")
        
        # Extraer todos los nodos
        todos_nodos = {}
        def extraer(nodo_actual):
            if nodo_actual.es_hoja:
                todos_nodos.update(nodo_actual.datos_nodos)
            else:
                for hijo in nodo_actual.hijos:
                    extraer(hijo)
                    
        extraer(self.raiz_espacial)
        
        # Comprimir datos
        datos_comprimidos = self.compresor.comprimir_batch(
            [info['coords'] for info in todos_nodos.values()]
        )
        
        checkpoint = {
            'version': '3.0',
            'timestamp': time.time(),
            'theta': self.theta,
            'nodos': todos_nodos,
            'vectores_w': {
                vid: {
                    'anclaje': v.punto_anclaje,
                    'theta': v.theta,
                    'longitud': v.longitud
                } for vid, v in self.cache_vectores_w.items()
            },
            'metricas': self.metricas,
            'datos_comprimidos': datos_comprimidos
        }
        
        with open(self.ruta_checkpoint, 'w') as f:
            json.dump(checkpoint, f, indent=2)
            
        print("[vOS Optimizado] Checkpoint guardado exitosamente")
        
    def optimizar_memoria(self):
        """Optimiza el uso de memoria con compresión y balanceo"""
        print("[vOS Optimizado] Ejecutando optimización de memoria...")
        
        # Balancear árbol completo
        self._balancear_arbol_completo(self.raiz_espacial)
        
        # Calcular ratio de compresión
        memoria_original = 0
        memoria_comprimida = 0
        nodos_procesados = 0
        
        def procesar_nodo(nodo_actual):
            nonlocal memoria_original, memoria_comprimida, nodos_procesados
            if nodo_actual.es_hoja:
                for n_info in nodo_actual.datos_nodos.values():
                    memoria_original += len(str(n_info['coords']))
                    # Comprimir individualmente
                    comprimido = self.compresor.codificar_diferencial(
                        n_info['coords'], 
                        (0, 0, 0)
                    )
                    memoria_comprimida += len(str(comprimido))
                    nodos_procesados += 1
            else:
                for hijo in nodo_actual.hijos:
                    procesar_nodo(hijo)
                    
        procesar_nodo(self.raiz_espacial)
        
        if memoria_original > 0:
            self.metricas['compresion_ratio'] = memoria_comprimida / memoria_original
            
        print(f"[vOS Optimizado] Compresión ratio: {self.metricas['compresion_ratio']:.2%}")
        print(f"[vOS Optimizado] Nodos procesados: {nodos_procesados}")
        
    def _balancear_arbol_completo(self, nodo):
        """Balancea todo el árbol recursivamente"""
        if not nodo.es_hoja:
            for hijo in nodo.hijos:
                self._balancear_arbol_completo(hijo)
            nodo.balanceador.balancear(nodo)

# =============================================
# FUNCIONES DE VALIDACIÓN Y PRUEBAS AVANZADAS
# =============================================

def prueba_rendimiento_optimizado():
    """Prueba de rendimiento del sistema optimizado"""
    print("=" * 60)
    print("PRUEBA DE RENDIMIENTO - vOS OPTIMIZADO v3.0")
    print("=" * 60)
    
    # Inicializar sistema
    vos = NúcleoVectorialOSOptimizado()
    
    # 1. Crear y probar Vector W
    print("\n[1] SISTEMA DE VECTORES W")
    vector_w = vos.crear_vector_w((16000, 16000, 16000), longitud=10000)
    print(f"✓ Vector W creado: {vector_w.id_vector}")
    print(f"  Dirección: {vector_w.direccion}")
    print(f"  Punto inicio: {vector_w.punto_inicio}")
    print(f"  Punto fin: {vector_w.punto_fin}")
    
    # Probar proyección
    punto_prueba = (20000, 18000, 16000)
    proj = vector_w.proyectar_punto(punto_prueba)
    dist = vector_w.distancia_ortogonal(punto_prueba)
    print(f"  Proyección de {punto_prueba}: {proj}")
    print(f"  Distancia ortogonal: {dist:.2f}")
    
    # 2. Prueba de indexación con Vector W
    print("\n[2] INDEXACIÓN CON VECTOR W")
    datos_prueba = [
        {'id': 'D1', 'coords': (20000, 18000, 16000), 'val': 'TEST1'},
        {'id': 'D2', 'coords': (21000, 18500, 16000), 'val': 'TEST2'},
        {'id': 'D3', 'coords': (19000, 17500, 16000), 'val': 'TEST3'},
    ]
    datos_indexados = vos.indexar_con_vector_w(datos_prueba, vector_w)
    print(f"✓ Datos indexados: {len(datos_indexados)} elementos")
    
    # 3. Prueba de acceso inteligente
    print("\n[3] ACCESO INTELIGENTE Y PREFETCHING")
    direcciones = [7458921, 7458922, 7458923, 7458924, 7458925]
    
    for dir_addr in direcciones:
        resultado = vos.acceso_inteligente(dir_addr)
        if resultado:
            print(f"✓ Acceso a {dir_addr}: Encontrado en {resultado['coords']}")
        else:
            print(f"✗ Acceso a {dir_addr}: No encontrado")
            
    # 4. Prueba de compresión
    print("\n[4] SISTEMA DE COMPRESIÓN ESPACIAL")
    vectores_originales = [
        (1000, 1000, 1000),
        (1001, 1000, 1000),
        (1002, 1001, 1000),
        (1003, 1001, 1001)
    ]
    
    comprimidos = vos.compresor.comprimir_batch(vectores_originales)
    descomprimidos = vos.compresor.descomprimir_batch(comprimidos)
    
    print(f"✓ Vectores originales: {len(vectores_originales)}")
    print(f"✓ Elementos comprimidos: {len(comprimidos)}")
    print(f"✓ Tasa de compresión: {len(vectores_originales)/len(comprimidos):.2f}x")
    
    # 5. Prueba de optimización de memoria
    print("\n[5] OPTIMIZACIÓN DE MEMORIA")
    vos.optimizar_memoria()
    print(f"✓ Ratio de compresión: {vos.metricas['compresion_ratio']:.2%}")
    print(f"✓ Memoria utilizada: {vos.metricas['memoria_utilizada']} bytes")
    
    # 6. Métricas de rendimiento
    print("\n[6] MÉTRICAS DE RENDIMIENTO")
    print(f"✓ Accesos totales: {vos.metricas['accesos']}")
    print(f"✓ Aciertos de caché: {vos.metricas['aciertos_cache']}")
    print(f"✓ Fallos de caché: {vos.metricas['fallos_cache']}")
    print(f"✓ Tiempo promedio: {vos.metricas['tiempo_promedio_acceso']:.6f}s")
    
    # Guardar checkpoint
    print("\n[7] PERSISTENCIA")
    vos.guardar_checkpoint_optimizado()
    
    print("\n" + "=" * 60)
    print("PRUEBA COMPLETADA EXITOSAMENTE")
    print("=" * 60)
    
def prueba_escenario_estres():
    """Prueba de estrés con múltiples operaciones concurrentes"""
    print("\n" + "=" * 60)
    print("PRUEBA DE ESTRÉS - OPERACIONES CONCURRENTES")
    print("=" * 60)
    
    vos = NúcleoVectorialOSOptimizado()
    
    # Generar datos de prueba masivos
    datos_masivos = []
    for i in range(100):
        coords = (
            10000 + i * 10,
            10000 + i * 5,
            10000 + i * 3
        )
        datos_masivos.append({
            'id': f"DATA_{i}",
            'coords': coords,
            'val': f"VALUE_{i}"
        })
    
    print(f"✓ Generados {len(datos_masivos)} registros de prueba")
    
    # Insertar datos
    inicio = time.time()
    for dato in datos_masivos:
        vos.raiz_espacial.insertar(dato['id'], dato)
    tiempo_insercion = time.time() - inicio
    
    print(f"✓ Inserción completada en {tiempo_insercion:.3f}s")
    print(f"  Tasa: {len(datos_masivos)/tiempo_insercion:.0f} registros/segundo")
    
    # Accesos concurrentes
    print("\nEjecutando accesos concurrentes...")
    
    def acceso_concurrente(dir_base, offset):
        direccion = dir_base + offset
        return vos.acceso_inteligente(direccion)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futuros = []
        for i in range(50):
            futuros.append(
                executor.submit(acceso_concurrente, 7458900, i)
            )
            
        resultados = [f.result() for f in futuros]
        
    exitos = sum(1 for r in resultados if r is not None)
    print(f"✓ {exitos} accesos exitosos de {len(resultados)}")
    
    # Optimizar después de la carga
    print("\nOptimizando después de carga pesada...")
    vos.optimizar_memoria()
    print(f"✓ Memoria final: {vos.metricas['memoria_utilizada']} bytes")
    print(f"✓ Ratio de compresión: {vos.metricas['compresion_ratio']:.2%}")
    
    print("\n" + "=" * 60)
    print("PRUEBA DE ESTRÉS COMPLETADA")
    print("=" * 60)

# =============================================
# MENÚ PRINCIPAL DE DEMOSTRACIÓN
# =============================================

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  VECTORIAL OS (vOS) - NÚCLEO OPTIMIZADO v3.0")
    print("  Arquitectura Espacial con Sistema Vectorial W")
    print("=" * 70)
    
    while True:
        print("\n=== MENÚ DE DEMOSTRACIÓN ===")
        print("1. Prueba de rendimiento optimizado")
        print("2. Prueba de estrés concurrente")
        print("3. Crear y manipular Vectores W")
        print("4. Análisis de patrones de acceso")
        print("5. Salir")
        
        opcion = input("\nSeleccione una opción (1-5): ")
        
        if opcion == '1':
            prueba_rendimiento_optimizado()
        elif opcion == '2':
            prueba_escenario_estres()
        elif opcion == '3':
            print("\n--- DEMOSTRACIÓN DE VECTORES W ---")
            vos = NúcleoVectorialOSOptimizado()
            
            # Crear varios vectores W con diferentes ángulos
            angulos = [0.0, 0.5, 1.0, 1.5, 2.0]
            for i, angulo in enumerate(angulos):
                vw = vos.crear_vector_w(
                    (16000 + i*1000, 16000, 16000),
                    theta=angulo,
                    longitud=5000
                )
                print(f"Vector W{i+1}: θ={angulo:.2f}rad, dir={vw.direccion}")
                
            # Proyectar puntos en diferentes vectores
            punto = (18000, 17000, 16000)
            print(f"\nPunto de prueba: {punto}")
            for vid, vw in vos.cache_vectores_w.items():
                proj = vw.proyectar_punto(punto)
                dist = vw.distancia_ortogonal(punto)
                print(f"  Proyección en {vid}: {proj}, distancia={dist:.2f}")
                
        elif opcion == '4':
            print("\n--- ANÁLISIS DE PATRONES DE ACCESO ---")
            prefetch = PrefetchVectorial()
            
            # Simular diferentes patrones de acceso
            patrones = [
                # Patrón lineal
                [(1000, 1000, 1000), (1010, 1010, 1010), (1020, 1020, 1020)],
                # Patrón circular
                [(2000, 2000, 2000), (2010, 1995, 2000), (2020, 1990, 2000)],
                # Patrón aleatorio
                [(3000, 3000, 3000), (3100, 2900, 3000), (2950, 3050, 3000)]
            ]
            
            for i, patron in enumerate(patrones):
                print(f"\nAnalizando patrón {i+1}:")
                for coord in patron:
                    prefetch.registrar_acceso(coord)
                    
                predicciones = prefetch.obtener_prefetch()
                patron_detectado = prefetch._identificar_patron_movimiento()
                print(f"  Patrón detectado: {patron_detectado}")
                if predicciones:
                    print(f"  Predicciones: {predicciones[:3]}...")
                    
        elif opcion == '5':
            print("\n¡Gracias por usar vOS Optimizado!")
            break
        else:
            print("Opción no válida. Intente de nuevo.")
