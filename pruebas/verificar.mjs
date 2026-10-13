/**
 * Verificación del plugin VectorW sin arrancar la GUI de DSH.
 *
 * Simula lo que hace el loader de Cordis: importa el módulo tal como lo haría
 * el perfil y aplica el plugin sobre un ctx falso que captura las herramientas
 * registradas. Después ejecuta cada herramienta contra el puente Python real.
 *
 *   node --experimental-vm-modules verificar.mjs
 */

import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { readFileSync } from 'node:fs'

// La raíz del paquete es el directorio padre de pruebas/.
const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Igual que el loader de Cordis: la resolución parte del directorio del perfil,
// de modo que esto comprueba de verdad el enlace en profiles/node_modules.
const requireDesdePerfil = createRequire(
  pathToFileURL(join(process.env.DSH_HOME ?? 'C:/Users/PePiuoX/.dsh', 'profiles', 'package.json')).href,
)
const ENTRADA = pathToFileURL(requireDesdePerfil.resolve('@deepseek-ai/dsh-plugin-vectorw')).href

// --- réplica mínima de schemastery (solo lo que usa el plugin) -------------
function replica(esquema) {
  const campos = Object.fromEntries(
    Object.entries(esquema.dict).map(([k, v]) => [k, { meta: v.meta ?? {}, tipo: v }]),
  )
  return {
    campos,
    validar(entrada = {}) {
      const salida = {}
      for (const [nombre, { meta, tipo }] of Object.entries(campos)) {
        let valor = entrada[nombre]
        if (valor === undefined) valor = meta.default
        if (typeof tipo?.validar === 'function') valor = tipo.validar(valor)
        salida[nombre] = valor
      }
      return salida
    },
  }
}
const z = new Proxy(
  { object: (forma) => replica(forma) },
  {
    get(objetivo, prop) {
      if (prop in objetivo) return objetivo[prop]
      return (meta = {}) => ({ meta, validar: (v) => v })
    },
  },
)

const { defineTool } = await import(
  pathToFileURL(requireDesdePerfil.resolve('@deepseek-ai/dsh-tools')).href
)

// --- ctx falso ------------------------------------------------------------
const registradas = new Map()
const ctx = {
  tools: {
    register(define) {
      registradas.set(define.name, define)
      return () => registradas.delete(define.name)
    },
  },
  on() {},
  get: () => undefined,
  inject(_servicios, cb) {
    try {
      cb(ctx)
    } catch {
      /* servicio ausente en esta prueba */
    }
  },
  logger: Object.assign(
    () => ({ warn: (m) => console.log(`[warn] ${m}`), info: () => {}, error: (m) => console.log(`[err] ${m}`) }),
    { warn: (m) => console.log(`[warn] ${m}`), info: () => {}, error: (m) => console.log(`[err] ${m}`) },
  ),
}

// --- cargar el plugin como lo hace el loader ------------------------------
const mod = await import(ENTRADA)
const { name, apply } = mod
console.log(`\n=== plugin "${name}" importado ===`)

/**
 * Lee la entrada del plugin desde el cordis.patch.yml REAL del perfil, en vez
 * de inventar la configuración: así se prueba exactamente lo que verá DSH.
 */
function configDelPerfil() {
  const perfil = process.env.DSH_PROFILE_DIR ?? join(process.env.DSH_HOME, 'profiles', 'desktop')
  const yaml = readFileSync(join(perfil, 'cordis.patch.yml'), 'utf8')
  const lineas = yaml.split(/\r?\n/)
  const i = lineas.findIndex((l) => /^\s*-\s*id:\s*vectorw-memory\s*$/.test(l))
  if (i < 0) throw new Error('no hay entrada vectorw-memory en cordis.patch.yml')

  const config = {}
  for (let j = i + 1; j < lineas.length; j++) {
    const linea = lineas[j]
    if (/^\s*-\s/.test(linea)) break
    const m = /^\s{4}([A-Za-z_][\w]*):\s*(.*)$/.exec(linea) // solo el bloque config:
    if (!m) continue
    let valor = m[2].trim().replace(/^["']|["']$/g, '')
    if (valor === 'true') valor = true
    else if (valor === 'false') valor = false
    else if (valor !== '' && !Number.isNaN(Number(valor))) valor = Number(valor)
    config[m[1]] = valor
  }
  // Se eliminan las claves estructurales: `apply` debe completar el resto con
  // sus propios valores por defecto, y eso es justo lo que esta prueba valida.
  return config
}

const config = configDelPerfil()
console.log('config leída del perfil:', JSON.stringify(config, null, 2))

await apply(ctx, config)
console.log(`\n=== ${registradas.size} herramientas registradas ===`)
for (const n of registradas.keys()) console.log(`  • ${n}`)

// --- ejecutar herramientas contra el puente real --------------------------
const ejecutar = async (nombre, args) => {
  const define = registradas.get(nombre)
  if (!define) throw new Error(`no existe la herramienta ${nombre}`)
  const valor = await define.execute(args, {})
  const bloques = define.output.render(args, valor)
  console.log(`\n--- ${nombre}(${JSON.stringify(args)}) ---`)
  console.log(bloques.map((b) => b.text).join('\n'))
  return valor
}

const inicio = Date.now()
await ejecutar('vector_stats', {})
await ejecutar('vector_cache_check', { query: 'como funciona la diagonal W' })
await ejecutar('vector_cache_store', {
  query: 'como funciona la diagonal W',
  value: 'La firma W 4D proyecta el punto sobre las 4 diagonales del cubo.',
  tokens: 180,
})
await ejecutar('vector_cache_check', { query: 'Explica la diagonal W' })
await ejecutar('vector_cache_store', {
  query: 'configurar la cache LRU TTL',
  value: 'score = freq*0.7 - edad*0.3',
  tokens: 60,
})
await ejecutar('vector_cache_store', {
  query: 'prediccion markov orden superior',
  value: 'backoff con suavizado de Laplace',
  tokens: 75,
})
await ejecutar('vector_predict', { n: 3 })
await ejecutar('vector_persist', {
  action: 'save',
  path: join(RAIZ, '.verificacion_estado.json'),
})
await ejecutar('vector_stats', {})

console.log(`\n=== verificación completa en ${Date.now() - inicio} ms ===`)
process.exit(0)