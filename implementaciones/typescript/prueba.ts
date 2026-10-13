/**
 * Verificación del port TypeScript contra los vectores de prueba compartidos.
 *
 * Los vectores (`pruebas/vectores_w.json`) los genera la implementación de
 * Python, que a su vez está verificada contra el núcleo original de VectorW
 * (`vendor/vectorW_py/vectorW_6.py`). Si esta prueba pasa, el port TypeScript
 * produce exactamente las mismas firmas y las mismas decisiones de caché.
 *
 *     node implementaciones/typescript/prueba.ts
 *
 * VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
 * https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1
 */

import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  CacheSemanticaW,
  FamiliaDiagonalesW,
  tokenizar,
  type Punto,
} from './vectorw_w.ts'

const AQUI = dirname(fileURLToPath(import.meta.url))
const RAIZ = resolve(AQUI, '..', '..')
const TOLERANCIA = 1e-9

let comprobaciones = 0
let fallos = 0

/** Comprueba una condición y registra el resultado. */
function afirmar(condicion: boolean, mensaje: string): void {
  comprobaciones++
  if (!condicion) {
    fallos++
    console.error(`  FALLO: ${mensaje}`)
  }
}

/** Compara dos listas de números con tolerancia. */
function casiIgual(a: readonly number[], b: readonly number[], etiqueta: string): void {
  if (a.length !== b.length) {
    afirmar(false, `${etiqueta}: longitud ${a.length} != ${b.length}`)
    return
  }
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i] - b[i]) > TOLERANCIA) {
      afirmar(false, `${etiqueta}[${i}]: ${a[i]} != ${b[i]}`)
      return
    }
  }
  afirmar(true, etiqueta)
}

const vectores = JSON.parse(
  readFileSync(join(RAIZ, 'pruebas', 'vectores_w.json'), 'utf8'),
)

const { lado_cubo: lado, n_espacios: nEspacios } = vectores.config
const familia = new FamiliaDiagonalesW(lado, nEspacios)

console.log(`Vectores: ${vectores.puntos.length} puntos, ${vectores.textos.length} textos, ` +
  `${vectores.distancias.length} distancias, ${vectores.cache.length} casos de caché`)
console.log(`Cubo: lado ${lado}, ${nEspacios} espacios por diagonal\n`)

// --- 1. Tokenización -------------------------------------------------------
for (const [texto, esperado] of Object.entries<string[]>(vectores.tokenizacion)) {
  const obtenido = tokenizar(texto)
  afirmar(
    JSON.stringify(obtenido) === JSON.stringify(esperado),
    `tokenizar(${JSON.stringify(texto)}): ${JSON.stringify(obtenido)} != ${JSON.stringify(esperado)}`,
  )
}

// --- 2. Firmas de puntos 3D ------------------------------------------------
for (const caso of vectores.puntos) {
  const punto = caso.punto as unknown as Punto
  casiIgual(familia.componentesDe(punto), caso.componentes, `componentes ${JSON.stringify(caso.punto)}`)
  casiIgual(familia.firmaDePunto(punto), caso.firma, `firma ${JSON.stringify(caso.punto)}`)
  afirmar(
    JSON.stringify(familia.espaciosDe(punto)) === JSON.stringify(caso.espacios),
    `espacios ${JSON.stringify(caso.punto)}: ${JSON.stringify(familia.espaciosDe(punto))} != ${JSON.stringify(caso.espacios)}`,
  )
}

// --- 3. Firmas de textos ---------------------------------------------------
for (const caso of vectores.textos) {
  const f = familia.firmaDeTexto(caso.texto)
  afirmar(
    JSON.stringify(f.tokens) === JSON.stringify(caso.tokens),
    `tokens de ${JSON.stringify(caso.texto)}: ${JSON.stringify(f.tokens)} != ${JSON.stringify(caso.tokens)}`,
  )
  casiIgual(f.coords, caso.coords, `centroide de ${JSON.stringify(caso.texto)}`)
  casiIgual(f.componentes, caso.componentes, `componentes de ${JSON.stringify(caso.texto)}`)
  casiIgual(f.firma, caso.firma, `firma de ${JSON.stringify(caso.texto)}`)
  afirmar(
    JSON.stringify(f.espacios) === JSON.stringify(caso.espacios),
    `espacios de ${JSON.stringify(caso.texto)}`,
  )
}

// --- 4. Distancias y umbral ------------------------------------------------
for (const caso of vectores.distancias) {
  const fa = familia.firmaDeTexto(caso.a)
  const fb = familia.firmaDeTexto(caso.b)
  const [dist, solape] = familia.distancia(fa, fb)
  if (Math.abs(dist - caso.distancia) > TOLERANCIA) {
    afirmar(false, `distancia ${JSON.stringify(caso.b)}: ${dist} != ${caso.distancia}`)
  } else {
    afirmar(true, `distancia ${JSON.stringify(caso.b)}`)
  }
  if (Math.abs(solape - caso.solapamiento) > TOLERANCIA) {
    afirmar(false, `solapamiento ${JSON.stringify(caso.b)}: ${solape} != ${caso.solapamiento}`)
  } else {
    afirmar(true, `solapamiento ${JSON.stringify(caso.b)}`)
  }
  // La decisión aplica la misma regla que la caché: distancia bajo umbral y
  // al menos un token en común.
  const umbral = vectores.config.umbral_similitud as number
  afirmar(
    (dist <= umbral && solape > 0) === caso.acierto,
    `decision ${JSON.stringify(caso.b)}: se esperaba acierto=${caso.acierto} ` +
      `(d=${dist}, solape=${solape}, umbral=${umbral})`,
  )
}

// --- 5. Comportamiento de la caché ----------------------------------------
const cache = new CacheSemanticaW(familia, vectores.config.umbral_similitud)
cache.guardar('optimizar consultas vectoriales con octree', 'resultado-caro', 4200)
cache.guardar('como funciona la cache LRU con TTL y frecuencia', 'otro', 60)

for (const esperado of vectores.cache) {
  const obtenido = cache.buscar(esperado.consulta)
  afirmar(
    obtenido.hit === esperado.hit,
    `caché ${JSON.stringify(esperado.consulta)}: hit ${obtenido.hit} != ${esperado.hit}`,
  )
  if (esperado.hit) {
    afirmar(
      obtenido.kind === esperado.kind,
      `caché ${JSON.stringify(esperado.consulta)}: kind ${obtenido.kind} != ${esperado.kind}`,
    )
    if (Math.abs((obtenido.distancia ?? -1) - esperado.distancia) > TOLERANCIA) {
      afirmar(false, `caché distancia: ${obtenido.distancia} != ${esperado.distancia}`)
    } else {
      afirmar(true, `caché distancia ${JSON.stringify(esperado.consulta)}`)
    }
  }
}

const stats = cache.estadisticas()
afirmar(
  stats.hitsExactos === vectores.cache_estadisticas.hits_exactos &&
    stats.hitsSemanticos === vectores.cache_estadisticas.hits_semanticos &&
    stats.fallos === vectores.cache_estadisticas.fallos,
  `estadísticas de caché: ${JSON.stringify(stats)}`,
)

// --- Resultado -------------------------------------------------------------
console.log(`\nRESULTADO: ${comprobaciones - fallos}/${comprobaciones} comprobaciones OK`)
if (fallos > 0) {
  console.error(`  ${fallos} FALLOS`)
  process.exit(1)
}
console.log('  El port TypeScript coincide con la referencia Python.')
