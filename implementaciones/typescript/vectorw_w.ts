/**
 * Firma W 4D y caché semántica de VectorW — implementación de referencia en TypeScript.
 *
 * Puerto fiel de `implementaciones/python/vectorw_w.py`, que a su vez reproduce
 * exactamente el núcleo VectorW. Las firmas que produce este archivo coinciden
 * número a número con las de Python, y ambas con el núcleo original.
 *
 * VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
 * https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1
 *
 * Sin dependencias: solo `node:crypto` para SHA-256. Node 24+ ejecuta este
 * archivo .ts directamente (type stripping), así que no hace falta compilar:
 *
 *     node --test implementaciones/typescript  # (o) node implementaciones/typescript/prueba.ts
 *
 * @module vectorw_w
 */

import { createHash } from 'node:crypto'

/** Versión de esta implementación. */
export const VERSION = '1.1.0'

/** Constantes del espacio de memoria VectorW. */
export const ConfigW = {
  /** Lado del cubo de memoria (valor por defecto del núcleo). */
  LADO_CUBO: 1024.0,
  /** Espacios por diagonal; resolución total = 4 × N_ESPACIOS. */
  N_ESPACIOS: 8,
  /** Distancia W máxima para aceptar un acierto semántico. */
  UMBRAL_SIMILITUD: 0.15,
  /** Máximo de entradas de la caché. */
  MAX_ENTRADAS: 2000,
  /** Comparar firmas bajo las 24 permutaciones. */
  INVARIANTE_PERMUTACIONES: true,
  /** Peso de la distancia geométrica en la métrica combinada. */
  PESO_GEOMETRIA: 0.35,
  /** Peso del solapamiento de vocabulario en la métrica combinada. */
  PESO_SOLAPAMIENTO: 1.3,
} as const

// ---------------------------------------------------------------------------
// Tokenización
// ---------------------------------------------------------------------------

/**
 * Palabras vacías ES/EN. Idénticas a las de la implementación Python: no
 * aportan posición semántica y desplazarían el centroide.
 */
const PALABRAS_VACIAS = new Set(
  `
a al algo algunas algunos ante antes aqui asi aun aunque bien cada como con contra cual
cuando de del desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso
esos esta estaba estado estas este esto estos fue fueron ha hace hacia han hasta hay la
las le les lo los mas me mi mis mucho muy nada ni no nos nosotros nuestra nuestro o os
otra otro para pero poco por porque que quien se sea segun ser si sin sobre son su sus
tal tambien tanto te tiene tienen todo todos tu tus un una uno unos y ya
the is at which on an and are as be been but by can for from has have how in into it its
of or that their there these this to was were what when where who will with your
`.split(/\s+/).filter(Boolean),
)

/** Sufijos que se recortan, en el mismo orden que en Python. */
const SUFIJOS = [
  'ciones', 'cion', 'mente', 'ados', 'adas', 'ado', 'ada',
  'idos', 'idas', 'ido', 'ida', 'es', 'os', 'as', 's',
]

/**
 * Mapa de diacríticos latinos a su letra base.
 *
 * Python usa `unicodedata.normalize('NFKD')`; aquí se resuelve con una tabla
 * explícita porque es más rápido, no depende de la configuración regional y
 * cubre exactamente el mismo repertorio (Latin-1 + ñ/ü).
 */
const SIN_ACENTO: Record<string, string> = {
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
 * @param texto - texto a normalizar.
 * @returns el texto sin acentos y en minúsculas.
 */
export function sinAcentos(texto: string): string {
  let salida = ''
  for (const caracter of texto.toLowerCase()) {
    salida += SIN_ACENTO[caracter] ?? caracter
  }
  return salida
}

/**
 * Raíz aproximada de un token, tolerante a plurales, género y conjugaciones.
 *
 * El orden y las longitudes de `SUFIJOS` deben ser idénticos a los de Python:
 * de la raíz depende que las firmas coincidan entre implementaciones.
 *
 * @param token - token ya normalizado (sin acentos, en minúsculas).
 * @returns la raíz del token.
 */
export function raiz(token: string): string {
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
 * Minúsculas, sin acentos, descarta palabras vacías y palabras de menos de 3
 * letras, reduce a raíz y elimina duplicados conservando el orden de aparición.
 *
 * @param texto - consulta o tarea a tokenizar.
 * @returns lista de raíces sin duplicados.
 */
export function tokenizar(texto: string): string[] {
  if (!texto) return []
  // Equivalente a [\w...]+ de Python: letras Unicode, dígitos y guion bajo.
  const crudos = texto.match(/[\p{L}\p{N}_]+/gu) ?? []
  const vistos = new Set<string>()
  const salida: string[] = []
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

/** Punto 3D dentro del cubo de memoria. */
export type Punto = readonly [number, number, number]

/** Firma W 4D normalizada. */
export type Firma = readonly [number, number, number, number]

/** Firma W 4D de un texto, con su procedencia. */
export interface FirmaW {
  /** Tokens significativos usados (raíces). */
  readonly tokens: string[]
  /** Centroide 3D de los tokens dentro del cubo. */
  readonly coords: Punto
  /** Las 4 proyecciones sin normalizar. */
  readonly componentes: Firma
  /** Las 4 proyecciones normalizadas por la longitud de la diagonal. */
  readonly firma: Firma
  /** Índice de espacio W (0..n-1) en cada diagonal. */
  readonly espacios: readonly number[]
  /** True si el texto no aportó ningún token. */
  readonly esVacia: boolean
}

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
 * La firma normalizada es `t_k / (L·√3) = (b_k + s_k · p') / 3`. Por eso los
 * componentes 2..4 arrancan en ≈0.9107 y no en 0: el núcleo sitúa el inicio de
 * esas tres rectas fuera del cubo. Es una propiedad del núcleo, no un error;
 * la firma sirve para clasificar y comparar, no como medida absoluta.
 */
export class FamiliaDiagonalesW {
  /** Lado del cubo de memoria. */
  readonly lado: number
  /** Espacios por diagonal. */
  readonly nEspacios: number
  /** Longitud de la diagonal: lado·√3. */
  readonly longitud: number
  /** Divisor de normalización de la firma. */
  readonly normalizador: number

  /** Coeficientes (±1) por diagonal, en el orden W1, W2, W3, W4. */
  static readonly SIGNOS: readonly (readonly number[])[] = [
    [1, 1, 1],
    [-1, 1, 1],
    [1, -1, 1],
    [1, 1, -1],
  ]

  private static readonly RAIZ3 = Math.sqrt(3)
  private readonly bases: readonly number[]

  /**
   * @param ladoCubo - lado del cubo (el núcleo usa 1024).
   * @param nEspacios - espacios por diagonal (el núcleo usa 8).
   */
  constructor(ladoCubo: number = ConfigW.LADO_CUBO, nEspacios: number = ConfigW.N_ESPACIOS) {
    this.lado = ladoCubo
    this.nEspacios = Math.max(1, Math.trunc(nEspacios))
    this.longitud = this.lado * FamiliaDiagonalesW.RAIZ3
    this.normalizador = this.longitud
    const r3 = FamiliaDiagonalesW.RAIZ3
    // b_k: 0 en W1 (recta anclada en el vértice) y 1+√3 en las otras tres
    // (su inicio queda fuera del cubo; con lado 1024, en 2797.62).
    this.bases = [0, 1 + r3, 1 + r3, 1 + r3]
  }

  /**
   * Proyección escalar del punto sobre la diagonal indicada.
   *
   * @param indice - 0..3, en el orden W1, W2, W3, W4.
   * @param punto - terna de coordenadas dentro del cubo.
   * @returns la proyección sin normalizar.
   */
  parametroT(indice: number, punto: Punto): number {
    const signos = FamiliaDiagonalesW.SIGNOS[indice]
    const proyeccion = signos[0] * punto[0] + signos[1] * punto[1] + signos[2] * punto[2]
    return (this.bases[indice] * this.lado + proyeccion) / FamiliaDiagonalesW.RAIZ3
  }

  /**
   * Las 4 proyecciones sin normalizar de un punto.
   *
   * @param punto - terna de coordenadas.
   * @returns las 4 proyecciones en orden W1..W4.
   */
  componentesDe(punto: Punto): Firma {
    return [
      this.parametroT(0, punto),
      this.parametroT(1, punto),
      this.parametroT(2, punto),
      this.parametroT(3, punto),
    ]
  }

  /**
   * Firma W 4D normalizada de un punto 3D.
   *
   * Equivale a `FamiliaDiagonales.calcular_firma_normalizada` del núcleo.
   *
   * @param punto - terna de coordenadas.
   * @returns la firma normalizada.
   */
  firmaDePunto(punto: Punto): Firma {
    const c = this.componentesDe(punto)
    const n = this.normalizador
    return [c[0] / n, c[1] / n, c[2] / n, c[3] / n]
  }

  /**
   * Índice de espacio W (0..n-1) de cada diagonal para un punto.
   *
   * El núcleo acota la proyección a `[0, longitud]` antes de repartirla en
   * espacios; se replica el truncado hacia cero de Python.
   *
   * @param punto - terna de coordenadas.
   * @returns un índice por diagonal.
   */
  espaciosDe(punto: Punto): number[] {
    const n = this.nEspacios
    const salida: number[] = []
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
   * Es la proyección de un hash criptográfico, no una posición semántica real:
   * lo que importa es que sea determinista, uniforme y estable, para que dos
   * textos con los mismos tokens den el mismo centroide.
   *
   * @param token - token ya normalizado.
   * @returns terna (x, y, z) en [0, lado).
   */
  puntoW(token: string): Punto {
    const resumen = createHash('sha256').update(token, 'utf8').digest('hex')
    return [
      Number(BigInt('0x' + resumen.slice(0, 8)) % BigInt(this.lado)),
      Number(BigInt('0x' + resumen.slice(8, 16)) % BigInt(this.lado)),
      Number(BigInt('0x' + resumen.slice(16, 24)) % BigInt(this.lado)),
    ]
  }

  /**
   * Punto medio de los puntos W de los tokens.
   *
   * Si no hay tokens se usa el punto del texto completo, para que una consulta
   * vacía siga teniendo una firma válida.
   *
   * @param tokens - tokens significativos.
   * @param texto - texto original, como respaldo.
   * @returns el centroide dentro del cubo.
   */
  centroide(tokens: readonly string[], texto = ''): Punto {
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
   * @param texto - consulta o tarea a indexar.
   * @returns la firma con tokens, centroide, componentes y espacios.
   */
  firmaDeTexto(texto: string): FirmaW {
    const tokens = tokenizar(texto)
    const coords = this.centroide(tokens, texto || '')
    const componentes = this.componentesDe(coords)
    const n = this.normalizador
    return {
      tokens,
      coords,
      componentes,
      firma: [componentes[0] / n, componentes[1] / n, componentes[2] / n, componentes[3] / n],
      espacios: this.espaciosDe(coords),
      esVacia: tokens.length === 0,
    }
  }

  // -- distancias -----------------------------------------------------------

  /**
   * Distancia euclídea directa entre dos firmas W 4D.
   *
   * @param f1 - primera firma.
   * @param f2 - segunda firma.
   */
  distanciaGeometrica(f1: Firma, f2: Firma): number {
    return Math.hypot(f1[0] - f2[0], f1[1] - f2[1], f1[2] - f2[2], f1[3] - f2[3])
  }

  /**
   * Distancia mínima sobre las 24 permutaciones de la segunda firma.
   *
   * Hace la comparación invariante al orden de las diagonales. Cuesta 24
   * distancias en lugar de 1.
   *
   * @param f1 - primera firma.
   * @param f2 - segunda firma.
   */
  distanciaPermutaciones(f1: Firma, f2: Firma): number {
    let mejor = Infinity
    for (let a = 0; a < 4; a++) {
      for (let b = 0; b < 4; b++) {
        if (b === a) continue
        for (let c = 0; c < 4; c++) {
          if (c === a || c === b) continue
          const d = 6 - a - b - c
          const dist = Math.hypot(
            f1[0] - f2[a], f1[1] - f2[b], f1[2] - f2[c], f1[3] - f2[d],
          )
          if (dist < mejor) mejor = dist
        }
      }
    }
    return mejor
  }

  /**
   * Distancia combinada W 4D + solapamiento de vocabulario.
   *
   * La geometría sola produce falsos aciertos: dos consultas sin ninguna
   * palabra en común pueden caer cerca por azar. El solapamiento (Jaccard sobre
   * las raíces) actúa de penalización.
   *
   * @param f1 - primera firma.
   * @param f2 - segunda firma.
   * @param invariantePermutaciones - comparar bajo las 24 permutaciones.
   * @returns `[distancia, solapamiento]`.
   */
  distancia(
    f1: FirmaW,
    f2: FirmaW,
    invariantePermutaciones: boolean = ConfigW.INVARIANTE_PERMUTACIONES,
  ): [number, number] {
    const geometrica = invariantePermutaciones
      ? this.distanciaPermutaciones(f1.firma, f2.firma)
      : this.distanciaGeometrica(f1.firma, f2.firma)

    const conjunto1 = new Set(f1.tokens)
    const conjunto2 = new Set(f2.tokens)
    if (conjunto1.size === 0 || conjunto2.size === 0) return [geometrica, 0]

    let interseccion = 0
    for (const token of conjunto1) if (conjunto2.has(token)) interseccion++
    const union = conjunto1.size + conjunto2.size - interseccion
    const solapamiento = union > 0 ? interseccion / union : 0
    const penalizacion =
      ConfigW.PESO_GEOMETRIA + ConfigW.PESO_SOLAPAMIENTO * (1 - solapamiento)
    return [geometrica * penalizacion, solapamiento]
  }
}

// ---------------------------------------------------------------------------
// Caché semántica
// ---------------------------------------------------------------------------

/** Resultado de una consulta a la caché. */
export interface ResultadoCache {
  hit: boolean
  kind: 'exacto' | 'semantico' | 'miss'
  query: string
  value?: unknown
  tokensAhorrados?: number
  distancia?: number
  solapamiento?: number
  umbral: number
  candidatos?: number
  mejorDistancia?: number | null
  mejorSolapamiento?: number
}

/** Métricas de acierto y ahorro de la caché. */
export interface EstadisticasCache {
  entradas: number
  maxEntradas: number
  umbralSimilitud: number
  hitsExactos: number
  hitsSemanticos: number
  fallos: number
  hitRate: number
  tokensAhorrados: number
  tokensAlmacenados: number
}

/** Entrada almacenada en la caché. */
interface EntradaCache {
  query: string
  queryNorm: string
  valor: unknown
  tokens: number
  firma: FirmaW
  metadata: Record<string, unknown>
  timestamp: number
}

/**
 * Caché de pares consulta→valor con recuperación por similitud W 4D.
 *
 * Sustituye la coincidencia literal de cadenas por coincidencia semántica: una
 * consulta reformulada recupera la respuesta ya calculada, que es el ahorro
 * real de tokens.
 */
export class CacheSemanticaW {
  readonly familia: FamiliaDiagonalesW
  readonly umbral: number
  readonly maxEntradas: number
  private readonly entradas = new Map<string, EntradaCache>()
  hitsExactos = 0
  hitsSemanticos = 0
  fallos = 0
  tokensAhorrados = 0
  tokensAlmacenados = 0

  /**
   * @param familia - familia de diagonales (se crea una por defecto).
   * @param umbralSimilitud - distancia W máxima para aceptar un acierto.
   * @param maxEntradas - tamaño máximo; se expulsa la entrada más antigua.
   */
  constructor(
    familia: FamiliaDiagonalesW = new FamiliaDiagonalesW(),
    umbralSimilitud: number = ConfigW.UMBRAL_SIMILITUD,
    maxEntradas: number = ConfigW.MAX_ENTRADAS,
  ) {
    this.familia = familia
    this.umbral = umbralSimilitud
    this.maxEntradas = maxEntradas
  }

  /** Normaliza para la coincidencia exacta: minúsculas y espacios simples. */
  private static normalizar(texto: string): string {
    return (texto ?? '').toLowerCase().split(/\s+/).filter(Boolean).join(' ')
  }

  /**
   * Busca una consulta equivalente en la caché.
   *
   * @param consulta - la consulta a resolver.
   * @returns el acierto con su valor, o un `miss` con el diagnóstico.
   */
  buscar(consulta: string): ResultadoCache {
    const norm = CacheSemanticaW.normalizar(consulta)
    const firma = this.familia.firmaDeTexto(norm)

    // 1) coincidencia exacta normalizada
    for (const entrada of this.entradas.values()) {
      if (entrada.queryNorm === norm) {
        this.hitsExactos++
        this.tokensAhorrados += entrada.tokens
        return this.vista(entrada, 'exacto', 0, 1)
      }
    }

    // 2) coincidencia semántica
    //
    // Solo se consideran candidatas las entradas que comparten al menos un
    // token. Filtrar ANTES de elegir la más cercana es imprescindible: si se
    // elige primero la de menor distancia y luego se exige solapamiento, una
    // entrada sin nada en común (cercana por azar) puede adelantarse a la que
    // sí coincide y convertir un acierto válido en un fallo.
    let mejorDist = Infinity
    let mejorSolape = 0
    let mejor: EntradaCache | null = null
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
   * @param consulta - consulta que produjo el resultado.
   * @param valor - resultado a cachear.
   * @param tokens - coste estimado en tokens (para medir el ahorro).
   * @param metadata - metadatos libres.
   */
  guardar(
    consulta: string,
    valor: unknown,
    tokens = 0,
    metadata: Record<string, unknown> = {},
  ): void {
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
  private vista(
    entrada: EntradaCache,
    tipo: 'exacto' | 'semantico',
    distancia: number,
    solapamiento: number,
  ): ResultadoCache {
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
  estadisticas(): EstadisticasCache {
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
  limpiar(): number {
    const cantidad = this.entradas.size
    this.entradas.clear()
    return cantidad
  }
}
