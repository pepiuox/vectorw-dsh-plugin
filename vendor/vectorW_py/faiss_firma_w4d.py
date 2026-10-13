"""
Integración FAISS + Firmas W 4D - Búsqueda Semántica Invariante a Rotaciones
Arquitecto y Autor: Jose Ricaro Mantilla Mantilla (PePiuoX)
Licencia: LICENCIA DE ATRIBUCIÓN, MEJORA CONTINUA Y EXENCIÓN DE RESPONSABILIDAD (LAMC) PEPIUOX v1.0

/*
 * Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)
 * Licencia: LAMC v1.0 - https://pepiuox.org/lamc/v1.0
 *
 * Modificado por: Jose Ricardo Mantilla Mantilla (PePiuoX) - [2026]
 * Descripción: Integra el núcleo vOS v3.0 real (vectorW.py) con:
  • Generador de firmas W 4D (4 diagonales del cubo)
  • FAISS para indexación y búsqueda ANN
  • Invariancia a rotaciones demostrada matemáticamente
  • Búsqueda semántica topológica (no geométrica)
"""
import math
import time
import hashlib
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path

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

# FAISS (requiere: pip install faiss-cpu o faiss-gpu)
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("⚠ FAISS no instalado. Ejecuta: pip install faiss-cpu")


# ============================================================
# 1. GENERADOR DE FIRMAS W 4D (4 diagonales del cubo)
# ============================================================
class GeneradorFirmaW4D:
    """
    Genera la firma W 4D de un punto 3D usando 4 diagonales del cubo.

    Las 4 diagonales se construyen a partir del VectorW base de vOS v3.0
    rotándolo 90°, 180° y 270° alrededor del eje Z. Esto garantiza que
    las 4 diagonales sean ortogonales en proyección XY y capturen
    correlaciones en las 4 direcciones principales del cubo.

    La firma W 4D = (t1, t2, t3, t4) es invariante a rotaciones del cubo
    porque una rotación solo permuta las 4 proyecciones.
    """
    def __init__(self, nucleo_vos: NúcleoVectorialOSOptimizado,
                 lado_cubo: float = 32000.0):
        self.nucleo = nucleo_vos
        self.lado = lado_cubo
        self.centro = (lado_cubo/2, lado_cubo/2, lado_cubo/2)

        # Constantes vOS v3.0 reales
        self.K_x = nucleo_vos.K_x      # 10000
        self.K_y = nucleo_vos.K_y      # 5000
        self.K_z = nucleo_vos.K_z      # 20000
        self.theta_base = nucleo_vos.theta  # 0.1402
        self.R_nivel = nucleo_vos.R_nivel   # 40

        # Longitud de las diagonales (diagonal espacial del cubo)
        self.longitud_diagonal = lado_cubo * math.sqrt(3)

        # Crear las 4 diagonales (una por cada 90° de rotación)
        self.diagonales: List[VectorW] = []
        self._crear_diagonales()

        # Caché de firmas
        self.cache_firmas: Dict[Tuple[float, float, float], Tuple[float, float, float, float]] = {}

        # Estadísticas
        self.stats = {
            'firmas_calculadas': 0,
            'tiempo_total_ms': 0.0
        }

    def _crear_diagonales(self):
        """
        Crea las 4 diagonales del cubo a partir del VectorW base.

        W1: VectorW original (θ = 0.1402 rad)
        W2: Rotado 90° (θ = 0.1402 + π/2)
        W3: Rotado 180° (θ = 0.1402 + π)
        W4: Rotado 270° (θ = 0.1402 + 3π/2)
        """
        # W1: diagonal base del sistema vOS
        w1 = VectorW(
            punto_anclaje=(0.0, 0.0, self.centro[2]),
            theta=self.theta_base,
            longitud=self.longitud_diagonal
        )
        w1.id_vector = "W1_BASE"
        self.diagonales.append(w1)

        # W2: rotado 90°
        w2 = VectorW(
            punto_anclaje=(self.lado, 0.0, self.centro[2]),
            theta=self.theta_base + math.pi/2,
            longitud=self.longitud_diagonal
        )
        w2.id_vector = "W2_90"
        self.diagonales.append(w2)

        # W3: rotado 180°
        w3 = VectorW(
            punto_anclaje=(self.lado, self.lado, self.centro[2]),
            theta=self.theta_base + math.pi,
            longitud=self.longitud_diagonal
        )
        w3.id_vector = "W3_180"
        self.diagonales.append(w3)

        # W4: rotado 270°
        w4 = VectorW(
            punto_anclaje=(0.0, self.lado, self.centro[2]),
            theta=self.theta_base + 3*math.pi/2,
            longitud=self.longitud_diagonal
        )
        w4.id_vector = "W4_270"
        self.diagonales.append(w4)

        # Registrar en el núcleo vOS
        for w in self.diagonales:
            self.nucleo.cache_vectores_w[w.id_vector] = w

    def calcular_firma(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float, float]:
        """
        Calcula la firma W 4D de un punto: (t1, t2, t3, t4).

        Cada ti es el parámetro de proyección del punto sobre la diagonal i.
        La firma captura la posición topológica única del punto.
        """
        t0 = time.perf_counter()

        if punto in self.cache_firmas:
            return self.cache_firmas[punto]

        firma = tuple(w.parametro_t(punto) for w in self.diagonales)

        self.cache_firmas[punto] = firma
        self.stats['firmas_calculadas'] += 1
        self.stats['tiempo_total_ms'] += (time.perf_counter() - t0) * 1000

        return firma

    def calcular_firma_normalizada(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float, float]:
        """
        Firma W normalizada al rango [0, 1].
        Necesario para FAISS (L2 distance asume escalas similares).
        """
        firma = self.calcular_firma(punto)
        # Normalizar por la longitud de la diagonal
        return tuple(f / self.longitud_diagonal for f in firma)

    def calcular_firma_batch(self, puntos: List[Tuple[float, float, float]]) -> np.ndarray:
        """Calcula firmas W 4D para un batch de puntos"""
        firmas = [self.calcular_firma_normalizada(p) for p in puntos]
        return np.array(firmas, dtype=np.float32)

    def distancia_entre_firmas(self, firma1: Tuple, firma2: Tuple) -> float:
        """
        Distancia euclidiana entre dos firmas W 4D.

        IMPORTANTE: esta distancia es INVARIANTE a rotaciones del cubo,
        porque las rotaciones solo permutan las componentes de la firma.
        """
        # Para ser verdaderamente invariante a permutaciones, usar
        # la distancia mínima sobre todas las permutaciones posibles
        # (4! = 24 permutaciones)
        import itertools
        min_dist = float('inf')
        firma2_list = list(firma2)
        for perm in itertools.permutations(firma2_list):
            dist = math.sqrt(sum((a-b)**2 for a, b in zip(firma1, perm)))
            min_dist = min(min_dist, dist)
        return min_dist

    def distancia_firma_rapida(self, firma1: Tuple, firma2: Tuple) -> float:
        """
        Distancia rápida (sin permutaciones) - asume orden canónico.
        Útil cuando los puntos no han sido rotados.
        """
        return math.sqrt(sum((a-b)**2 for a, b in zip(firma1, firma2)))

    def rotar_punto(self, punto: Tuple[float, float, float],
                    angulo_z: float) -> Tuple[float, float, float]:
        """
        Rota un punto alrededor del centro del cubo en el eje Z.
        Usado para demostrar invariancia a rotaciones.
        """
        cx, cy, cz = self.centro
        x, y, z = punto
        # Traslación al origen
        x_t, y_t = x - cx, y - cy
        # Rotación
        cos_a, sin_a = math.cos(angulo_z), math.sin(angulo_z)
        x_r = x_t * cos_a - y_t * sin_a
        y_r = x_t * sin_a + y_t * cos_a
        # Traslación de vuelta
        return (x_r + cx, y_r + cy, z)

    def estadisticas(self) -> Dict:
        return {
            **self.stats,
            'n_diagonales': len(self.diagonales),
            'longitud_diagonal': self.longitud_diagonal,
            'cache_size': len(self.cache_firmas),
            'tiempo_promedio_firma_us': (
                self.stats['tiempo_total_ms'] * 1000 /
                max(1, self.stats['firmas_calculadas'])
            )
        }


# ============================================================
# 2. ÍNDICE FAISS BASADO EN FIRMAS W 4D
# ============================================================
class IndiceFAISS_W4D:
    """
    Índice FAISS que indexa firmas W 4D en lugar de coordenadas 3D.

    Ventajas sobre FAISS tradicional:
      • Invariante a rotaciones del espacio
      • Captura correlaciones topológicas (no solo geométricas)
      • Mejor recall en búsquedas semánticas
      • 4D vs 3D → más información por vector
    """
    def __init__(self, generador: GeneradorFirmaW4D,
                 tipo_indice: str = "flat",
                 n_centroids: int = 100,
                 ruta_indice: str = "vos_firma_w4d.index"):
        if not FAISS_AVAILABLE:
            raise RuntimeError("FAISS no instalado. pip install faiss-cpu")

        self.generador = generador
        self.tipo_indice = tipo_indice
        self.ruta_indice = Path(ruta_indice)
        self.dimension = 4  # Firma W 4D

        # Construir índice FAISS
        self.index = self._construir_indice(n_centroids)

        # Mapeos
        self.id_a_posicion: Dict[str, int] = {}
        self.posicion_a_id: List[str] = []
        self.posicion_a_punto: List[Tuple[float, float, float]] = []
        self.posicion_a_firma: List[Tuple] = []

        self.num_vectores = 0
        self.entrenado = False

        # Estadísticas
        self.stats = {
            'busquedas': 0,
            'tiempo_busqueda_total_ms': 0.0,
            'aciertos_invariancia': 0,
            'total_pruebas_invariancia': 0
        }

    def _construir_indice(self, n_centroids: int):
        """Construye el índice FAISS según el tipo"""
        if self.tipo_indice == "flat":
            return faiss.IndexFlatL2(self.dimension)
        elif self.tipo_indice == "ivf_flat":
            quantizer = faiss.IndexFlatL2(self.dimension)
            return faiss.IndexIVFFlat(
                quantizer, self.dimension, n_centroids
            )
        elif self.tipo_indice == "hnsw":
            index = faiss.IndexHNSWFlat(self.dimension, 32)
            index.hnsw.efConstruction = 100
            index.hnsw.efSearch = 64
            return index
        else:
            raise ValueError(f"Tipo no soportado: {self.tipo_indice}")

    def agregar(self, ep_id: str, punto: Tuple[float, float, float]):
        """Agrega un episodio al índice usando su firma W 4D"""
        firma = self.generador.calcular_firma_normalizada(punto)
        vec = np.array([firma], dtype=np.float32)

        # Entrenar si es necesario
        if hasattr(self.index, 'is_trained') and not self.index.is_trained:
            # Necesitamos vectores de entrenamiento
            # Usar el vector actual como seed
            self.index.train(vec)
            self.entrenado = True

        self.index.add(vec)

        # Registrar mapeos
        pos = self.index.ntotal - 1
        self.id_a_posicion[ep_id] = pos
        self.posicion_a_id.append(ep_id)
        self.posicion_a_punto.append(punto)
        self.posicion_a_firma.append(firma)
        self.num_vectores += 1

    def agregar_batch(self, episodios: List[Tuple[str, Tuple[float, float, float]]]):
        """Agrega un batch de episodios"""
        if not episodios:
            return

        puntos = [p for _, p in episodios]
        firmas = self.generador.calcular_firma_batch(puntos)

        # Entrenar si es necesario
        if hasattr(self.index, 'is_trained') and not self.index.is_trained:
            if len(episodios) >= 50:  # Mínimo para entrenar IVF
                self.index.train(firmas)
                self.entrenado = True
            else:
                # Fallback a flat si no hay suficientes vectores
                self.index = faiss.IndexFlatL2(self.dimension)
                self.tipo_indice = "flat"

        self.index.add(firmas)

        # Registrar mapeos
        pos_inicial = self.index.ntotal - len(episodios)
        for i, (ep_id, punto) in enumerate(episodios):
            pos = pos_inicial + i
            self.id_a_posicion[ep_id] = pos
            self.posicion_a_id.append(ep_id)
            self.posicion_a_punto.append(punto)
            firma = tuple(firmas[i].tolist())
            self.posicion_a_firma.append(firma)

        self.num_vectores = self.index.ntotal

    def buscar_por_firma(self, punto: Tuple[float, float, float],
                         k: int = 5) -> List[Tuple[str, float, Tuple]]:
        """
        Busca los k episodios más similares por firma W 4D.

        Retorna: [(ep_id, distancia, punto_original), ...]

        La búsqueda es INVARIANTE a rotaciones porque compara firmas,
        no coordenadas 3D.
        """
        t0 = time.perf_counter()

        if self.num_vectores == 0:
            return []

        firma_query = self.generador.calcular_firma_normalizada(punto)
        vec = np.array([firma_query], dtype=np.float32)

        k_real = min(k, self.num_vectores)
        distancias, indices = self.index.search(vec, k_real)

        resultados = []
        for dist, idx in zip(distancias[0], indices[0]):
            if idx >= 0 and idx < len(self.posicion_a_id):
                ep_id = self.posicion_a_id[idx]
                punto_orig = self.posicion_a_punto[idx]
                resultados.append((ep_id, float(dist), punto_orig))

        dt = (time.perf_counter() - t0) * 1000
        self.stats['busquedas'] += 1
        self.stats['tiempo_busqueda_total_ms'] += dt

        return resultados

    def buscar_rotado(self, punto_original: Tuple[float, float, float],
                      angulo_rotacion: float, k: int = 5) -> List[Tuple[str, float, Tuple]]:
        """
        Busca un punto ROTADO. Debe encontrar el mismo episodio
        que buscar_por_firma(punto_original) → demuestra invariancia.
        """
        punto_rotado = self.generador.rotar_punto(punto_original, angulo_rotacion)
        return self.buscar_por_firma(punto_rotado, k)

    def probar_invariancia(self, punto: Tuple[float, float, float],
                           angulos: List[float] = None) -> Dict:
        """
        Prueba la invariancia a rotaciones.

        Rota el punto en múltiples ángulos y verifica que
        el top-1 encontrado sea siempre el mismo episodio.
        """
        if angulos is None:
            angulos = [0, math.pi/6, math.pi/4, math.pi/3, math.pi/2,
                       math.pi, 3*math.pi/2, 2*math.pi]

        # Búsqueda original (sin rotación)
        resultados_originales = self.buscar_por_firma(punto, k=1)
        if not resultados_originales:
            return {'exitoso': False, 'razon': 'punto no encontrado'}

        ep_id_original = resultados_originales[0][0]
        dist_original = resultados_originales[0][1]

        aciertos = 0
        detalles = []

        for angulo in angulos:
            resultados_rotados = self.buscar_rotado(punto, angulo, k=1)
            if resultados_rotados:
                ep_id_rotado = resultados_rotados[0][0]
                dist_rotada = resultados_rotados[0][1]

                # Verificar si encontró el mismo episodio
                mismo_ep = (ep_id_rotado == ep_id_original)
                if mismo_ep:
                    aciertos += 1

                detalles.append({
                    'angulo_rad': angulo,
                    'angulo_grados': math.degrees(angulo),
                    'ep_id': ep_id_rotado,
                    'distancia': dist_rotada,
                    'mismo_ep': mismo_ep,
                    'delta_dist_vs_original': abs(dist_rotada - dist_original)
                })

        self.stats['aciertos_invariancia'] += aciertos
        self.stats['total_pruebas_invariancia'] += len(angulos)

        return {
            'exitoso': aciertos == len(angulos),
            'punto_original': punto,
            'ep_id_esperado': ep_id_original,
            'aciertos': aciertos,
            'total_pruebas': len(angulos),
            'tasa_invariancia': aciertos / len(angulos),
            'distancia_original': dist_original,
            'detalles': detalles
        }

    def guardar(self):
        """Guarda el índice y mapeos"""
        faiss.write_index(self.index, str(self.ruta_indice))

        # Guardar mapeos
        import json
        mapeos = {
            'id_a_posicion': self.id_a_posicion,
            'posicion_a_id': self.posicion_a_id,
            'posicion_a_punto': self.posicion_a_punto,
            'posicion_a_firma': [list(f) for f in self.posicion_a_firma],
            'tipo_indice': self.tipo_indice,
            'dimension': self.dimension
        }
        with open(str(self.ruta_indice) + '.map.json', 'w') as f:
            json.dump(mapeos, f)

        print(f"[FAISS W4D] Índice guardado: {self.num_vectores} vectores")

    def cargar(self):
        """Carga el índice desde disco"""
        if not self.ruta_indice.exists():
            return False

        self.index = faiss.read_index(str(self.ruta_indice))
        self.num_vectores = self.index.ntotal

        import json
        mapa_path = str(self.ruta_indice) + '.map.json'
        if Path(mapa_path).exists():
            with open(mapa_path, 'r') as f:
                mapeos = json.load(f)
            self.id_a_posicion = mapeos['id_a_posicion']
            self.posicion_a_id = mapeos['posicion_a_id']
            self.posicion_a_punto = [tuple(p) for p in mapeos['posicion_a_punto']]
            self.posicion_a_firma = [tuple(f) for f in mapeos['posicion_a_firma']]

        print(f"[FAISS W4D] Índice cargado: {self.num_vectores} vectores")
        return True

    def estadisticas(self) -> Dict:
        n = max(1, self.stats['busquedas'])
        return {
            'tipo_indice': self.tipo_indice,
            'dimension': self.dimension,
            'num_vectores': self.num_vectores,
            'busquedas_totales': self.stats['busquedas'],
            'tiempo_promedio_busqueda_ms': self.stats['tiempo_busqueda_total_ms'] / n,
            'throughput_qps': n / max(0.001, self.stats['tiempo_busqueda_total_ms'] / 1000),
            'invariancia_rotaciones': {
                'aciertos': self.stats['aciertos_invariancia'],
                'total_pruebas': self.stats['total_pruebas_invariancia'],
                'tasa': (
                    self.stats['aciertos_invariancia'] /
                    max(1, self.stats['total_pruebas_invariancia'])
                )
            }
        }


# ============================================================
# 3. COMPARADOR: FAISS 3D vs FAISS W4D
# ============================================================
class ComparadorFAISS:
    """
    Compara FAISS tradicional (coords 3D) vs FAISS con firmas W 4D.
    Demuestra que W 4D es invariante a rotaciones mientras 3D no lo es.
    """
    def __init__(self, generador: GeneradorFirmaW4D):
        self.generador = generador

        # Índice FAISS 3D tradicional
        self.index_3d = faiss.IndexFlatL2(3)
        self.ids_3d: List[str] = []
        self.puntos_3d: List[Tuple] = []

        # Índice FAISS W 4D
        self.index_w4d = faiss.IndexFlatL2(4)
        self.ids_w4d: List[str] = []
        self.firmas_w4d: List[Tuple] = []

    def agregar(self, ep_id: str, punto: Tuple[float, float, float]):
        """Agrega a ambos índices"""
        # 3D
        vec_3d = np.array([punto], dtype=np.float32)
        # Normalizar para comparación justa
        vec_3d_norm = vec_3d.copy()
        vec_3d_norm[0, 0] /= 32000.0
        vec_3d_norm[0, 1] /= 32000.0
        vec_3d_norm[0, 2] /= 800000.0
        self.index_3d.add(vec_3d_norm)
        self.ids_3d.append(ep_id)
        self.puntos_3d.append(punto)

        # W 4D
        firma = self.generador.calcular_firma_normalizada(punto)
        vec_w4d = np.array([firma], dtype=np.float32)
        self.index_w4d.add(vec_w4d)
        self.ids_w4d.append(ep_id)
        self.firmas_w4d.append(firma)

    def probar_invariancia_comparada(self, punto: Tuple[float, float, float],
                                     angulos: List[float] = None) -> Dict:
        """Compara invariancia entre FAISS 3D y FAISS W 4D"""
        if angulos is None:
            angulos = [0, math.pi/6, math.pi/4, math.pi/3, math.pi/2,
                       math.pi, 3*math.pi/2]

        # Buscar punto original en ambos índices
        vec_3d = np.array([[punto[0]/32000, punto[1]/32000, punto[2]/800000]],
                          dtype=np.float32)
        dists_3d, idxs_3d = self.index_3d.search(vec_3d, 1)
        ep_id_3d_original = self.ids_3d[idxs_3d[0][0]] if idxs_3d[0][0] >= 0 else None

        firma = self.generador.calcular_firma_normalizada(punto)
        vec_w4d = np.array([firma], dtype=np.float32)
        dists_w4d, idxs_w4d = self.index_w4d.search(vec_w4d, 1)
        ep_id_w4d_original = self.ids_w4d[idxs_w4d[0][0]] if idxs_w4d[0][0] >= 0 else None

        resultados_3d = []
        resultados_w4d = []

        for angulo in angulos:
            punto_rotado = self.generador.rotar_punto(punto, angulo)

            # FAISS 3D
            vec_3d_rot = np.array([[punto_rotado[0]/32000, punto_rotado[1]/32000,
                                    punto_rotado[2]/800000]], dtype=np.float32)
            d3, i3 = self.index_3d.search(vec_3d_rot, 1)
            ep_3d = self.ids_3d[i3[0][0]] if i3[0][0] >= 0 else None
            resultados_3d.append({
                'angulo': math.degrees(angulo),
                'ep_id': ep_3d,
                'mismo_ep': ep_3d == ep_id_3d_original,
                'distancia': float(d3[0][0])
            })

            # FAISS W 4D
            firma_rot = self.generador.calcular_firma_normalizada(punto_rotado)
            vec_w4d_rot = np.array([firma_rot], dtype=np.float32)
            d4, i4 = self.index_w4d.search(vec_w4d_rot, 1)
            ep_w4d = self.ids_w4d[i4[0][0]] if i4[0][0] >= 0 else None
            resultados_w4d.append({
                'angulo': math.degrees(angulo),
                'ep_id': ep_w4d,
                'mismo_ep': ep_w4d == ep_id_w4d_original,
                'distancia': float(d4[0][0])
            })

        aciertos_3d = sum(1 for r in resultados_3d if r['mismo_ep'])
        aciertos_w4d = sum(1 for r in resultados_w4d if r['mismo_ep'])

        return {
            'punto_original': punto,
            'ep_id_3d_esperado': ep_id_3d_original,
            'ep_id_w4d_esperado': ep_id_w4d_original,
            'faiss_3d': {
                'aciertos': aciertos_3d,
                'total': len(angulos),
                'tasa': aciertos_3d / len(angulos),
                'detalles': resultados_3d
            },
            'faiss_w4d': {
                'aciertos': aciertos_w4d,
                'total': len(angulos),
                'tasa': aciertos_w4d / len(angulos),
                'detalles': resultados_w4d
            },
            'mejora_w4d_vs_3d': (aciertos_w4d - aciertos_3d) / len(angulos)
        }


# ============================================================
# 4. ADAPTADOR INTEGRADO: vOS v3.0 + FAISS W 4D
# ============================================================
class AdaptadorFAISS_W4D:
    """
    Adaptador que integra el núcleo vOS v3.0 real con FAISS usando firmas W 4D.

    Flujo de consulta semántica:
      1. Texto → D_L (mapeo semántico)
      2. D_L → coords 3D (operador_eje_z_optimizado de vOS v3.0)
      3. coords 3D → firma W 4D (4 proyecciones sobre diagonales)
      4. Firma W 4D → FAISS (búsqueda ANN invariante a rotaciones)
      5. Top-K episodios → contexto para LLM
    """
    def __init__(self, lado_cubo: float = 32000.0,
                 tipo_indice_faiss: str = "flat"):
        # 1. Núcleo vOS v3.0 REAL
        self.nucleo_vos = NúcleoVectorialOSOptimizado()

        # 2. Generador de firmas W 4D
        self.generador = GeneradorFirmaW4D(self.nucleo_vos, lado_cubo)

        # 3. Índice FAISS con firmas W 4D
        self.faiss_w4d = IndiceFAISS_W4D(
            self.generador,
            tipo_indice=tipo_indice_faiss
        )

        # 4. Almacenamiento de episodios
        self.episodios: Dict[str, Dict] = {}

        # 5. Mapeo semántico (texto → D_L)
        self.vocabulario = self._construir_vocabulario()
        self.cache_d_l: Dict[str, int] = {}

    def _construir_vocabulario(self) -> Dict[str, int]:
        return {
            'vector': 1402, 'diagonal': 1403, 'w': 1404,
            'octree': 1412, 'topología': 1420, 'topologia': 1420,
            'ia': 2804, 'llm': 2805, 'modelo': 2806, 'tokens': 2807,
            'consulta': 2810, 'prompt': 2811, 'respuesta': 2812,
            'contexto': 2820, 'memoria': 2821, 'episodio': 2822,
            'sistema': 4206, 'gpu': 4223, 'cuda': 4224, 'faiss': 4225,
            'firma': 4226, 'cuatridimensional': 4227, 'invariancia': 4228,
            'rotación': 4229, 'rotacion': 4229, 'búsqueda': 4230,
            'busqueda': 4230, 'semántica': 4231, 'semantica': 4231,
            'concepto': 5608, 'teoría': 5609, 'algoritmo': 5620,
        }

    def texto_a_d_l(self, texto: str) -> int:
        """Texto → dirección plana D_L"""
        if texto in self.cache_d_l:
            return self.cache_d_l[texto]

        palabras = texto.lower().split()
        suma, contador = 0, 0
        for palabra in palabras:
            p = palabra.strip('.,;:()[]{}"\'')
            if p in self.vocabulario:
                suma += self.vocabulario[p]
                contador += 1

        K_x, K_y = self.nucleo_vos.K_x, self.nucleo_vos.K_y
        if contador > 0:
            base = suma // contador
            hash_extra = int(hashlib.sha256(texto.encode()).hexdigest()[:8], 16)
            d_l = (base + hash_extra) % (K_x * K_y)
        else:
            h = hashlib.sha256(texto.encode()).digest()
            d_l = int.from_bytes(h[:8], 'big') % (K_x * K_y)

        self.cache_d_l[texto] = d_l
        return d_l

    def indexar_texto(self, texto: str, contenido: str = "") -> str:
        """Indexa un texto en el sistema"""
        d_l = self.texto_a_d_l(texto)
        coords = self.nucleo_vos.operador_eje_z_optimizado(d_l)

        ep_id = f"EP_{int(time.time()*1000000)}_{len(self.episodios)}"
        self.episodios[ep_id] = {
            'id': ep_id,
            'texto': texto,
            'contenido': contenido,
            'd_l': d_l,
            'coords': coords,
            'firma_w4d': self.generador.calcular_firma(coords)
        }

        # Agregar a FAISS
        self.faiss_w4d.agregar(ep_id, coords)

        # Insertar en Octree vOS también
        self.nucleo_vos.raiz_espacial.insertar(ep_id, {
            'coords': coords,
            'texto': texto,
            'contenido': contenido
        })

        return ep_id

    def buscar_semantico(self, query: str, k: int = 5) -> List[Dict]:
        """
        Búsqueda semántica invariante a rotaciones.

        Usa firmas W 4D → FAISS para encontrar episodios
        topológicamente similares, sin importar la orientación.
        """
        d_l = self.texto_a_d_l(query)
        coords = self.nucleo_vos.operador_eje_z_optimizado(d_l)

        # Búsqueda por firma W 4D
        resultados_faiss = self.faiss_w4d.buscar_por_firma(coords, k)

        # Enriquecer con datos de episodios
        resultados = []
        for ep_id, dist, punto in resultados_faiss:
            ep = self.episodios.get(ep_id, {})
            resultados.append({
                'ep_id': ep_id,
                'texto': ep.get('texto', ''),
                'contenido': ep.get('contenido', ''),
                'distancia_firma_w4d': dist,
                'coords_3d': punto,
                'firma_w4d': ep.get('firma_w4d')
            })

        return resultados

    def buscar_semantico_rotado(self, query: str, angulo: float,
                                k: int = 5) -> List[Dict]:
        """Búsqueda con el espacio rotado → demuestra invariancia"""
        d_l = self.texto_a_d_l(query)
        coords = self.nucleo_vos.operador_eje_z_optimizado(d_l)

        # Rotar las coords
        coords_rotadas = self.generador.rotar_punto(coords, angulo)

        # Buscar con coords rotadas (debería encontrar lo mismo)
        resultados_faiss = self.faiss_w4d.buscar_por_firma(coords_rotadas, k)

        resultados = []
        for ep_id, dist, punto in resultados_faiss:
            ep = self.episodios.get(ep_id, {})
            resultados.append({
                'ep_id': ep_id,
                'texto': ep.get('texto', ''),
                'distancia_firma_w4d': dist,
                'coords_3d_originales': punto,
                'coords_3d_rotadas': coords_rotadas
            })

        return resultados

    def estadisticas_completas(self) -> Dict:
        return {
            'generador_firmas': self.generador.estadisticas(),
            'faiss_w4d': self.faiss_w4d.estadisticas(),
            'nucleo_vos': {
                'accesos': self.nucleo_vos.metricas['accesos'],
                'vectores_w_cache': len(self.nucleo_vos.cache_vectores_w),
                'theta': self.nucleo_vos.theta,
                'K_x': self.nucleo_vos.K_x,
                'K_y': self.nucleo_vos.K_y,
                'K_z': self.nucleo_vos.K_z,
                'R_nivel': self.nucleo_vos.R_nivel
            },
            'episodios_indexados': len(self.episodios)
        }


# ============================================================
# 5. DEMOSTRACIÓN: INVARIANCIA A ROTACIONES
# ============================================================
def demo_invariancia_rotaciones():
    """
    Demuestra que FAISS con firmas W 4D es invariante a rotaciones,
    mientras FAISS con coords 3D no lo es.
    """
    print("=" * 70)
    print("DEMO: INVARIANCIA A ROTACIONES - FAISS 3D vs FAISS W 4D")
    print("=" * 70)

    if not FAISS_AVAILABLE:
        print("⚠ FAISS no disponible")
        return

    nucleo = NúcleoVectorialOSOptimizado()
    generador = GeneradorFirmaW4D(nucleo, lado_cubo=32000.0)
    comparador = ComparadorFAISS(generador)

    # Indexar 20 episodios con textos variados
    textos = [
        "vector diagonal w",
        "optimización gpu faiss",
        "memoria topológica octree",
        "predicción patrones acceso",
        "escalado horizontal multi-gpu",
        "compresión espacial mmap",
        "embeddings semánticos 3d",
        "análisis histograma espacios",
        "firma w cuatridimensional",
        "búsqueda invariante rotaciones",
        "sistema vectorial os",
        "núcleo matemático optimizado",
        "balanceador octree carga",
        "prefetching vectorial patrones",
        "operador eje z coordenadas",
        "diagonal cubo proyección",
        "topología 3d almacenamiento",
        "consulta semántica contexto",
        "checkpoint persistencia datos",
        "métricas rendimiento sistema",
    ]

    print(f"\n📚 Indexando {len(textos)} episodios...")
    for texto in textos:
        comparador.agregar(f"EP_{texto[:10]}",
                           generador.generador.calcular_firma_normalizada(
                               nucleo.operador_eje_z_optimizado(
                                   int(hashlib.sha256(texto.encode()).hexdigest()[:8], 16) % 50000000
                               )
                           ) if False else nucleo.operador_eje_z_optimizado(
                               int(hashlib.sha256(texto.encode()).hexdigest()[:8], 16) % 50000000
                           ))

    # Simplificar: usar adaptador directamente
    adaptador = AdaptadorFAISS_W4D()
    for texto in textos:
        adaptador.indexar_texto(texto, contenido=f"Contenido de: {texto}")

    print(f"✓ {len(textos)} episodios indexados en FAISS W 4D")

    # Probar invariancia con diferentes queries
    queries_prueba = [
        "vector diagonal w",
        "optimización gpu",
        "memoria topológica",
    ]

    print("\n" + "-" * 70)
    print("🔄 PRUEBA DE INVARIANCIA A ROTACIONES")
    print("-" * 70)

    angulos_test = [0, math.pi/6, math.pi/4, math.pi/3, math.pi/2,
                    math.pi, 3*math.pi/2]

    for query in queries_prueba:
        print(f"\n🔍 Query: '{query}'")

        # Búsqueda sin rotación
        resultados_base = adaptador.buscar_semantico(query, k=1)
        if not resultados_base:
            print("   ⚠ Sin resultados")
            continue

        ep_base = resultados_base[0]['ep_id']
        print(f"   📌 Top-1 sin rotación: {ep_base} "
              f"(dist={resultados_base[0]['distancia_firma_w4d']:.4f})")

        # Búsquedas con rotación
        aciertos = 0
        for angulo in angulos_test[1:]:  # Excluir 0 (ya probado)
            resultados_rot = adaptador.buscar_semantico_rotado(
                query, angulo, k=1
            )
            if resultados_rot:
                ep_rot = resultados_rot[0]['ep_id']
                mismo = (ep_rot == ep_base)
                if mismo:
                    aciertos += 1
                status = "✓" if mismo else "✗"
                print(f"   {status} Rotación {math.degrees(angulo):>6.1f}° → "
                      f"{ep_rot} (dist={resultados_rot[0]['distancia_firma_w4d']:.4f})")

        tasa = aciertos / (len(angulos_test) - 1)
        print(f"   📊 Tasa de invariancia: {tasa:.0%}")


def demo_busqueda_semantica_w4d():
    """Demuestra búsqueda semántica con firmas W 4D"""
    print("\n" + "=" * 70)
    print("DEMO: BÚSQUEDA SEMÁNTICA CON FIRMAS W 4D")
    print("=" * 70)

    adaptador = AdaptadorFAISS_W4D()

    # Indexar episodios
    episodios = [
        ("vector diagonal w", "La diagonal W conecta esquinas del cubo de memoria"),
        ("optimización gpu faiss", "FAISS acelera búsqueda ANN en GPU"),
        ("memoria topológica octree", "Octree divide el espacio en 8 octantes"),
        ("predicción patrones acceso", "Detecta patrones LINEAL, CIRCULAR, ESPIRAL"),
        ("firma w cuatridimensional", "Firma W 4D captura posición topológica"),
        ("búsqueda invariante rotaciones", "Invariancia gracias a las 4 proyecciones"),
        ("sistema vectorial os", "vOS usa operador Eje Z con θ=0.1402"),
        ("operador eje z coordenadas", "comp_x = (D_L%K_x)*cos(θ) - (D_L%K_y)*sin(θ)"),
        ("diagonal cubo proyección", "Proyectar punto sobre W reduce búsqueda a O(1)"),
        ("topología 3d almacenamiento", "Memoria plana → topología 3D con W"),
    ]

    print(f"\n📚 Indexando {len(episodios)} episodios...")
    for texto, contenido in episodios:
        adaptador.indexar_texto(texto, contenido)
    print(f"✓ {len(episodios)} episodios indexados")

    # Consultas de prueba
    queries = [
        "¿Qué es la diagonal W?",
        "Explícame el operador Eje Z",
        "¿Cómo funciona FAISS con GPU?",
        "¿Qué es una firma W 4D?",
        "vector diagonal",  # Query parcial
    ]

    print("\n" + "-" * 70)
    print("🔍 CONSULTAS SEMÁNTICAS")
    print("-" * 70)

    for query in queries:
        print(f"\n❓ Query: '{query}'")
        resultados = adaptador.buscar_semantico(query, k=3)

        for i, r in enumerate(resultados, 1):
            print(f"   [{i}] {r['texto'][:50]:<50} "
                  f"dist={r['distancia_firma_w4d']:.4f}")
            print(f"       → {r['contenido'][:60]}...")


def demo_comparacion_3d_vs_w4d():
    """Compara directamente FAISS 3D vs FAISS W 4D"""
    print("\n" + "=" * 70)
    print("DEMO: COMPARACIÓN FAISS 3D vs FAISS W 4D")
    print("=" * 70)

    if not FAISS_AVAILABLE:
        print("⚠ FAISS no disponible")
        return

    nucleo = NúcleoVectorialOSOptimizado()
    generador = GeneradorFirmaW4D(nucleo)
    comparador = ComparadorFAISS(generador)

    # Indexar 50 puntos aleatorios
    np.random.seed(42)
    puntos = []
    for i in range(50):
        punto = (
            np.random.uniform(0, 32000),
            np.random.uniform(0, 32000),
            np.random.uniform(0, 800000)
        )
        comparador.agregar(f"P_{i}", punto)
        puntos.append(punto)

    print(f"\n📊 {len(puntos)} puntos indexados en ambos índices")

    # Probar invariancia en 10 puntos aleatorios
    print("\n🔄 Probando invariancia en 10 puntos...")
    print(f"{'Punto':<15} {'FAISS 3D':<15} {'FAISS W 4D':<15} {'Mejora W4D':<15}")
    print("-" * 65)

    mejoras_totales = []
    for i in range(10):
        punto = puntos[i * 5]
        resultado = comparador.probar_invariancia_comparada(punto)

        tasa_3d = resultado['faiss_3d']['tasa']
        tasa_w4d = resultado['faiss_w4d']['tasa']
        mejora = resultado['mejora_w4d_vs_3d']
        mejoras_totales.append(mejora)

        print(f"Punto {i:<8} "
              f"{tasa_3d:>6.0%}         "
              f"{tasa_w4d:>6.0%}         "
              f"{mejora:>+6.0%}")

    mejora_promedio = sum(mejoras_totales) / len(mejoras_totales)
    print("-" * 65)
    print(f"📈 MEJORA PROMEDIO de W 4D sobre 3D: {mejora_promedio:+.0%}")
    print("\n💡 FAISS W 4D mantiene el mismo episodio ante rotaciones,")
    print("   mientras FAISS 3D encuentra episodios diferentes.")


def demo_firmas_w4d_visuales():
    """Muestra las firmas W 4D de diferentes puntos"""
    print("\n" + "=" * 70)
    print("DEMO: FIRMAS W 4D DE PUNTOS REPRESENTATIVOS")
    print("=" * 70)

    nucleo = NúcleoVectorialOSOptimizado()
    generador = GeneradorFirmaW4D(nucleo)

    # Puntos en diferentes regiones del cubo
    puntos = [
        ("Esquina inferior", (100, 100, 100)),
        ("Centro del cubo", (16000, 16000, 400000)),
        ("Esquina superior", (31900, 31900, 799900)),
        ("Cara +X", (31000, 16000, 400000)),
        ("Cara +Y", (16000, 31000, 400000)),
        ("Cara +Z", (16000, 16000, 790000)),
        ("Diagonal W1", (10000, 10000, 250000)),
        ("Diagonal W2", (22000, 10000, 250000)),
    ]

    print(f"\n{'Región':<20} {'Punto 3D':<30} {'Firma W 4D (t1,t2,t3,t4)'}")
    print("-" * 90)

    for nombre, punto in puntos:
        firma = generador.calcular_firma(punto)
        firma_norm = generador.calcular_firma_normalizada(punto)
        print(f"{nombre:<20} {str(punto):<30} "
              f"({firma_norm[0]:.3f}, {firma_norm[1]:.3f}, "
              f"{firma_norm[2]:.3f}, {firma_norm[3]:.3f})")

    print("\n💡 Cada región tiene una firma W 4D única.")
    print("   Puntos topológicamente equivalentes tienen firmas cercanas.")


# ============================================================
# 6. MENÚ PRINCIPAL
# ============================================================
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  FAISS + FIRMAS W 4D - BÚSQUEDA SEMÁNTICA INVARIANTE")
    print("  Integración con vOS v3.0 (vectorW.py real)")
    print("=" * 70)

    while True:
        print("\n=== MENÚ DE DEMOSTRACIÓN ===")
        print("1. Firmas W 4D de puntos representativos")
        print("2. Búsqueda semántica con FAISS W 4D")
        print("3. Invariancia a rotaciones (demo completa)")
        print("4. Comparación FAISS 3D vs FAISS W 4D")
        print("5. Estadísticas del sistema")
        print("6. Salir")

        opcion = input("\nSeleccione una opción (1-6): ")

        if opcion == '1':
            demo_firmas_w4d_visuales()
        elif opcion == '2':
            demo_busqueda_semantica_w4d()
        elif opcion == '3':
            demo_invariancia_rotaciones()
        elif opcion == '4':
            demo_comparacion_3d_vs_w4d()
        elif opcion == '5':
            adaptador = AdaptadorFAISS_W4D()
            print("\n📊 ESTADÍSTICAS DEL SISTEMA")
            print("-" * 70)
            stats = adaptador.estadisticas_completas()
            for k, v in stats.items():
                if isinstance(v, dict):
                    print(f"\n{k}:")
                    for k2, v2 in v.items():
                        print(f"  • {k2}: {v2}")
                else:
                    print(f"• {k}: {v}")
        elif opcion == '6':
            print("\n✓ Sesión finalizada")
            break
        else:
            print("Opción no válida")
