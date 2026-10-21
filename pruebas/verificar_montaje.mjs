/**
 * Banco de pruebas de puesta en uso del plugin VectorW.
 *
 * Reproduce, paso a paso, lo que hace el loader de Cordis al arrancar DSH:
 * resuelve el especificador desde el directorio del perfil, importa el módulo
 * (con lo que se resuelven sus dependencias), crea un `Context` real de
 * Cordis, registra el servicio `tools` y aplica el plugin sobre él. Después
 * invoca las herramientas de verdad.
 *
 * Es lo más cerca del arranque real que se puede llegar sin reiniciar DSH:
 * si esto pasa, el único paso que falta en el arranque real es que el loader
 * lea la fila del perfil, y eso ya se verificó con `--dump-config`.
 *
 *     node pruebas/verificar_montaje.mjs
 *     node pruebas/verificar_montaje.mjs --solo-montaje
 *
 * `--solo-montaje` omite la seccion 4 (ejecucion real de las herramientas).
 * Es necesario cuando esta prueba se lanza desde otro proceso que captura la
 * salida: bajo el sandbox de Windows un proceso anidado no puede abrir
 * tuberias, y el arranque del puente Python fallaria con EPERM aunque el
 * plugin este perfectamente montado. La ejecucion de las herramientas la
 * cubren `verificar.mjs` y `verificar_ahorro.mjs`, que si corren en el nivel
 * superior.
 *
 * Debe ejecutarse desde el directorio del perfil de DSH (donde vive
 * node_modules), igual que la resolucion del loader.
 */

import { createRequire } from 'node:module'
import { readFileSync, existsSync, rmSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve, dirname } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const SOLO_MONTAJE = process.argv.includes('--solo-montaje')

const DSH_HOME = process.env.DSH_HOME ?? 'C:/Users/PePiuoX/.dsh'
const PERFIL = process.env.DSH_PROFILE ?? 'desktop'
const DIR_PERFIL = join(DSH_HOME, 'profiles', PERFIL)
// Raíz del plugin: el directorio padre de pruebas/.
const RAIZ_PLUGIN = resolve(dirname(fileURLToPath(import.meta.url)), '..')

let comprobaciones = 0
let fallos = 0

/** Registra el resultado de una comprobación. */
function afirmar(condicion, mensaje, detalle = '') {
  comprobaciones++
  if (condicion) {
    console.log(`  OK    ${mensaje}`)
  } else {
    fallos++
    console.error(`  FALLO ${mensaje}${detalle ? `\n        ${detalle}` : ''}`)
  }
}

function titulo(texto) {
  console.log(`\n${texto}`)
  console.log('-'.repeat(66))
}

console.log('Verificacion de montaje del plugin VectorW')
console.log(`Perfil: ${DIR_PERFIL}`)

// ---------------------------------------------------------------------------
titulo('1. Estado del perfil')
// ---------------------------------------------------------------------------

// La fila la aporta el PATCH DEL BUNDLE, no el cordis.patch.yml del usuario.
// Escribirla a mano en el perfil fue justo lo que impedía habilitar el plugin.
const patchBundle = readFileSync(join(RAIZ_PLUGIN, 'cordis.patch.yml'), 'utf8')
const tieneFila = /id:\s*vectorw-memory/.test(patchBundle)
const bajoInsert = /-\s*insert:[\s\S]*?id:\s*vectorw-memory/.test(patchBundle)
afirmar(tieneFila, 'El patch del bundle declara la fila vectorw-memory')
afirmar(
  bajoInsert,
  'La fila esta bajo "insert:" (obligatorio para ANADIR filas)',
  'Sin "insert:" el loader la trata como parche de una fila inexistente y la descarta.',
)

// El paquete debe estar declarado como bundle del perfil.
let enBundles = false
try {
  const perfilPkg = JSON.parse(readFileSync(join(DIR_PERFIL, 'package.json'), 'utf8'))
  enBundles = (perfilPkg?.dsh?.profile?.bundles ?? []).includes(
    '@deepseek-ai/dsh-plugin-vectorw',
  )
} catch { /* se reporta abajo */ }
afirmar(
  enBundles,
  'El bundle esta declarado en dsh.profile.bundles del perfil',
  'Debe instalarlo install_bundle, no escribirse a mano.',
)

// El enlace del paquete debe estar materializado en el perfil.
const rutaNodeModules = join(DSH_HOME, 'profiles', 'node_modules')
const rutasCandidatas = [
  join(DIR_PERFIL, 'node_modules', '@deepseek-ai', 'dsh-plugin-vectorw'),
  join(rutaNodeModules, '@deepseek-ai', 'dsh-plugin-vectorw'),
]
const rutaEnlace = rutasCandidatas.find((r) => existsSync(r))
afirmar(!!rutaEnlace, `El paquete esta instalado (${rutaEnlace ?? 'no encontrado'})`)

// ---------------------------------------------------------------------------
titulo('2. Resolucion como la hace el loader')
// ---------------------------------------------------------------------------

const requireDesdePerfil = createRequire(
  pathToFileURL(join(rutaNodeModules, '..', 'package.json')).href,
)

let entrada
try {
  entrada = requireDesdePerfil.resolve('@deepseek-ai/dsh-plugin-vectorw')
  afirmar(true, `resolve OK -> ${entrada}`)
} catch (error) {
  afirmar(false, 'resolve del especificador del plugin', `${error.code}: ${error.message}`)
  process.exit(1)
}

// El plugin debe poder resolver SUS dependencias desde su ruta real. Esto es
// lo que exige el enlace vecino de node_modules que crea install.ps1.
let contexto
try {
  const { Context } = await import(
    pathToFileURL(requireDesdePerfil.resolve('@deepseek-ai/cordis')).href
  )
  const { defineTool } = await import(
    pathToFileURL(requireDesdePerfil.resolve('@deepseek-ai/dsh-tools')).href
  )
  contexto = new Context()
  afirmar(true, 'Dependencias del plugin resueltas (@deepseek-ai/cordis, dsh-tools)')

  // Servicio `tools` minimo, con la misma forma que consume el plugin.
  const registradas = new Map()
  contexto.provide('tools', {
    register(define) {
      registradas.set(define.name, define)
      return () => registradas.delete(define.name)
    },
  })
  contexto.__registradas = registradas
  contexto.__defineTool = defineTool
} catch (error) {
  afirmar(false, 'Resolver las dependencias del plugin', String(error))
  process.exit(1)
}

// ---------------------------------------------------------------------------
titulo('3. Montaje del plugin sobre un Context real de Cordis')
// ---------------------------------------------------------------------------

let modulo
try {
  modulo = await import(pathToFileURL(entrada).href)
  afirmar(true, `import del plugin OK -> exports: ${Object.keys(modulo).join(', ')}`)
} catch (error) {
  afirmar(false, 'import del plugin', `${error.code}: ${error.message}`)
  process.exit(1)
}

afirmar(typeof modulo.name === 'string', `name exportado: ${modulo.name}`)
afirmar(Array.isArray(modulo.inject), `inject declarado: ${JSON.stringify(modulo.inject)}`)
afirmar(typeof modulo.apply === 'function', 'apply exportado')
afirmar(!!modulo.Config, 'Config exportado (esquema de configuracion)')

// Leer la configuracion REAL de la fila (la declara el patch del bundle).
function configDelPerfil() {
  const lineas = patchBundle.split(/\r?\n/)
  const i = lineas.findIndex((l) => /^\s*-\s*id:\s*vectorw-memory\s*$/.test(l))
  const config = {}
  if (i < 0) return config
  for (let j = i + 1; j < lineas.length; j++) {
    if (/^\s*-\s/.test(lineas[j])) break
    const m = /^\s{6}([A-Za-z_]\w*):\s*(.*)$/.exec(lineas[j])
    if (!m) continue
    let v = m[2].trim().replace(/^["']|["']$/g, '')
    if (v === 'true') v = true
    else if (v === 'false') v = false
    else if (v !== '' && !Number.isNaN(Number(v))) v = Number(v)
    config[m[1]] = v
  }
  return config
}

const config = configDelPerfil()
// La memoria SQLite de esta prueba no debe contaminar la memoria real del
// usuario: se usa una base temporal dentro de pruebas/ y se borra al final.
// En el TEMP del sistema, no en el repo: el puente puede mantener la base
// abierta hasta que el proceso muere y Windows no permite borrarla en caliente.
const carpetaMemoriaPrueba = join(tmpdir(), 'vectorw-montaje-prueba')
// Limpieza de ejecuciones anteriores: aquí ya no hay ningún puente vivo.
try {
  rmSync(carpetaMemoriaPrueba, { recursive: true, force: true })
} catch { /* otro proceso la mantiene abierta */ }
mkdirSync(carpetaMemoriaPrueba, { recursive: true })
const rutaMemoriaPrueba = join(carpetaMemoriaPrueba, 'memoria.db')
config.rutaMemoria = rutaMemoriaPrueba
// El puente mantiene la base abierta hasta que DSH descarga el plugin, así que
// el borrado del final puede no ser posible en Windows. Se limpia al ARRANCAR,
// cuando ya no hay ningún proceso anterior usando esos ficheros.
for (const sufijo of ['', '-wal', '-shm']) {
  try {
    rmSync(`${rutaMemoriaPrueba}${sufijo}`, { force: true })
  } catch { /* otro proceso aún la tiene abierta */ }
}
console.log(`  config del perfil: ${JSON.stringify(config)}`)

// El loader aplica el plugin con un contexto hijo que ve el servicio `tools`.
try {
  modulo.apply(contexto, config)
  afirmar(true, 'apply() ejecutado sin errores')
} catch (error) {
  afirmar(false, 'apply() ejecutado sin errores', String(error))
  process.exit(1)
}

const esperadas = [
  'vector_cache_check',
  'vector_cache_store',
  'vector_predict',
  'vector_stats',
  'vector_persist',
  'vector_purge',
  'vector_proceso_buscar',
  'vector_proceso_guardar',
  'vector_recurso_buscar',
]
const registradas = contexto.__registradas
afirmar(
  esperadas.every((n) => registradas.has(n)),
  `${registradas.size} herramientas registradas: ${[...registradas.keys()].join(', ')}`,
)

// Cada herramienta debe declarar nombre, descripcion, parametros y salida.
for (const nombre of esperadas) {
  const define = registradas.get(nombre)
  if (!define) continue
  afirmar(
    !!define.description && !!define.parameters && !!define.output?.schema,
    `  ${nombre}: esquema completo`,
  )
}

// ---------------------------------------------------------------------------
titulo('4. Ejecucion real de las herramientas (puente Python)')
// ---------------------------------------------------------------------------

if (SOLO_MONTAJE) {
  console.log('  OMITIDO por --solo-montaje')
  console.log('  (la ejecucion de las herramientas la cubren verificar.mjs y verificar_ahorro.mjs)')
}
const ejecutar = async (nombre, args) => {
  const define = registradas.get(nombre)
  if (!define) throw new Error(`no registrada: ${nombre}`)
  const valor = await define.execute(args, {})
  const bloques = define.output.render(args, valor)
  return { valor, texto: bloques.map((b) => b.text).join('\n') }
}

const inicio = Date.now()
if (!SOLO_MONTAJE) {
try {
  const stats = await ejecutar('vector_stats', {})
  const primera = stats.texto.split('\n')[0]
  afirmar(/^Modo: vectorw/.test(primera), `vector_stats -> ${primera}`, stats.texto)
  afirmar(
    /Diagonales W: 4/.test(stats.texto),
    '  El nucleo real esta activo (4 diagonales)',
  )

  const miss = await ejecutar('vector_cache_check', { query: 'consulta inicial inexistente xyz' })
  afirmar(miss.valor.hit === false, 'vector_cache_check devuelve MISS en cache vacia')

  const guardado = await ejecutar('vector_cache_store', {
    query: 'optimizar consultas vectoriales con octree y poda espacial',
    value: 'Poda por octante: se descarta 7/8 del espacio por nivel.',
    tokens: 4200,
  })
  afirmar(guardado.valor.stored === true, 'vector_cache_store guarda la entrada')

  const hitExacto = await ejecutar('vector_cache_check', {
    query: 'optimizar consultas vectoriales con octree y poda espacial',
  })
  afirmar(hitExacto.valor.kind === 'exacto', 'vector_cache_check -> HIT exacto')

  const hitSemantico = await ejecutar('vector_cache_check', {
    query: 'optimizar consultas vectoriales con octree y podado espacial',
  })
  afirmar(
    hitSemantico.valor.kind === 'semantico',
    `vector_cache_check -> HIT semantico (distancia ${hitSemantico.valor.distanciaW?.toFixed(4)})`,
    hitSemantico.texto,
  )

  const ajeno = await ejecutar('vector_cache_check', {
    query: 'desplegar el plugin en linux con systemd',
  })
  afirmar(ajeno.valor.hit === false, 'vector_cache_check -> MISS en tema distinto (sin falso acierto)')

  // --- memoria de procesos, lecciones y catálogo (SQLite) -----------------
  const procesoGuardado = await ejecutar('vector_proceso_guardar', {
    intencion: 'migrar la tabla de pedidos a MySQL 8 con PDO y transacciones',
    resultado: 'Migracion 004_pedidos creada y verificada con 9/9 pruebas.',
    pasos: 'leer esquema\ncrear migracion\nejecutar pruebas',
    referencia: 'migrations/004_pedidos.sql',
    contexto: 'modulo=pedidos; preset=php-mysql-senior-factory-v2',
    estado: 'validado',
    tokens: 2100,
    leccion: {
      tipo: 'base-de-datos',
      causa: 'falta indice en la columna de busqueda',
      correccion: 'crear indice compuesto (tenant_id, estado)',
      prevencion: 'revisar el plan de ejecucion antes de desplegar',
      modulo: 'pedidos',
    },
  })
  afirmar(procesoGuardado.valor.guardado === true,
    `vector_proceso_guardar guarda en SQLite (id ${procesoGuardado.valor.id})`)

  const procesoHit = await ejecutar('vector_proceso_buscar', {
    query: 'migrar tabla pedidos MySQL con PDO y transacciones',
  })
  afirmar(procesoHit.valor.hit === true,
    `vector_proceso_buscar -> HIT (${procesoHit.valor.procesos?.length ?? 0} procesos)`,
    procesoHit.texto)
  afirmar((procesoHit.valor.lecciones ?? []).length > 0,
    'vector_proceso_buscar devuelve la leccion asociada')

  const procesoMiss = await ejecutar('vector_proceso_buscar', {
    query: 'disenar un sistema de facturacion electronica',
  })
  afirmar(procesoMiss.valor.hit === false,
    'vector_proceso_buscar -> MISS en tema distinto')

  const recurso = await ejecutar('vector_recurso_buscar', {
    query: 'guardar un resultado en la cache semantica',
    tipo: 'herramienta',
  })
  afirmar(recurso.valor.hit === true,
    `vector_recurso_buscar -> HIT (${recurso.valor.recursos?.[0]?.nombre ?? '—'})`,
    recurso.texto)

  const statsMemoria = await ejecutar('vector_stats', {})
  afirmar(/Memoria SQLite: \d+ procesos/.test(statsMemoria.texto),
    'vector_stats informa de la memoria SQLite')
  afirmar(/Presupuesto: 6000 car\./.test(statsMemoria.texto),
    'vector_stats informa del presupuesto de tokens')

  // El predictor necesita historial: con una sola entrada no hay transición
  // que aprender. Se comprueba su comportamiento en los dos casos.
  const sinHistorial = await ejecutar('vector_predict', { n: 3 })
  afirmar(
    sinHistorial.valor.sugerencias.length === 0,
    'vector_predict sin historial suficiente -> 0 sugerencias (y lo explica)',
  )
  afirmar(
    /historial|predecir/i.test(sinHistorial.texto),
    '  El mensaje explica por que no hay sugerencias',
  )

  await ejecutar('vector_cache_store', {
    query: 'configurar la cache LRU con TTL y frecuencia',
    value: 'Expulsion por score = frecuencia*0.7 - antiguedad*0.3.',
    tokens: 60,
  })
  await ejecutar('vector_cache_store', {
    query: 'prediccion markov de orden superior',
    value: 'Backoff de orden 4 a 1 con suavizado de Laplace.',
    tokens: 75,
  })
  const conHistorial = await ejecutar('vector_predict', { n: 3 })
  afirmar(
    conHistorial.valor.sugerencias.length > 0,
    `vector_predict con historial -> ${conHistorial.valor.sugerencias.length} sugerencias` +
      ` (${conHistorial.valor.sugerencias.map((s) => s.confianza).join(', ')})`,
    conHistorial.texto,
  )
  afirmar(
    conHistorial.valor.puntosW.length > 0,
    `vector_predict devuelve ${conHistorial.valor.puntosW.length} puntos W 4D`,
  )

  const persistido = await ejecutar('vector_persist', {
    action: 'save',
    path: join(DIR_PERFIL, 'vectorw_estado_prueba.json'),
  })
  afirmar(/guardado en/.test(persistido.texto), 'vector_persist guarda el estado')

  const purgado = await ejecutar('vector_purge', {})
  afirmar(/vaciada/.test(purgado.texto), 'vector_purge vacia la cache')
} catch (error) {
  afirmar(false, 'Ejecucion de las herramientas', String(error))
}

console.log(`\n  (tiempo total de las herramientas: ${Date.now() - inicio} ms)`)
}

// La base de memoria de la prueba era temporal: no se deja basura en el repo.
// Descargar el contexto ejecuta el `dispose` del plugin, que cierra el puente
// Python; sin eso, Windows mantiene los ficheros SQLite bloqueados.
try {
  await contexto.dispose()
} catch { /* el contexto de prueba puede no exponer dispose */ }
await new Promise((listo) => setTimeout(listo, 600))
for (const sufijo of ['', '-wal', '-shm']) {
  let borrado = false
  for (let intento = 0; intento < 10; intento++) {
    try {
      rmSync(`${rutaMemoriaPrueba}${sufijo}`, { force: true })
      borrado = true
      break
    } catch {
      await new Promise((listo) => setTimeout(listo, 300))
    }
  }
  if (!borrado && process.env.VECTORW_DEBUG) {
    console.log(`  AVISO no se pudo borrar ${rutaMemoriaPrueba}${sufijo} (proceso aún vivo)`)
  }
}

// ---------------------------------------------------------------------------
console.log('\n' + '='.repeat(66))
if (fallos > 0) {
  console.error(`RESULTADO: ${fallos} FALLOS de ${comprobaciones} comprobaciones`)
  process.exit(1)
}
console.log(`RESULTADO: ${comprobaciones}/${comprobaciones} comprobaciones OK`)
console.log(
  SOLO_MONTAJE
    ? '  El plugin se monta correctamente en el perfil.'
    : '  El plugin se monta y funciona igual que lo hara al arrancar DSH.',
)
process.exit(0)
