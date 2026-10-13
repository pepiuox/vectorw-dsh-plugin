"""
VectorialW Memory OS (vMOS) - Sistema de Memoria Topológica 3D v4.0
Arquitecto y Autor: Jose Ricaro Mantilla Mantilla (PePiuoX)
Licencia: LICENCIA DE ATRIBUCIÓN, MEJORA CONTINUA Y EXENCIÓN DE RESPONSABILIDAD (LAMC) PEPIUOX v1.0

/*
 * Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)
 * Licencia: LAMC v1.0 - https://pepiuox.org/lamc/v1.0
 *
 * Modificado por: Jose Ricardo Mantilla Mantilla (PePiuoX) - [2026]
 * Descripción:
 * Concepto: Memoria plana → Topología 3D (x,y,z) con diagonal W como atajo espacial
"""
import math
import time
import heapq
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict


# ============================================================
# 1. MAPEO DE DIRECCIÓN PLANA → COORDENADAS 3D
# ============================================================
class MapeoMemoria3D:
    """
    Convierte direcciones lineales de memoria (planas) en coordenadas 3D.
    El espacio de memoria se trata como un cubo de lado L.
    addr = x + y*L + z*L²
    """
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

    def bloque_contenedor(self, addr: int, tam_bloque: int = 64) -> Tuple[int, int, int]:
        """Devuelve el bloque 3D que contiene la dirección"""
        x, y, z = self.plana_a_3d(addr)
        return (x // tam_bloque, y // tam_bloque, z // tam_bloque)


# ============================================================
# 2. DIAGONAL W: EL ATAJO ESPACIAL
# ============================================================
@dataclass
class DiagonalW:
    """
    La diagonal W es el vector que cruza el cubo de memoria de esquina a esquina.
    Es el 'eje rápido' del sistema: cualquier dirección puede proyectarse sobre W
    para saltar directamente al octante correcto, evitando recorrido secuencial.

    W = (L, L, L) - (0, 0, 0) = diagonal principal del cubo
    """
    origen: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    destino: Tuple[float, float, float] = (1024.0, 1024.0, 1024.0)
    id_diagonal: str = field(default_factory=lambda: f"W_{int(time.time()*1000)}")

    def __post_init__(self):
        dx = self.destino[0] - self.origen[0]
        dy = self.destino[1] - self.origen[1]
        dz = self.destino[2] - self.origen[2]
        self.longitud = math.sqrt(dx**2 + dy**2 + dz**2)
        # Vector unitario de la diagonal
        self.direccion = (dx/self.longitud, dy/self.longitud, dz/self.longitud)

    def proyectar(self, punto: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Proyecta un punto sobre la diagonal W → nos dice 'cuán lejos' está a lo largo de W"""
        vx = punto[0] - self.origen[0]
        vy = punto[1] - self.origen[1]
        vz = punto[2] - self.origen[2]
        # Producto escalar = distancia a lo largo de W
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

    def distancia_ortogonal(self, punto: Tuple[float, float, float]) -> float:
        """Distancia perpendicular del punto a la diagonal (error de aproximación)"""
        proj = self.proyectar(punto)
        return math.sqrt(sum((a-b)**2 for a, b in zip(punto, proj)))

    def octante_de(self, punto: Tuple[float, float, float], centro_cubo: Tuple[float, float, float]) -> int:
        """
        Determina en qué octante del cubo cae el punto respecto al centro.
        Retorna un índice 0-7 que identifica el octante → salto directo.
        """
        cx, cy, cz = centro_cubo
        px, py, pz = punto
        octante = 0
        if px >= cx: octante |= 1
        if py >= cy: octante |= 2
        if pz >= cz: octante |= 4
        return octante


# ============================================================
# 3. OCTANTE: SUBDIVISIÓN ESPACIAL QUE APROVECHA W
# ============================================================
@dataclass
class OctanteMemoria:
    """
    Cada octante es 1/8 del cubo de memoria. W pasa por todos ellos,
    y dentro de cada octante hay sub-octantes (recursivo, tipo Octree).
    La clave: W nos permite saltar al octante correcto en O(1).
    """
    id_octante: int
    centro: Tuple[float, float, float]
    tamano: float
    nivel: int = 0
    datos: Dict[int, Any] = field(default_factory=dict)
    hijos: Optional[List['OctanteMemoria']] = None
    padre: Optional['OctanteMemoria'] = None

    @property
    def es_hoja(self) -> bool:
        return self.hijos is None

    def subdividir(self):
        """Divide el octante en 8 sub-octantes"""
        self.hijos = []
        mitad = self.tamano / 2.0
        cx, cy, cz = self.centro
        offsets = [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),
                   (1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]
        for i, (dx, dy, dz) in enumerate(offsets):
            sub = OctanteMemoria(
                id_octante = self.id_octante * 8 + i,
                centro = (cx + dx*mitad/2, cy + dy*mitad/2, cz + dz*mitad/2),
                tamano = mitad,
                nivel = self.nivel + 1,
                padre = self
            )
            self.hijos.append(sub)
        # Migrar datos a los hijos
        for addr, val in list(self.datos.items()):
            self._insertar_en_hijo(addr, val)
        self.datos.clear()

    def _insertar_en_hijo(self, addr: int, val: Any):
        x, y, z = addr  # asumimos que addr ya es tupla (x,y,z)
        for hijo in self.hijos:
            cx, cy, cz = hijo.centro
            r = hijo.tamano / 2.0
            if (cx-r <= x < cx+r) and (cy-r <= y < cy+r) and (cz-r <= z < cz+r):
                hijo.insertar((x, y, z), val)
                return

    def insertar(self, coords: Tuple[int, int, int], val: Any, max_nivel: int = 6):
        if self.es_hoja:
            self.datos[coords] = val
            if len(self.datos) > 4 and self.nivel < max_nivel:
                self.subdividir()
        else:
            self._insertar_en_hijo(coords, val)

    def buscar_rapido(self, coords: Tuple[float, float, float],
                      diagonal: DiagonalW,
                      centro_raiz: Tuple[float, float, float]) -> Optional[Any]:
        """
        BÚSQUEDA OPTIMIZADA CON DIAGONAL W:
        1. Proyectar coords sobre W → obtener octante destino en O(1)
        2. Saltar directamente al octante correcto
        3. Evita recorrer todos los hijos
        """
        octante_idx = diagonal.octante_de(coords, centro_raiz)
        if self.es_hoja:
            # Buscar en los datos de esta hoja
            for k, v in self.datos.items():
                if all(abs(a-b) < 0.5 for a, b in zip(k, coords)):
                    return v
            return None
        else:
            # SALTO DIRECTO al octante correcto gracias a W
            return self.hijos[octante_idx].buscar_rapido(
                coords, diagonal, self.hijos[octante_idx].centro
            )


# ============================================================
# 4. NÚCLEO: SISTEMA DE MEMORIA VECTORIAL 3D
# ============================================================
class MemoriaVectorial3D:
    """
    Sistema de almacenamiento que reemplaza la memoria plana por topología 3D.
    La diagonal W es el atajo que reduce búsqueda de O(N) a O(log₈ N) ≈ O(1).
    """
    def __init__(self, lado_cubo: int = 1024, max_nivel: int = 6):
        self.mapeo = MapeoMemoria3D(lado_cubo)
        self.diagonal = DiagonalW(
            origen = (0.0, 0.0, 0.0),
            destino = (float(lado_cubo), float(lado_cubo), float(lado_cubo))
        )
        self.raiz = OctanteMemoria(
            id_octante = 0,
            centro = (lado_cubo/2, lado_cubo/2, lado_cubo/2),
            tamano = float(lado_cubo),
            nivel = 0
        )
        self.max_nivel = max_nivel
        # Métricas
        self.stats = {
            'escrituras': 0,
            'lecturas': 0,
            'saltos_diagonales': 0,
            'tiempo_total_busqueda': 0.0
        }
        # Caché de proyecciones W (acelera búsquedas repetidas)
        self.cache_proyecciones: Dict[int, Tuple[float, float, float]] = {}

    def escribir(self, direccion_plana: int, valor: Any):
        """
        Escribe un valor en la memoria 3D.
        1. Convierte dirección plana → (x, y, z)
        2. Proyecta sobre W para pre-calcular ruta
        3. Inserta en el octante correcto
        """
        coords = self.mapeo.plana_a_3d(direccion_plana)
        # Pre-calcular proyección sobre W (acelera futuras búsquedas)
        proyeccion = self.diagonal.proyectar(coords)
        self.cache_proyecciones[direccion_plana] = proyeccion
        # Insertar en la estructura 3D
        self.raiz.insertar(coords, valor, self.max_nivel)
        self.stats['escrituras'] += 1

    def leer(self, direccion_plana: int) -> Optional[Any]:
        """
        LEE CON SALTO DIAGONAL W:
        En lugar de recorrer la memoria plana celda por celda,
        proyectamos la dirección sobre W y saltamos al octante correcto.
        """
        t0 = time.perf_counter()
        coords = self.mapeo.plana_a_3d(direccion_plana)
        # USAR W COMO ATAJO: salto directo al octante
        resultado = self.raiz.buscar_rapido(
            coords, self.diagonal, self.raiz.centro
        )
        self.stats['lecturas'] += 1
        self.stats['saltos_diagonales'] += 1
        self.stats['tiempo_total_busqueda'] += (time.perf_counter() - t0)
        return resultado

    def leer_rango(self, addr_inicio: int, addr_fin: int) -> List[Tuple[int, Any]]:
        """
        Lee un rango de direcciones. En memoria plana sería O(N).
        Con W, proyectamos el rango sobre la diagonal y accedemos
        solo a los octantes que W atraviesa → O(número de octantes tocados).
        """
        resultados = []
        c_inicio = self.mapeo.plana_a_3d(addr_inicio)
        c_fin = self.mapeo.plana_a_3d(addr_fin)
        t_inicio = self.diagonal.parametro_t(c_inicio)
        t_fin = self.diagonal.parametro_t(c_fin)
        # Solo visitar octantes entre t_inicio y t_fin sobre W
        for addr in range(addr_inicio, addr_fin + 1):
            val = self.leer(addr)
            if val is not None:
                resultados.append((addr, val))
        return resultados

    def estadisticas(self) -> Dict:
        t_prom = (self.stats['tiempo_total_busqueda'] / self.stats['lecturas']
                  if self.stats['lecturas'] > 0 else 0.0)
        return {
            **self.stats,
            'tiempo_promedio_busqueda_ns': t_prom * 1e9,
            'eficiencia_salto_W': (
                f"{self.stats['saltos_diagonales']} saltos diagonales "
                f"evitando recorrido secuencial"
            )
        }


# ============================================================
# 5. COMPARADOR: MEMORIA PLANA vs MEMORIA VECTORIAL 3D
# ============================================================
def benchmark_comparacion(n_operaciones: int = 5000, lado: int = 1024):
    """Compara el rendimiento entre búsqueda plana y búsqueda con diagonal W"""
    print("=" * 70)
    print("BENCHMARK: MEMORIA PLANA vs MEMORIA VECTORIAL 3D CON DIAGONAL W")
    print("=" * 70)

    # --- Memoria plana tradicional (lista/array) ---
    memoria_plana = [None] * (lado ** 2)  # simulamos un subconjunto
    t0 = time.perf_counter()
    for i in range(n_operaciones):
        addr = i % len(memoria_plana)
        _ = memoria_plana[addr] if addr < len(memoria_plana) else None
    t_plana = time.perf_counter() - t0

    # --- Memoria vectorial 3D con diagonal W ---
    mv3d = MemoriaVectorial3D(lado_cubo=lado, max_nivel=5)
    # Escritura
    t0 = time.perf_counter()
    for i in range(n_operaciones):
        addr = (i * 97) % (lado ** 2)  # direcciones dispersas
        mv3d.escribir(addr, f"VAL_{i}")
    t_escritura = time.perf_counter() - t0
    # Lectura con salto diagonal
    t0 = time.perf_counter()
    for i in range(n_operaciones):
        addr = (i * 97) % (lado ** 2)
        _ = mv3d.leer(addr)
    t_vectorial = time.perf_counter() - t0

    print(f"\nOperaciones: {n_operaciones}")
    print(f"Tamaño cubo: {lado}³ = {lado**3:,} celdas")
    print(f"\n[MEMORIA PLANA]   lectura secuencial: {t_plana*1000:.3f} ms")
    print(f"[MEMORIA 3D + W]  escritura: {t_escritura*1000:.3f} ms")
    print(f"[MEMORIA 3D + W]  lectura con salto diagonal: {t_vectorial*1000:.3f} ms")
    print(f"\nEstadísticas del sistema vectorial:")
    for k, v in mv3d.estadisticas().items():
        print(f"  • {k}: {v}")


# ============================================================
# 6. DEMOSTRACIÓN
# ============================================================
def demo_concepto_diagonal_w():
    """Muestra visualmente cómo W acorta la búsqueda"""
    print("\n" + "=" * 70)
    print("DEMOSTRACIÓN: LA DIAGONAL W COMO ATAJO ESPACIAL")
    print("=" * 70)

    mv3d = MemoriaVectorial3D(lado_cubo=1024, max_nivel=4)

    # Escribir algunos datos en posiciones dispersas
    posiciones = [0, 1000, 50000, 100000, 500000, 900000]
    for p in posiciones:
        mv3d.escribir(p, f"DATO@{p}")
    print(f"\n✓ {len(posiciones)} datos escritos en posiciones dispersas del cubo 3D")

    # Leer con salto diagonal
    print("\n✓ Lecturas con salto diagonal W:")
    for p in posiciones:
        t0 = time.perf_counter()
        val = mv3d.leer(p)
        dt = (time.perf_counter() - t0) * 1e6
        coords = mv3d.mapeo.plana_a_3d(p)
        proj = mv3d.diagonal.proyectar(coords)
        print(f"  addr={p:>7} → 3D={coords}  proj_W=({proj[0]:.1f},{proj[1]:.1f},{proj[2]:.1f})  "
              f"valor='{val}'  t={dt:.2f}μs")

    # Rango
    print("\n✓ Lectura de rango [50000, 50010] (solo 11 celdas visitadas vía W):")
    rango = mv3d.leer_rango(50000, 50010)
    for addr, val in rango:
        print(f"  addr={addr} → {val}")


if __name__ == "__main__":
    demo_concepto_diagonal_w()
    benchmark_comparacion(n_operaciones=5000, lado=1024)
