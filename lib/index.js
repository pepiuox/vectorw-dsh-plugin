/**
 * @deepseek-ai/dsh-plugin-vectorw — host half.
 *
 * Expone el núcleo vectorial VectorW (vOS v6.0) como herramientas del agente,
 * para que el modelo no vuelva a pedir lo que ya se buscó: el espacio W 4D
 * funciona como caché semántica y el predictor Markov precalcula lo siguiente.
 *
 * El núcleo VectorW es obra de Jose Ricardo Mantilla Mantilla (PePiuoX)
 * (https://github.com/PePiuoX), licencia LAMC v1.0 / LULA v1.1. Este plugin
 * solo lo orquesta: no reimplementa ni copia su código, lo ejecuta desde la
 * carpeta `vectorW_py` indicada en la configuración.
 *
 * @module @deepseek-ai/dsh-plugin-vectorw
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { EventEmitter } from 'node:events'

import z from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'

/** Cordis plugin name. */
export const name = 'plugin-vectorw'

/** The plugin only needs the tool registry; everything else is optional. */
export const inject = ['tools']

const AQUI = dirname(fileURLToPath(import.meta.url))
const RAIZ_PAQUETE = resolve(AQUI, '..')
const RUTA_BRIDGE = join(RAIZ_PAQUETE, 'bridge_vos.py')

/**
 * Configuración del plugin. Esquema Schemastery: cada campo se valida antes de
 * arrancar el puente Python.
 */
export const Config = z.object({
  /** Carpeta que contiene `vectorW_6.py` (el vectorW_py del usuario). */
  rutaCore: z.string().default(''),
  /** Intérprete de Python. Vacío = el `python` del runtime de DSH o del PATH. */
  rutaPython: z.string().default(''),
  /** Umbral de distancia de firma W 4D para aceptar un acierto semántico. */
  umbralSimilitud: z.number().default(0.15),
  /** Lado del cubo de memoria vOS (1024 por defecto en el núcleo v6). */
  ladoCubo: z.number().default(1024),
  /** Espacios por diagonal (resolución total = 4 × nEspacios). */
  nEspacios: z.number().default(8),
  /** Orden de la cadena de Markov del predictor (1-4). */
  ordenMarkov: z.number().default(2),
  /** Máximo de entradas de la caché semántica. */
  maxEntradas: z.number().default(2000),
  /** TTL en segundos de cada entrada (0 = sin caducidad). */
  ttlSegundos: z.number().default(0),
  /** Comparar firmas bajo las 24 permutaciones (invariante a permutaciones). */
  invariantePermutaciones: z.boolean().default(true),
  /** Timeout en ms por llamada al puente Python. */
  timeoutMs: z.number().default(30000),
  /** Estado persistente a restaurar al arrancar (vacío = ninguno). */
  estadoInicial: z.string().default(''),
})

/**
 * Valores por defecto de la configuración.
 *
 * `apply` los aplica siempre, sin fiarse de que el loader haya inyectado las
 * anotaciones de {@link Config}: una entrada de `cordis.patch.yml` puede
 * declarar solo un subconjunto de campos, y `defineTool` con un timeout `NaN`
 * o un umbral `undefined` fallaría de forma confusa.
 */
const DEFAULTS = Object.freeze({
  rutaCore: '',
  rutaPython: '',
  umbralSimilitud: 0.15,
  ladoCubo: 1024,
  nEspacios: 8,
  ordenMarkov: 2,
  maxEntradas: 2000,
  ttlSegundos: 0,
  invariantePermutaciones: true,
  timeoutMs: 30000,
  estadoInicial: '',
})

/**
 * Completa una configuración parcial con {@link DEFAULTS}, ignorando claves
 * desconocidas y coercitivamente aceptando los tipos declarados.
 *
 * @param entrada - la configuración tal cual llegó del loader (posiblemente parcial).
 * @returns la configuración completa y tipada.
 */
function normalizarConfig(entrada) {
  const origen = entrada && typeof entrada === 'object' ? entrada : {}
  const numero = (valor, respaldo) => {
    const n = Number(valor)
    return Number.isFinite(n) ? n : respaldo
  }
  return {
    rutaCore: String(origen.rutaCore ?? DEFAULTS.rutaCore),
    rutaPython: String(origen.rutaPython ?? DEFAULTS.rutaPython),
    umbralSimilitud: numero(origen.umbralSimilitud, DEFAULTS.umbralSimilitud),
    ladoCubo: numero(origen.ladoCubo, DEFAULTS.ladoCubo),
    nEspacios: numero(origen.nEspacios, DEFAULTS.nEspacios),
    ordenMarkov: numero(origen.ordenMarkov, DEFAULTS.ordenMarkov),
    maxEntradas: numero(origen.maxEntradas, DEFAULTS.maxEntradas),
    ttlSegundos: numero(origen.ttlSegundos, DEFAULTS.ttlSegundos),
    invariantePermutaciones:
      origen.invariantePermutaciones === undefined
        ? DEFAULTS.invariantePermutaciones
        : Boolean(origen.invariantePermutaciones),
    timeoutMs: Math.max(1000, numero(origen.timeoutMs, DEFAULTS.timeoutMs)),
    estadoInicial: String(origen.estadoInicial ?? DEFAULTS.estadoInicial),
  }
}

/** Localiza el intérprete de Python del runtime de DSH o del sistema. */
function resolverPython(configurado) {
  if (configurado && configurado.trim()) return configurado.trim()
  const home = process.env.DSH_HOME
  if (home) {
    const candidatos = [
      join(home, 'dsh-runtimes', 'dsh-primary-runtime', 'dependencies', 'python', 'python.exe'),
      join(home, 'dsh-runtimes', 'dsh-primary-runtime', 'dependencies', 'python', 'bin', 'python3'),
    ]
    for (const candidato of candidatos) {
      if (existsSync(candidato)) return candidato
    }
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

/**
 * Proceso Python persistente que habla el protocolo JSON línea a línea con
 * `bridge_vos.py`. Se mantiene vivo para conservar el aprendizaje (caché W,
 * octree y cadenas de Markov) entre llamadas de herramientas.
 */
class PuenteVectorW extends EventEmitter {
  constructor(config) {
    super()
    this.config = config
    this.hijo = null
    this.buffer = ''
    this.pendientes = new Map()
    this.siguienteId = 1
    this.estado = 'detenido'
    this.ultimoError = null
  }

  get arrancado() {
    return this.estado === 'listo' || this.estado === 'arrancando'
  }

  /** Arranca el proceso si no está vivo. Devuelve la info de `init`. */
  async arrancar() {
    if (this.estado === 'listo') return this.info
    if (this.estado === 'arrancando') return this.arranque

    this.estado = 'arrancando'
    this.arranque = this.#lanzar()
    try {
      this.info = await this.arranque
      this.estado = 'listo'
      return this.info
    } catch (error) {
      this.estado = 'fallido'
      this.ultimoError = error
      throw error
    }
  }

  async #lanzar() {
    const python = resolverPython(this.config.rutaPython)
    const rutaCore = this.config.rutaCore?.trim() || ''

    this.hijo = spawn(python, ['-u', RUTA_BRIDGE], {
      cwd: RAIZ_PAQUETE,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    })

    this.hijo.stdout.setEncoding('utf8')
    this.hijo.stderr.setEncoding('utf8')
    this.hijo.stdout.on('data', (trozo) => this.#consumir(trozo))
    this.hijo.stderr.on('data', (trozo) => {
      this.ultimoError = String(trozo).trim()
      this.emit('diagnostico', this.ultimoError)
    })
    this.hijo.on('exit', (codigo) => this.#alMorir(codigo))
    this.hijo.on('error', (error) => this.#alMorir(null, error))

    const info = await this.llamar('init', {
      config: {
        ruta_core: rutaCore || null,
        lado_cubo: Math.round(this.config.ladoCubo),
        n_espacios: Math.round(this.config.nEspacios),
        orden_markov: Math.round(this.config.ordenMarkov),
        umbral_similitud: this.config.umbralSimilitud,
        max_entradas: Math.round(this.config.maxEntradas),
        ttl_segundos: this.config.ttlSegundos,
        invariante_permutaciones: this.config.invariantePermutaciones,
      },
    })

    const inicial = this.config.estadoInicial?.trim()
    if (inicial) {
      try {
        info.restaurado = await this.llamar('restore', { path: inicial })
      } catch (error) {
        info.restaurado = { restaurado: false, motivo: String(error.message ?? error) }
      }
    }
    return info
  }

  /** Reparte la salida del puente en mensajes JSON completos. */
  #consumir(trozo) {
    this.buffer += trozo
    let corte = this.buffer.indexOf('\n')
    while (corte >= 0) {
      const linea = this.buffer.slice(0, corte).trim()
      this.buffer = this.buffer.slice(corte + 1)
      if (linea) this.#resolver(linea)
      corte = this.buffer.indexOf('\n')
    }
  }

  #resolver(linea) {
    let mensaje
    try {
      mensaje = JSON.parse(linea)
    } catch {
      return // ruido de stdout (avisos del núcleo): se ignora
    }
    const pendiente = this.pendientes.get(mensaje.id)
    if (!pendiente) return
    this.pendientes.delete(mensaje.id)
    clearTimeout(pendiente.temporizador)
    if (mensaje.ok) pendiente.resolver(mensaje.result)
    else pendiente.rechazar(new Error(mensaje.error ?? 'error del puente VectorW'))
  }

  #alMorir(codigo, error) {
    const motivo = error
      ? `no se pudo iniciar Python: ${error.message}`
      : `el puente VectorW terminó con código ${codigo}`
    for (const pendiente of this.pendientes.values()) {
      clearTimeout(pendiente.temporizador)
      pendiente.rechazar(new Error(motivo))
    }
    this.pendientes.clear()
    this.hijo = null
    this.buffer = ''
    if (this.estado !== 'detenido') {
      this.estado = 'fallido'
      this.ultimoError = motivo
    }
    this.emit('caida', motivo)
  }

  /** Envía una petición y espera su respuesta. */
  llamar(method, params = {}) {
    if (!this.hijo) {
      return Promise.reject(
        new Error(this.ultimoError ?? 'el puente VectorW no está en ejecución'),
      )
    }
    const id = this.siguienteId++
    const timeout = Math.max(1000, Math.round(this.config.timeoutMs))
    return new Promise((resolver, rechazar) => {
      const temporizador = setTimeout(() => {
        this.pendientes.delete(id)
        rechazar(new Error(`timeout de ${timeout} ms en vector_${method}`))
      }, timeout)
      this.pendientes.set(id, { resolver, rechazar, temporizador })
      this.hijo.stdin.write(`${JSON.stringify({ id, method, params })}\n`)
    })
  }

  /** Arranca si hace falta y llama. */
  async usar(method, params) {
    await this.arrancar()
    return this.llamar(method, params)
  }

  /** Cierra el proceso y limpia temporizadores. */
  cerrar() {
    this.estado = 'detenido'
    for (const pendiente of this.pendientes.values()) {
      clearTimeout(pendiente.temporizador)
      pendiente.rechazar(new Error('plugin VectorW descargado'))
    }
    this.pendientes.clear()
    if (this.hijo) {
      try {
        this.hijo.stdin.end()
        this.hijo.kill()
      } catch {
        /* el proceso ya no está */
      }
      this.hijo = null
    }
  }
}

/** Formatea una lista de números para mostrarla al modelo. */
const lista = (valores, nd = 4) =>
  Array.isArray(valores) ? valores.map((v) => Number(v).toFixed(nd)).join(', ') : '—'

/** Descripción común del subsistema. */
const CABECERA =
  'VectorW (vOS v6.0) indexa cada texto como una firma W 4D sobre las 4 diagonales ' +
  'de un cubo de memoria y detecta consultas equivalentes aunque cambien las palabras. ' +
  'Úsalo para no repetir trabajo: antes de una búsqueda o de mandar un contexto largo al ' +
  'modelo, comprueba la caché; después de obtener el resultado, guárdalo.'

/**
 * Registra las herramientas `vector_*` sobre el registro de herramientas.
 *
 * @param ctx - contexto Cordis con `ctx.tools`.
 * @param config - configuración ya validada por {@link Config}.
 */
export function apply(ctx, configBruto) {
  const config = normalizarConfig(configBruto)
  const puente = new PuenteVectorW(config)
  let avisoEmitido = false

  // El puente es un recurso del plugin: se cierra cuando la entrada se descarga.
  ctx.on('dispose', () => puente.cerrar())

  /** Ejecuta una operación del puente traduciendo fallos a errores legibles. */
  async function invocar(method, params) {
    try {
      return await puente.usar(method, params)
    } catch (error) {
      throw new Error(
        `VectorW no disponible: ${error.message}. ` +
          `Revisa "rutaCore" en la configuración del plugin (debe apuntar a la carpeta vectorW_py).`,
      )
    }
  }

  /** Arranca el puente en segundo plano para que la primera llamada sea rápida. */
  puente
    .arrancar()
    .then((info) => {
      if (info?.modo !== 'vectorw' && !avisoEmitido) {
        avisoEmitido = true
        ctx.logger?.warn?.(
          `[plugin-vectorw] núcleo en modo degradado: ${info?.motivo_degradado ?? 'desconocido'}`,
        )
      }
    })
    .catch(() => {
      /* el primer uso de una herramienta reportará el fallo completo */
    })

  ctx.tools.register(
    defineTool({
      name: 'vector_cache_check',
      description:
        `${CABECERA} Devuelve el resultado ya cacheado cuando la consulta es equivalente ` +
        'a una anterior (hit), o indica que no está (miss) para que la ejecutes tú.',
      parameters: {
        query: {
          type: 'string',
          required: true,
          description: 'La consulta o tarea a comprobar, en lenguaje natural.',
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          properties: {
            hit: { type: 'boolean', required: true },
            kind: { type: 'string', required: true },
            resumen: { type: 'string', required: true },
          },
        },
        render: (_args, valor) => [{ type: 'text', text: valor.resumen }],
      },
      async execute(args) {
        const resultado = await invocar('cache_check', { query: args.query })
        if (!resultado.hit) {
          const detalle = resultado.mejor_distancia != null
            ? ` La candidata más cercana queda a ${resultado.mejor_distancia}` +
              ` (solapamiento ${resultado.mejor_solapamiento}${resultado.motivo ? `, ${resultado.motivo}` : ''}).`
            : ''
          return {
            hit: false,
            kind: 'miss',
            resumen:
              `MISS — "${args.query}" no está en la caché W (${resultado.candidatos} entradas ` +
              `comparadas, umbral ${resultado.umbral}).${detalle} Ejecuta el trabajo y guárdalo con ` +
              `vector_cache_store.`,
          }
        }
        const valor =
          typeof resultado.value === 'string'
            ? resultado.value
            : JSON.stringify(resultado.value, null, 2)
        const como =
          resultado.kind === 'exacto'
            ? 'coincidencia exacta'
            : `coincidencia semántica (distancia W ${resultado.distancia_w.toFixed(4)}, ` +
              `solapamiento ${(resultado.solapamiento * 100).toFixed(0)}%)`
        return {
          hit: true,
          kind: resultado.kind,
          entradaOriginal: resultado.query,
          tokensAhorrados: resultado.tokens_ahorrados,
          distanciaW: resultado.distancia_w,
          valor: resultado.value,
          resumen:
            `HIT (${como}) — "${args.query}" reutiliza la entrada "${resultado.query}" ` +
            `(~${resultado.tokens_ahorrados} tokens evitados).\n\n${valor}`,
        }
      },
      presentCall: (args) => ({
        card: 'generic',
        title: 'VectorW · comprobar caché',
        kind: 'search',
        rawInput: args.query,
      }),
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'vector_cache_store',
      description:
        `${CABECERA} Guarda el resultado de una consulta en la caché semántica W 4D para ` +
        'reutilizarlo sin volver a consultar fuentes externas ni gastar tokens.',
      parameters: {
        query: {
          type: 'string',
          required: true,
          description: 'La consulta que produjo este resultado.',
        },
        value: {
          type: 'string',
          required: true,
          description: 'El resultado a cachear (texto o JSON serializado).',
        },
        tokens: {
          type: 'integer',
          description: 'Coste estimado en tokens de obtener este resultado (para medir el ahorro).',
        },
        etiquetas: {
          type: 'object',
          additionalProperties: true,
          description: 'Metadatos libres (herramienta de origen, ruta, versión...).',
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          properties: {
            stored: { type: 'boolean', required: true },
            resumen: { type: 'string', required: true },
          },
        },
        render: (_args, valor) => [{ type: 'text', text: valor.resumen }],
      },
      async execute(args) {
        const resultado = await invocar('cache_store', {
          query: args.query,
          value: args.value,
          tokens: args.tokens ?? 0,
          metadata: args.etiquetas ?? {},
        })
        return {
          stored: true,
          tokens: resultado.tokens,
          entradas: resultado.entradas,
          espaciosW: resultado.espacios_w,
          resumen:
            `Cacheado en el espacio W ${JSON.stringify(resultado.espacios_w)} ` +
            `(firma ${lista(resultado.firma_w)}). Entradas totales: ${resultado.entradas}.`,
        }
      },
      presentCall: (args) => ({
        card: 'generic',
        title: 'VectorW · guardar en caché',
        kind: 'other',
        rawInput: args.query,
      }),
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'vector_predict',
      description:
        `${CABECERA} Predice las próximas consultas probables a partir del patrón de acceso ` +
        'ya aprendido (Markov de orden superior + filtro de Kalman sobre las 4 diagonales W). ' +
        'Sirve para prefetch: pedir de antemano lo que el agente va a necesitar. ' +
        'Necesita historial: con menos de dos entradas guardadas no hay transición que ' +
        'aprender y devuelve una lista vacía.',
      parameters: {
        n: {
          type: 'integer',
          description: 'Cuántas sugerencias devolver (1-20, por defecto 5).',
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          properties: {
            resumen: { type: 'string', required: true },
          },
        },
        render: (_args, valor) => [{ type: 'text', text: valor.resumen }],
      },
      async execute(args) {
        const resultado = await invocar('predict', { n: args.n ?? 5 })
        const lineas = []
        if (resultado.sugerencias?.length) {
          lineas.push('Consultas probables (aprendidas del historial):')
          for (const s of resultado.sugerencias) {
            lineas.push(`  • ${s.query}  (confianza ${s.confianza})`)
          }
        } else {
          lineas.push(
            'Aún no hay historial suficiente para predecir: hacen falta al menos dos ' +
              'consultas guardadas con vector_cache_store.',
          )
        }
        if (resultado.puntos_w?.length) {
          lineas.push('Próximos puntos en el cubo W 4D:')
          for (const p of resultado.puntos_w) {
            lineas.push(`  • coords [${lista(p.coords, 2)}]  confianza ${p.confianza}`)
          }
        }
        return {
          sugerencias: resultado.sugerencias ?? [],
          puntosW: resultado.puntos_w ?? [],
          modo: resultado.modo,
          resumen: lineas.join('\n'),
        }
      },
      presentCall: () => ({
        card: 'generic',
        title: 'VectorW · predecir siguientes consultas',
        kind: 'other',
      }),
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'vector_stats',
      description:
        `${CABECERA} Informa del estado del subsistema: aciertos de caché, tokens ahorrados, ` +
        'entropía y predecibilidad por diagonal W, y si el núcleo VectorW real está activo.',
      parameters: {},
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          properties: {
            resumen: { type: 'string', required: true },
          },
        },
        render: (_args, valor) => [{ type: 'text', text: valor.resumen }],
      },
      async execute() {
        const m = await invocar('status', {})
        const c = m.cache_semantica ?? {}
        const nucleo = m.nucleo_vectorw ?? {}
        const predictor = nucleo.predictor ?? {}
        const familia = nucleo.familia_w ?? {}
        const porcentaje = (v) => `${(Number(v ?? 0) * 100).toFixed(1)}%`
        const lineas = [
          `Modo: ${m.modo}${m.motivo_degradado ? ` (${m.motivo_degradado})` : ''}`,
          `Caché semántica: ${c.entradas}/${c.max_entradas} entradas · umbral ${c.umbral_similitud}`,
          `Aciertos: ${c.hits_exactos} exactos + ${c.hits_semanticos} semánticos · ` +
            `fallos ${c.fallos} · hit rate ${porcentaje(c.hit_rate)}`,
          `Tokens ahorrados: ${c.tokens_ahorrados_efectivos} de ${c.tokens_almacenados} almacenados`,
          `Diagonales W: ${familia.n_diagonales ?? 0} · resolución total ` +
            `${familia.resolucion_total ?? 0} espacios`,
          `Predecibilidad media: ${porcentaje(familia.predecibilidad_promedio)} · ` +
            `entropía media: ${familia.entropia_promedio?.toFixed(4) ?? '—'}`,
          `Predictor: orden ${predictor.orden_markov ?? '—'} · precisión ` +
            `${predictor.precision_bruta ?? '—'} · patrones ` +
            `${Object.values(predictor.patrones_detectados ?? {}).join(', ') || '—'}`,
          `Parches de compatibilidad activos: ${(m.parches ?? []).length}`,
        ]
        return { metricas: m, resumen: lineas.join('\n') }
      },
      presentCall: () => ({
        card: 'generic',
        title: 'VectorW · estadísticas',
        kind: 'other',
      }),
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'vector_persist',
      description:
        `${CABECERA} Guarda o restaura el estado de la caché semántica en disco, para que el ` +
        'ahorro de tokens sobreviva entre sesiones. Usa action="save" o action="restore".',
      parameters: {
        action: {
          type: 'string',
          required: true,
          enum: ['save', 'restore'],
          description: 'save = escribir el estado; restore = leerlo.',
        },
        path: {
          type: 'string',
          description: 'Ruta del archivo de estado.',
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          properties: {
            resumen: { type: 'string', required: true },
          },
        },
        render: (_args, valor) => [{ type: 'text', text: valor.resumen }],
      },
      async execute(args) {
        const ruta = args.path?.trim() || join(RAIZ_PAQUETE, 'vectorw_state.json')
        if (args.action === 'save') {
          const r = await invocar('persist', { path: ruta })
          return { resumen: `Estado VectorW guardado en ${r.path} (${r.entradas} entradas).` }
        }
        const r = await invocar('restore', { path: ruta })
        return {
          resumen: r.restaurado
            ? `Estado VectorW restaurado desde ${r.path} (${r.entradas} entradas).`
            : `No se restauró nada: ${r.motivo}`,
        }
      },
      presentCall: (args) => ({
        card: 'generic',
        title: `VectorW · ${args.action === 'save' ? 'guardar' : 'restaurar'} estado`,
        kind: 'other',
      }),
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'vector_purge',
      description:
        `${CABECERA} Vacía la caché semántica W 4D. Úsalo cuando el contexto haya cambiado ` +
        'tanto que las entradas guardadas ya no sean fiables.',
      parameters: {},
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          properties: {
            resumen: { type: 'string', required: true },
          },
        },
        render: (_args, valor) => [{ type: 'text', text: valor.resumen }],
      },
      async execute() {
        const r = await invocar('purge', {})
        return { resumen: `Caché VectorW vaciada: ${r.purgadas} entradas eliminadas.` }
      },
      presentCall: () => ({
        card: 'generic',
        title: 'VectorW · vaciar caché',
        kind: 'other',
      }),
    }),
  )
}
