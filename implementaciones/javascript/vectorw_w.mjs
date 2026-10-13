/**
 * Firma W 4D y caché semántica de VectorW — implementación JavaScript sin dependencias.
 *
 * Puerto fiel de `implementaciones/python/vectorw_w.py` y del port TypeScript.
 * Produce exactamente las mismas firmas que ambos, y por tanto que el núcleo
 * VectorW original.
 *
 * VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
 * https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1
 *
 * SHA-256 está implementado aquí mismo, así que este archivo funciona igual en
 * Node, en el navegador y en cualquier motor ECMAScript moderno, sin `import`
 * ni `require`:
 *
 *     node implementaciones/javascript/prueba.mjs
 *
 * @module vectorw_w
 */

/** Versión de esta implementación. */
export const VERSION = '1.1.0'

/** Constantes del espacio de memoria VectorW. */
export const ConfigW = Object.freeze({
  LADO_CUBO: 1024.0,
  N_ESPACIOS: 8,
  UMBRAL_SIMILITUD: 0.15,
  MAX_ENTRADAS: 2000,
  INVARIANTE_PERMUTACIONES: true,
  PESO_GEOMETRIA: 0.35,
  PESO_SOLAPAMIENTO: 1.3,
})

// ---------------------------------------------------------------------------
// SHA-256 sin dependencias
// ---------------------------------------------------------------------------

/** Constantes de ronda de SHA-256 (primeros 32 bits de las raíces cúbicas de los primos). */
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

/** Rota a la derecha 32 bits. */
const rotr = (x, n) => ((x >>> n) | (x << (32 - n))) >>> 0

/**
 * Calcula SHA-256 de una cadena UTF-8.
 *
 * @param texto - cadena a resumir.
 * @returns el resumen en hexadecimal minúsculas, 64 caracteres.
 */
export function sha256Hex(texto) {
  const bytes = new TextEncoder().encode(texto)
  const longitudBits = bytes.length * 8

  // Relleno: 0x80, ceros, y la longitud en 64 bits big-endian.
  const conRelleno = new Uint8Array((((bytes.length + 9) >> 6) + 1) << 6)
  conRelleno.set(bytes)
  conRelleno[bytes.length] = 0x80
  const vista = new DataView(conRelleno.buffer)
  vista.setUint32(conRelleno.length - 8, Math.floor(longitudBits / 0x100000000))
  vista.setUint32(conRelleno.length - 4, longitudBits >>> 0)

  const h = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ])
  const w = new Uint32Array(64)

  for (let offset = 0; offset < conRelleno.length; offset += 64) {
    for (let i = 0; i < 16; i++) w[i] = vista.getUint32(offset + i * 4)
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3)
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }

    let [a, b, c, d, e, f, g, hh] = h
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const temp1 = (hh + S1 + ch + K[i] + w[i]) >>> 0
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const temp2 = (S0 + maj) >>> 0
      hh = g
      g = f
      f = e
      e = (d + temp1) >>> 0
      d = c
      c = b
      b = a
      a = (temp1 + temp2) >>> 0
    }
    h[0] = (h[0] + a) >>> 0
    h[1] = (h[1] + b) >>> 0
    h[2] = (h[2] + c) >>> 0
    h[3] = (h[3] + d) >>> 0
    h[4] = (h[4] + e) >>> 0
    h[5] = (h[5] + f) >>> 0
    h[6] = (h[6] + g) >>> 0
    h[7] = (h[7] + hh) >>> 0
  }

  let salida = ''
  for (let i = 0; i < 8; i++) salida += h[i].toString(16).padStart(8, '0')
  return salida
}

// ---------------------------------------------------------------------------
// Tokenización
// ---------------------------------------------------------------------------

/** Palabras vacías ES/EN: no aportan posición semántica. */
const PALABRAS_VACIAS = new Set(
  `a al algo algunas algunos ante antes aqui asi aun aunque bien cada como con contra cual
cuando de del desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso
esos esta estaba estado estas este esto estos fue fueron ha hace hacia han hasta hay la
las le les lo los mas me mi mis mucho muy nada ni no nos nosotros nuestra nuestro o os
otra otro para pero poco por porque que quien se sea segun ser si sin sobre son su sus
tal tambien tanto te tiene tienen todo todos tu tus un una uno unos y ya
the is at which on an and are as be been but by can for from has have how in into it its
of or that their there these this to was were what when where who will with your`
    .split(/\s+/)
    .filter(Boolean),
)

/** Sufijos que se recortan, en el mismo orden que en Python. */
const SUFIJOS = [
  'ciones', 'cion', 'mente', 'ados', 'adas', 'ado', 'ada',
  'idos', 'idas', 'ido', 'ida', 'es', 'os', 'as', 's',
]

/** Mapa de diacríticos latinos a su letra base. */
const SIN_ACENTO = {
  á: 'a', à: 'a', ä: 'a', â: 'a', ã: 'a', å: 'a',
  é: 'e', è: 'e', ë: 'e', ê: 'e',
  í: 'i', ì: 'i', ï: 'i', î: 'i',
  ó: 'o', ò: 'o', ö: 'o', ô: 'o', õ: 'o',
  ú: 'u', ù: 'u', ü: 'u', û: 'u',
  ñ: 'n', ç: 'c', ý: 'y',
}

/**
 * Quita diacríticos conservando la letra base y pasa a minúsculas.
 *
 * @param {string} texto - texto a normalizar.
 * @returns {string} el texto sin acentos y en minúsculas.
 */
export function sinAcentos(texto) {
  let salida = ''
  for (const caracter of texto.toLowerCase()) {
    salida += SIN_ACENTO[caracter] ?? caracter
  }
  return salida
}

/**
 * Raíz aproximada de un token, tolerante a plurales, género y conjugaciones.
 *
 * @param {string} token - token ya normalizado.
 * @returns {string} la raíz del token.
 */
export function raiz(token) {
  for (const sufijo of SUFIJOS) {
    if (token.length > sufijo.length + 3 && token.endsWith(sufijo)) {
      return token.slice(0, token.length - sufijo.length)
    }
  }
  return token
}

/**
 * Extrae los tokens significativos de un texto.
 *
 * @param {string} texto - consulta o tarea a tokenizar.
 * @returns {string[]} lista de raíces sin duplicados.
 */
export function tokenizar(texto) {
  if (!texto) return []
  const crudos = texto.match(/[\p{L}\p{N}_]+/gu) ?? []
  const vistos = new Set()
  const salida = []
  for (const crudo of crudos) {
    const normalizado = sinAcentos(crudo)
    if (normalizado.length < 3 || PALABRAS_VACIAS.has(normalizado)) continue
    const reducido = raiz(normalizado)
    if (vistos.has(reducido)) continue
    vistos.add(reducido)
    salida.push(reducido)
  }
  return salida
}

// ---------------------------------------------------------------------------
// Firma W 4D
// ---------------------------------------------------------------------------

/**
 * Las 4 diagonales del cubo de memoria y la aritmética de firmas W 4D.
 *
 * Reproduce la geometría del núcleo original. La proyección de un punto sobre
 * cada diagonal es la forma afín:
 *
 *     t_k(p) = ( b_k · L + s_k · p ) / √3
 *
 *     k   diagonal   b_k              s_k
 *     1   W1 (+++)   0                (+1, +1, +1)
 *     2   W2 (-++)   1+√3 ≈ 2.7321    (-1, +1, +1)
 *     3   W3 (+-+)   1+√3 ≈ 2.7321    (+1, -1, +1)
 *     4   W4 (++-)   1+√3 ≈ 2.7321    (+1, +1, -1)
 *
 * La firma normalizada es `t_k / (L·√3) = (b_k + s_k · p') / 3`, así que los
 * componentes 2..4 arrancan en ≈0.9107 y no en 0. Es una propiedad del núcleo.
 */
export class FamiliaDiagonalesW {
  /** Coeficientes (±1) por diagonal, en el orden W1..W4. */
  static SIGNOS = [
    [1, 1, 1],
    [-1, 1, 1],
    [1, -1, 1],
    [1, 1, -1],
  ]

  /**
   * @param {number} [ladoCubo] - lado del cubo (el núcleo usa 1024).
   * @param {number} [nEspacios] - espacios por diagonal (el núcleo usa 8).
   */
  constructor(ladoCubo = ConfigW.LADO_CUBO, nEspacios = ConfigW.N_ESPACIOS) {
    this.lado = ladoCubo
    this.nEspacios = Math.max(1, Math.trunc(nEspacios))
    this.raiz3 = Math.sqrt(3)
    this.longitud = this.lado * this.raiz3
    this.normalizador = this.longitud
    // b_k: 0 en W1 (recta anclada en el vértice) y 1+√3 en las otras tres.
    this.bases = [0, 1 + this.raiz3, 1 + this.raiz3, 1 + this.raiz3]
  }

  /**
   * Proyección escalar del punto sobre la diagonal indicada.
   *
   * @param {number} indice - 0..3, en el orden W1..W4.
   * @param {number[]} punto - terna de coordenadas.
   * @returns {number} la proyección sin normalizar.
   */
  parametroT(indice, punto) {
    const s = FamiliaDiagonalesW.SIGNOS[indice]
    return (this.bases[indice] * this.lado + s[0] * punto[0] + s[1] * punto[1] + s[2] * punto[2]) / this.raiz3
  }

  /**
   * Las 4 proyecciones sin normalizar de un punto.
   *
   * @param {number[]} punto - terna de coordenadas.
   * @returns {number[]} las 4 proyecciones.
   */
  componentesDe(punto) {
    return [0, 1, 2, 3].map((k) => this.parametroT(k, punto))
  }

  /**
   * Firma W 4D normalizada de un punto 3D.
   *
   * @param {number[]} punto - terna de coordenadas.
   * @returns {number[]} la firma normalizada.
   */
  firmaDePunto(punto) {
    return this.componentesDe(punto).map((v) => v / this.normalizador)
  }

  /**
   * Índice de espacio W (0..n-1) de cada diagonal para un punto.
   *
   * @param {number[]} punto - terna de coordenadas.
   * @returns {number[]} un índice por diagonal.
   */
  espaciosDe(punto) {
    const n = this.nEspacios
    const salida = []
    for (let k = 0; k < 4; k++) {
      const t = this.parametroT(k, punto)
      const acotado = Math.max(0, Math.min(t, this.longitud))
      salida.push(Math.min(Math.trunc((acotado / this.longitud) * n), n - 1))
    }
    return salida
  }

  /**
   * Punto 3D determinista de un token dentro del cubo.
   *
   * @param {string} token - token ya normalizado.
   * @returns {number[]} terna (x, y, z) en [0, lado).
   */
  puntoW(token) {
    const resumen = sha256Hex(token)
    return [0, 8, 16].map((i) => Number(BigInt('0x' + resumen.slice(i, i + 8)) % BigInt(this.lado)))
  }

  /**
   * Punto medio de los puntos W de los tokens.
   *
   * @param {string[]} tokens - tokens significativos.
   * @param {string} [texto] - texto original, como respaldo.
   * @returns {number[]} el centroide dentro del cubo.
   */
  centroide(tokens, texto = '') {
    if (tokens.length === 0) return this.puntoW(texto)
    let x = 0
    let y = 0
    let z = 0
    for (const token of tokens) {
      const [px, py, pz] = this.puntoW(token)
      x += px
      y += py
      z += pz
    }
    return [x / tokens.length, y / tokens.length, z / tokens.length]
  }

  /**
   * Firma W 4D completa de un texto.
   *
   * @param {string} texto - consulta o tarea a indexar.
   * @returns {{tokens: string[], coords: number[], componentes: number[], firma: number[], espacios: number[]}}
   */
  firmaDeTexto(texto) {
    const tokens = tokenizar(texto)
    const coords = this.centroide(tokens, texto || '')
    const componentes = this.componentesDe(coords)
    return {
      tokens,
      coords,
      componentes,
      firma: componentes.map((v) => v / this.normalizador),
      espacios: this.espaciosDe(coords),
    }
  }

  /**
   * Distancia euclídea directa entre dos firmas W 4D.
   *
   * @param {number[]} f1 - primera firma.
   * @param {number[]} f2 - segunda firma.
   * @returns {number} la distancia.
   */
  distanciaGeometrica(f1, f2) {
    return Math.hypot(f1[0] - f2[0], f1[1] - f2[1], f1[2] - f2[2], f1[3] - f2[3])
  }

  /**
   * Distancia mínima sobre las 24 permutaciones de la segunda firma.
   *
   * @param {number[]} f1 - primera firma.
   * @param {number[]} f2 - segunda firma.
   * @returns {number} la distancia mínima.
   */
  distanciaPermutaciones(f1, f2) {
    let mejor = Infinity
    for (let a = 0; a < 4; a++) {
      for (let b = 0; b < 4; b++) {
        if (b === a) continue
        for (let c = 0; c < 4; c++) {
          if (c === a || c === b) continue
          const d = 6 - a - b - c
          const dist = Math.hypot(f1[0] - f2[a], f1[1] - f2[b], f1[2] - f2[c], f1[3] - f2[d])
          if (dist < mejor) mejor = dist
        }
      }
    }
    return mejor
  }

  /**
   * Distancia combinada W 4D + solapamiento de vocabulario.
   *
   * @param {object} f1 - primera firma.
   * @param {object} f2 - segunda firma.
   * @param {boolean} [invariantePermutaciones] - comparar bajo las 24 permutaciones.
   * @returns {[number, number]} `[distancia, solapamiento]`.
   */
  distancia(f1, f2, invariantePermutaciones = ConfigW.INVARIANTE_PERMUTACIONES) {
    const geometrica = invariantePermutaciones
      ? this.distanciaPermutaciones(f1.firma, f2.firma)
      : this.distanciaGeometrica(f1.firma, f2.firma)

    const c1 = new Set(f1.tokens)
    const c2 = new Set(f2.tokens)
    if (c1.size === 0 || c2.size === 0) return [geometrica, 0]

    let interseccion = 0
    for (const token of c1) if (c2.has(token)) interseccion++
    const union = c1.size + c2.size - interseccion
    const solapamiento = union > 0 ? interseccion / union : 0
    const penalizacion = ConfigW.PESO_GEOMETRIA + ConfigW.PESO_SOLAPAMIENTO * (1 - solapamiento)
    return [geometrica * penalizacion, solapamiento]
  }
}

// ---------------------------------------------------------------------------
// Caché semántica
// ---------------------------------------------------------------------------

/**
 * Caché de pares consulta→valor con recuperación por similitud W 4D.
 */
export class CacheSemanticaW {
  /**
   * @param {FamiliaDiagonalesW} [familia] - familia de diagonales.
   * @param {number} [umbralSimilitud] - distancia W máxima para aceptar.
   * @param {number} [maxEntradas] - tamaño máximo de la caché.
   */
  constructor(
    familia = new FamiliaDiagonalesW(),
    umbralSimilitud = ConfigW.UMBRAL_SIMILITUD,
    maxEntradas = ConfigW.MAX_ENTRADAS,
  ) {
    this.familia = familia
    this.umbral = umbralSimilitud
    this.maxEntradas = maxEntradas
    this.entradas = new Map()
    this.hitsExactos = 0
    this.hitsSemanticos = 0
    this.fallos = 0
    this.tokensAhorrados = 0
    this.tokensAlmacenados = 0
  }

  /** Normaliza para la coincidencia exacta. */
  static normalizar(texto) {
    return (texto ?? '').toLowerCase().split(/\s+/).filter(Boolean).join(' ')
  }

  /**
   * Busca una consulta equivalente en la caché.
   *
   * @param {string} consulta - la consulta a resolver.
   * @returns {object} el acierto con su valor, o un `miss` con diagnóstico.
   */
  buscar(consulta) {
    const norm = CacheSemanticaW.normalizar(consulta)
    const firma = this.familia.firmaDeTexto(norm)

    for (const entrada of this.entradas.values()) {
      if (entrada.queryNorm === norm) {
        this.hitsExactos++
        this.tokensAhorrados += entrada.tokens
        return this.vista(entrada, 'exacto', 0, 1)
      }
    }

    // Solo compiten las entradas con al menos un token en común. El filtro va
    // ANTES de elegir la más cercana: si se elige primero por distancia y luego
    // se exige solapamiento, una entrada sin nada en común (cercana por azar)
    // puede adelantarse a la que sí coincide y convertir un acierto válido en
    // un fallo.
    let mejorDist = Infinity
    let mejorSolape = 0
    let mejor = null
    for (const entrada of this.entradas.values()) {
      const [dist, solape] = this.familia.distancia(firma, entrada.firma)
      if (solape <= 0) continue
      if (dist < mejorDist) {
        mejorDist = dist
        mejorSolape = solape
        mejor = entrada
      }
    }

    if (mejor && mejorDist <= this.umbral) {
      this.hitsSemanticos++
      this.tokensAhorrados += mejor.tokens
      return this.vista(mejor, 'semantico', mejorDist, mejorSolape)
    }

    this.fallos++
    return {
      hit: false,
      kind: 'miss',
      query: consulta,
      umbral: this.umbral,
      candidatos: this.entradas.size,
      mejorDistancia: mejor ? mejorDist : null,
      mejorSolapamiento: mejorSolape,
    }
  }

  /**
   * Guarda un resultado asociado a una consulta.
   *
   * @param {string} consulta - consulta que produjo el resultado.
   * @param {*} valor - resultado a cachear.
   * @param {number} [tokens] - coste estimado en tokens.
   * @param {object} [metadata] - metadatos libres.
   */
  guardar(consulta, valor, tokens = 0, metadata = {}) {
    const norm = CacheSemanticaW.normalizar(consulta)
    const firma = this.familia.firmaDeTexto(norm)
    const clave = firma.firma.map((v) => v.toFixed(12)).join('|')
    const coste = Math.max(0, Math.trunc(tokens))

    while (this.entradas.size >= this.maxEntradas) {
      const masAntigua = this.entradas.keys().next()
      if (masAntigua.done) break
      this.entradas.delete(masAntigua.value)
    }

    this.entradas.set(clave, {
      query: consulta,
      queryNorm: norm,
      valor,
      tokens: coste,
      firma,
      metadata,
      timestamp: Date.now(),
    })
    this.tokensAlmacenados += coste
  }

  /** Construye la vista de un acierto. */
  vista(entrada, tipo, distancia, solapamiento) {
    return {
      hit: true,
      kind: tipo,
      query: entrada.query,
      value: entrada.valor,
      tokensAhorrados: entrada.tokens,
      distancia,
      solapamiento,
      umbral: this.umbral,
      candidatos: this.entradas.size,
    }
  }

  /** Métricas de acierto y ahorro acumulado. */
  estadisticas() {
    const total = this.hitsExactos + this.hitsSemanticos + this.fallos
    return {
      entradas: this.entradas.size,
      maxEntradas: this.maxEntradas,
      umbralSimilitud: this.umbral,
      hitsExactos: this.hitsExactos,
      hitsSemanticos: this.hitsSemanticos,
      fallos: this.fallos,
      hitRate: total ? (this.hitsExactos + this.hitsSemanticos) / total : 0,
      tokensAhorrados: this.tokensAhorrados,
      tokensAlmacenados: this.tokensAlmacenados,
    }
  }

  /** Vacía la caché y devuelve cuántas entradas había. */
  limpiar() {
    const cantidad = this.entradas.size
    this.entradas.clear()
    return cantidad
  }
}
