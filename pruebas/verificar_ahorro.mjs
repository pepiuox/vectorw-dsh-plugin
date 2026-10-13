// Demostración del ahorro de tokens: guarda resultados y comprueba que una
// consulta parecida se resuelve desde la caché W sin volver a buscar.
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const requireDesdePerfil = createRequire(
  pathToFileURL(join(process.env.DSH_HOME ?? 'C:/Users/PePiuoX/.dsh', 'profiles', 'package.json')).href,
)
const { defineTool } = await import(
  pathToFileURL(requireDesdePerfil.resolve('@deepseek-ai/dsh-tools')).href
)
const { apply } = await import(
  pathToFileURL(requireDesdePerfil.resolve('@deepseek-ai/dsh-plugin-vectorw')).href
)

const registradas = new Map()
const ctx = {
  tools: { register: (d) => (registradas.set(d.name, d), () => {}) },
  on() {}, get: () => undefined, inject() {},
  logger: Object.assign(() => ({ warn: console.log, info: () => {}, error: console.log })),
}
await apply(ctx, { rutaCore: 'C:/Users/PePiuoX/Documents/Github/VectorW/vectorW_py' })
await registradas.get('vector_purge').execute({}, {})

const guardar = (q, v, t) => registradas.get('vector_cache_store').execute({ query: q, value: v, tokens: t }, {})
const comprobar = (q) => registradas.get('vector_cache_check').execute({ query: q }, {})

// Resultados "caros" que un agente obtendría de buscar en la web o leer archivos.
const corpus = [
  ['optimizar consultas vectoriales con octree y poda espacial', 'Poda por octante: descarta 7/8 del espacio por nivel.', 4200],
  ['como funciona la cache LRU con TTL y frecuencia', 'Expulsion por score = frecuencia*0.7 - antiguedad*0.3.', 1800],
  ['que es la firma W 4D y las diagonales del cubo', 'Cada punto se proyecta sobre 4 diagonales dando una firma invariante a permutaciones.', 2600],
  ['configurar FAISS con firmas W para busqueda ANN', 'Indice por firma W4D con distancia minima sobre 24 permutaciones.', 3100],
  ['estrategias de prediccion Markov de orden superior', 'Backoff de orden 4 a 1 con suavizado de Laplace por diagonal.', 2200],
]
for (const [q, v, t] of corpus) await guardar(q, v, t)

console.log('\n=== A. Consulta idéntica (debe ser HIT exacto) ===')
const a = await comprobar('optimizar consultas vectoriales con octree y poda espacial')
console.log(a.resumen.split('\n')[0])

console.log('\n=== B. Reformulación de la misma tarea (HIT semántico) ===')
const b = await comprobar('optimizar consultas vectoriales con octree y podado espacial')
console.log(b.resumen.split('\n')[0])

console.log('\n=== C. Consulta nueva (MISS, el agente debe trabajar) ===')
const c = await comprobar('desplegar el plugin en linux con systemd')
console.log(c.resumen)

const stats = await registradas.get('vector_stats').execute({}, {})
console.log('\n=== Balance de ahorro ===')
console.log(stats.resumen)
process.exit(0)
