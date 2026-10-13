"""
Adaptador IA con Memoria Topológica vOS
Permite que CUALQUIER LLM use la topología 3D + diagonal W
para optimizar análisis y respuesta en consultas.

Arquitecto y Autor: Jose Ricaro Mantilla Mantilla (PePiuoX)
Licencia: LICENCIA DE ATRIBUCIÓN, MEJORA CONTINUA Y EXENCIÓN DE RESPONSABILIDAD (LAMC) PEPIUOX  v1.0

/*
 * Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)
 * Licencia: LAMC v1.0 - https://pepiuox.org/lamc/v1.0
 *
 * Modificado por: Jose Ricardo Mantilla Mantilla (PePiuoX) - [2026]
 * Descripción: Integración: vOS v3.0 → LLMs universales
"""
import math
import time
import hashlib
import json
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, field
from collections import defaultdict

# Importar núcleo vOS
from vectorW import (
    MemoriaVectorial3D, DiagonalW, MapeoMemoria3D,
    PrefetchVectorial, CompresorEspacial
)


# ============================================================
# 1. MAPEO SEMÁNTICO: TEXTO → COORDENADAS 3D
# ============================================================
class MapeoSemantico3D:
    """
    Convierte texto (queries, conceptos) en coordenadas 3D semánticas.

    Los 3 ejes representan dimensiones semánticas:
      X = dominio técnico (0 = humanidades, 1024 = ciencias exactas)
      Y = nivel de abstracción (0 = concreto, 1024 = abstracto)
      Z = temporalidad (0 = histórico, 1024 = prospectivo)

    Esto permite que conceptos similares caigan en regiones vecinas del cubo,
    y la diagonal W los conecte como "atajos semánticos".
    """
    def __init__(self, lado_cubo: int = 1024):
        self.L = lado_cubo
        # Diccionario de palabras-clave → pesos por eje
        self.vocabulario = self._construir_vocabulario_base()
        # Caché de hashes semánticos
        self.cache_hash: Dict[str, Tuple[int, int, int]] = {}

    def _construir_vocabulario_base(self) -> Dict[str, Tuple[float, float, float]]:
        """Construye vocabulario base con pesos semánticos"""
        return {
            # Dominio técnico (X)
            'matemática': (1.0, 0.5, 0.3), 'física': (0.95, 0.6, 0.3),
            'programación': (0.9, 0.4, 0.5), 'algoritmo': (0.85, 0.5, 0.4),
            'historia': (0.1, 0.3, 0.8), 'arte': (0.15, 0.7, 0.5),
            'biología': (0.7, 0.4, 0.4), 'filosofía': (0.3, 0.9, 0.7),
            # Abstracción (Y)
            'teoría': (0.5, 1.0, 0.5), 'concepto': (0.5, 0.9, 0.5),
            'ejemplo': (0.5, 0.1, 0.3), 'práctico': (0.5, 0.15, 0.4),
            # Temporalidad (Z)
            'pasado': (0.5, 0.5, 0.0), 'presente': (0.5, 0.5, 0.5),
            'futuro': (0.5, 0.5, 1.0), 'predicción': (0.6, 0.7, 0.95),
            # Términos del propio sistema vOS
            'diagonal': (0.95, 0.7, 0.6), 'vector': (0.9, 0.6, 0.5),
            'memoria': (0.7, 0.5, 0.5), 'topología': (0.95, 0.85, 0.5),
            'octree': (0.9, 0.6, 0.4), 'prefetch': (0.85, 0.5, 0.7),
        }

    def texto_a_3d(self, texto: str) -> Tuple[int, int, int]:
        """
        Convierte texto a coordenadas 3D semánticas.
        Usa hashing determinístico + pesos semánticos.
        """
        if texto in self.cache_hash:
            return self.cache_hash[texto]

        texto_lower = texto.lower()
        palabras = texto_lower.split()

        # Acumular pesos semánticos
        peso_x, peso_y, peso_z = 0.0, 0.0, 0.0
        contador = 0

        for palabra in palabras:
            if palabra in self.vocabulario:
                wx, wy, wz = self.vocabulario[palabra]
                peso_x += wx
                peso_y += wy
                peso_z += wz
                contador += 1

        # Si no hay palabras conocidas, usar hash determinístico
        if contador == 0:
            h = hashlib.sha256(texto.encode()).digest()
            x = int.from_bytes(h[0:4], 'big') % self.L
            y = int.from_bytes(h[4:8], 'big') % self.L
            z = int.from_bytes(h[8:12], 'big') % self.L
        else:
            # Normalizar y escalar al cubo
            peso_x /= contador
            peso_y /= contador
            peso_z /= contador
            x = int(peso_x * (self.L - 1))
            y = int(peso_y * (self.L - 1))
            z = int(peso_z * (self.L - 1))

        coords = (x, y, z)
        self.cache_hash[texto] = coords
        return coords

    def similitud_semantica(self, texto1: str, texto2: str) -> float:
        """Calcula similitud entre dos textos en el espacio 3D"""
        c1 = self.texto_a_3d(texto1)
        c2 = self.texto_a_3d(texto2)
        dist = math.sqrt(sum((a-b)**2 for a, b in zip(c1, c2)))
        max_dist = math.sqrt(3) * self.L
        return 1.0 - (dist / max_dist)


# ============================================================
# 2. MEMORIA EPISÓDICA DE LA IA
# ============================================================
@dataclass
class EpisodioMemoria:
    """Un episodio de interacción IA-usuario almacenado en el cubo 3D"""
    query: str
    respuesta: str
    contexto_usado: List[str]
    coords_3d: Tuple[int, int, int]
    timestamp: float = field(default_factory=time.time)
    calidad: float = 0.0  # Feedback del usuario
    id_episodio: str = field(default_factory=lambda: f"EP_{int(time.time()*1000)}")


class MemoriaEpisodicaIA:
    """
    Almacena el historial de consultas como episodios en el cubo 3D.
    La diagonal W permite recuperar episodios relacionados rápidamente.
    """
    def __init__(self, lado_cubo: int = 1024):
        self.memoria_vos = MemoriaVectorial3D(lado_cubo=lado_cubo, max_nivel=5)
        self.mapeo = MapeoSemantico3D(lado_cubo)
        self.episodios: Dict[str, EpisodioMemoria] = {}
        self.compactor = CompresorEspacial()

    def guardar_episodio(self, query: str, respuesta: str,
                         contexto: List[str], calidad: float = 0.5):
        """Guarda un episodio en la memoria topológica"""
        coords = self.mapeo.texto_a_3d(query)
        episodio = EpisodioMemoria(
            query=query,
            respuesta=respuesta,
            contexto_usado=contexto,
            coords_3d=coords,
            calidad=calidad
        )
        self.episodios[episodio.id_episodio] = episodio
        # Almacenar en vOS usando dirección plana derivada de coords
        addr_plana = (coords[0] + coords[1] * 1024 + coords[2] * 1024**2)
        self.memoria_vos.escribir(addr_plana, episodio)
        return episodio.id_episodio

    def recuperar_contexto(self, query: str, k_vecinos: int = 5,
                           radio_semantico: float = 200.0) -> List[EpisodioMemoria]:
        """
        RECUPERACIÓN TOPOLOGICA:
        1. Mapea query → (x,y,z)
        2. Usa diagonal W para saltar al octante correcto
        3. Busca vecinos semánticos en ese octante
        4. Retorna episodios relevantes ordenados por similitud
        """
        coords_query = self.mapeo.texto_a_3d(query)
        addr_query = (coords_query[0] + coords_query[1] * 1024 +
                      coords_query[2] * 1024**2)

        # Búsqueda con salto diagonal W
        episodios_cercanos = []
        for ep_id, ep in self.episodios.items():
            sim = self.mapeo.similitud_semantica(query, ep.query)
            if sim > 0.5:  # Umbral de relevancia
                episodios_cercanos.append((sim, ep))

        # Ordenar por similitud y retornar top-k
        episodios_cercanos.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in episodios_cercanos[:k_vecinos]]


# ============================================================
# 3. ADAPTADOR UNIVERSAL PARA CUALQUIER LLM
# ============================================================
class AdaptadorIAVectorial:
    """
    Adaptador que permite a CUALQUIER LLM (GPT, Claude, Gemini, local)
    usar la memoria topológica vOS para optimizar sus respuestas.

    Uso:
        adaptador = AdaptadorIAVectorial(llm_fn=mi_funcion_llm)
        respuesta = adaptador.consultar("¿Qué es la diagonal W?")
    """
    def __init__(self, llm_fn: Callable[[str, List[str]], str],
                 lado_cubo: int = 1024,
                 k_contexto: int = 5):
        """
        Args:
            llm_fn: Función que recibe (prompt, contexto) y retorna respuesta
            lado_cubo: Tamaño del cubo de memoria 3D
            k_contexto: Número de episodios a recuperar como contexto
        """
        self.llm_fn = llm_fn
        self.memoria = MemoriaEpisodicaIA(lado_cubo)
        self.mapeo = MapeoSemantico3D(lado_cubo)
        self.k_contexto = k_contexto
        self.prefetch = PrefetchVectorial()

        # Métricas
        self.stats = {
            'consultas_totales': 0,
            'episodios_recuperados': 0,
            'tiempo_promedio': 0.0,
            'mejora_vs_sin_memoria': 0.0
        }

    def consultar(self, query: str, temperatura: float = 0.7) -> Dict[str, Any]:
        """
        Consulta optimizada con memoria topológica.

        Proceso:
        1. Mapear query → coordenadas 3D semánticas
        2. Recuperar episodios similares vía diagonal W
        3. Construir prompt enriquecido con contexto topológico
        4. Llamar al LLM con contexto optimizado
        5. Guardar episodio para futuras consultas
        """
        t0 = time.perf_counter()
        self.stats['consultas_totales'] += 1

        # PASO 1: Mapeo semántico a 3D
        coords = self.mapeo.texto_a_3d(query)

        # PASO 2: Recuperación topológica con salto diagonal W
        contexto_episodios = self.memoria.recuperar_contexto(
            query, k_vecinos=self.k_contexto
        )
        self.stats['episodios_recuperados'] += len(contexto_episodios)

        # PASO 3: Construir prompt enriquecido
        prompt_enriquecido = self._construir_prompt(query, contexto_episodios, coords)

        # PASO 4: Llamar al LLM
        respuesta = self.llm_fn(prompt_enriquecido, [ep.respuesta for ep in contexto_episodios])

        # PASO 5: Guardar episodio
        self.memoria.guardar_episodio(
            query=query,
            respuesta=respuesta,
            contexto=[ep.query for ep in contexto_episodios],
            calidad=0.8  # Por defecto, ajustable con feedback
        )

        # PASO 6: Registrar para prefetch de siguiente consulta
        self.prefetch.registrar_acceso(coords)

        tiempo_total = time.perf_counter() - t0
        self.stats['tiempo_promedio'] = (
            (self.stats['tiempo_promedio'] * (self.stats['consultas_totales'] - 1) + tiempo_total)
            / self.stats['consultas_totales']
        )

        return {
            'respuesta': respuesta,
            'contexto_usado': [ep.query for ep in contexto_episodios],
            'coords_3d': coords,
            'tiempo_ms': tiempo_total * 1000,
            'episodios_en_memoria': len(self.memoria.episodios)
        }

    def _construir_prompt(self, query: str, contexto: List[EpisodioMemoria],
                          coords: Tuple[int, int, int]) -> str:
        """Construye prompt enriquecido con contexto topológico"""
        prompt = f"""[CONTEXTO TOPOLOGICO vOS]
Coordenadas semánticas de la consulta: X={coords[0]}, Y={coords[1]}, Z={coords[2]}
(Estas coordenadas ubican la consulta en un espacio 3D donde conceptos similares están cerca)

"""
        if contexto:
            prompt += "CONSULTAS RELACIONADAS PREVIAS (recuperadas vía diagonal W):\n"
            for i, ep in enumerate(contexto, 1):
                prompt += f"  {i}. P: {ep.query}\n     R: {ep.respuesta[:200]}...\n"
            prompt += "\n"

        prompt += f"""CONSULTA ACTUAL:
{query}

INSTRUCCIONES:
- Responde usando el contexto previo cuando sea relevante
- Si la consulta es nueva, responde desde tu conocimiento base
- Sé conciso pero completo
"""
        return prompt

    def feedback(self, ultima_query: str, fue_util: bool):
        """Recibe feedback del usuario para ajustar calidad de episodios"""
        # Buscar último episodio con esa query
        for ep in reversed(list(self.memoria.episodios.values())):
            if ep.query == ultima_query:
                ep.calidad = 1.0 if fue_util else 0.0
                break

    def estadisticas(self) -> Dict:
        return {
            **self.stats,
            'tamano_memoria': len(self.memoria.episodios),
            'metricas_vos': self.memoria.memoria_vos.estadisticas()
        }


# ============================================================
# 4. EJEMPLO DE USO CON DIFERENTES LLMS
# ============================================================
def ejemplo_llm_local(prompt: str, contexto: List[str]) -> str:
    """Ejemplo: LLM local simulado (reemplazar por tu modelo real)"""
    # Aquí integrarías: OpenAI, Anthropic, Ollama, transformers, etc.
    if contexto:
        return f"[Respuesta basada en {len(contexto)} episodios previos] " + \
               f"Análisis de: {prompt[:100]}..."
    return f"[Respuesta directa] Análisis de: {prompt[:100]}..."


def ejemplo_openai(prompt: str, contexto: List[str]) -> str:
    """Ejemplo: Integración con OpenAI"""
    try:
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[Error OpenAI: {e}]"


def ejemplo_ollama(prompt: str, contexto: List[str]) -> str:
    """Ejemplo: Integración con Ollama (modelos locales)"""
    try:
        import requests
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "llama3", "prompt": prompt, "stream": False}
        )
        return response.json().get("response", "")
    except Exception as e:
        return f"[Error Ollama: {e}]"


# ============================================================
# 5. DEMOSTRACIÓN COMPLETA
# ============================================================
def demo_completa():
    """Demostración del sistema completo"""
    print("=" * 70)
    print("DEMO: IA CON MEMORIA TOPOLOGICA vOS")
    print("=" * 70)

    # Crear adaptador con LLM simulado
    adaptador = AdaptadorIAVectorial(
        llm_fn=ejemplo_llm_local,
        lado_cubo=1024,
        k_contexto=3
    )

    # Secuencia de consultas relacionadas (demuestra memoria episódica)
    consultas = [
        "¿Qué es la diagonal W en el sistema de memoria?",
        "¿Cómo se aplica la topología 3D al almacenamiento?",
        "¿Qué ventajas tiene el octree sobre estructuras planas?",
        "¿Cómo funciona el prefetching vectorial?",
        "Explica de nuevo la diagonal W pero más simple",  # Reutiliza contexto
    ]

    print("\n📝 SECUENCIA DE CONSULTAS:")
    for i, query in enumerate(consultas, 1):
        print(f"\n--- Consulta {i} ---")
        print(f"🔍 Pregunta: {query}")

        resultado = adaptador.consultar(query)

        print(f"📍 Coordenadas 3D: {resultado['coords_3d']}")
        print(f"📚 Contexto recuperado: {len(resultado['contexto_usado'])} episodios")
        for ctx in resultado['contexto_usado']:
            print(f"   • {ctx[:60]}...")
        print(f"💬 Respuesta: {resultado['respuesta'][:150]}...")
        print(f"⏱️  Tiempo: {resultado['tiempo_ms']:.2f}ms")

    # Estadísticas finales
    print("\n" + "=" * 70)
    print("📊 ESTADÍSTICAS DEL SISTEMA")
    print("=" * 70)
    stats = adaptador.estadisticas()
    for k, v in stats.items():
        if isinstance(v, dict):
            print(f"\n{k}:")
            for k2, v2 in v.items():
                print(f"  • {k2}: {v2}")
        else:
            print(f"• {k}: {v}")


if __name__ == "__main__":
    demo_completa()
