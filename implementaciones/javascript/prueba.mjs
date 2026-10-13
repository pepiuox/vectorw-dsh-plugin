/**
 * Verificación del port JavaScript contra los vectores de prueba compartidos.
 *
 * Los vectores los genera la implementación de Python, verificada contra el
 * núcleo original de VectorW. Además se comprueba que el SHA-256 propio
 * coincide con el de `node:crypto`.
 *
 *     node implementaciones/javascript/prueba.mjs
 *
 * VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
 * https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1
 */

import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  CacheSemanticaW,
  FamiliaDiagonalesW,
  sha256Hex,
  tokenizar,
} from './vectorw_w.mjs'

const AQUI = dirname(fileURLToPath(import.meta.url))
const RAIZ = resolve(AQUI, '..', '..')
const TOLERANCIA = 1e-9

let comprobaciones = 0
let fallos = 0

function afirmar(condicion, mensaje) {
  comprobaciones++
  if (!condicion) {
    fallos++
    console.error(`  FALLO: ${mensaje}`)
  }
}

function casiIgual(a, b, etiqueta) {
  if (a.length !== b.length) return afirmar(false, `${etiqueta}: longitud distinta`)
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i] - b[i]) > TOLERANCIA) {
      return afirmar(false, `${etiqueta}[${i}]: ${a[i]} != ${b[i]}`)
    }
  }
  afirmar(true, etiqueta)
}

// --- 0. SHA-256 propio frente a node:crypto --------------------------------
for (const texto of ['', 'a', 'abc', 'octree', 'optimizar consultas', 'áéíóú ñ', 'x'.repeat(200)]) {
  const propio = sha256Hex(texto)
  const crypto = createHash('sha256').update(texto, 'utf8').digest('hex')
  afirmar(propio === crypto, `sha256(${JSON.stringify(texto)}): ${propio} != ${crypto}`)
}

const vectores = JSON.parse(readFileSync(join(RAIZ, 'pruebas', 'vectores_w.json'), 'utf8'))
const { lado_cubo: lado, n_espacios: nEspacios, umbral_similitud: umbral } = vectores.config
const familia = new FamiliaDiagonalesW(lado, nEspacios)

console.log(`Vectores: ${vectores.puntos.length} puntos, ${vectores.textos.length} textos, ` +
  `${vectores.distancias.length} distancias, ${vectores.cache.length} casos de caché`)
console.log(`Cubo: lado ${lado}, ${nEspacios} espacios por diagonal\n`)

// --- 1. Tokenización -------------------------------------------------------
for (const [texto, esperado] of Object.entries(vectores.tokenizacion)) {
  const obtenido = tokenizar(texto)
  afirmar(
    JSON.stringify(obtenido) === JSON.stringify(esperado),
    `tokenizar(${JSON.stringify(texto)}): ${JSON.stringify(obtenido)} != ${JSON.stringify(esperado)}`,
  )
}

// --- 2. Firmas de puntos 3D ------------------------------------------------
for (const caso of vectores.puntos) {
  casiIgual(familia.componentesDe(caso.punto), caso.componentes, `componentes ${JSON.stringify(caso.punto)}`)
  casiIgual(familia.firmaDePunto(caso.punto), caso.firma, `firma ${JSON.stringify(caso.punto)}`)
  afirmar(
    JSON.stringify(familia.espaciosDe(caso.punto)) === JSON.stringify(caso.espacios),
    `espacios ${JSON.stringify(caso.punto)}`,
  )
}

// --- 3. Firmas de textos ---------------------------------------------------
for (const caso of vectores.textos) {
  const f = familia.firmaDeTexto(caso.texto)
  afirmar(
    JSON.stringify(f.tokens) === JSON.stringify(caso.tokens),
    `tokens de ${JSON.stringify(caso.texto)}`,
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
  const [dist, solape] = familia.distancia(
    familia.firmaDeTexto(caso.a),
    familia.firmaDeTexto(caso.b),
  )
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
  afirmar(
    (dist <= umbral && solape > 0) === caso.acierto,
    `decision ${JSON.stringify(caso.b)}: se esperaba acierto=${caso.acierto}`,
  )
}

// --- 5. Comportamiento de la caché ----------------------------------------
const cache = new CacheSemanticaW(familia, umbral)
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
    afirmar(
      Math.abs(obtenido.distancia - esperado.distancia) <= TOLERANCIA,
      `caché distancia: ${obtenido.distancia} != ${esperado.distancia}`,
    )
  }
}

const stats = cache.estadisticas()
afirmar(
  stats.hitsExactos === vectores.cache_estadisticas.hits_exactos &&
    stats.hitsSemanticos === vectores.cache_estadisticas.hits_semanticos &&
    stats.fallos === vectores.cache_estadisticas.fallos,
  `estadísticas de caché: ${JSON.stringify(stats)}`,
)

console.log(`\nRESULTADO: ${comprobaciones - fallos}/${comprobaciones} comprobaciones OK`)
if (fallos > 0) {
  console.error(`  ${fallos} FALLOS`)
  process.exit(1)
}
console.log('  El port JavaScript coincide con la referencia Python.')
