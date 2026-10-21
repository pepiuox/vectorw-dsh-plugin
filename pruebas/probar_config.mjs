/**
 * Prueba de validación de la Config del plugin con la librería real.
 *
 * Comprueba si el esquema Schemastery que exporta el plugin acepta la
 * configuración que tiene realmente el perfil, en particular `rutaCore: null`
 * (que es lo que produce un `rutaCore:` vacío en YAML).
 *
 *     node pruebas/probar_config.mjs
 */

import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'

const requireAqui = createRequire(import.meta.url)
const esquemaUrl = pathToFileURL(requireAqui.resolve('@deepseek-ai/schemastery')).href
const { default: z } = await import(esquemaUrl)

const plugin = await import(pathToFileURL(fileURLToPath(
  new URL('../lib/index.js', import.meta.url))).href)

const Config = plugin.Config
console.log('Config exportada:', typeof Config, Object.keys(Config ?? {}))

/** Intenta validar y describe el resultado sin lanzar. */
function probar(etiqueta, entrada) {
  try {
    const salida = Config(entrada)
    console.log(`  OK    ${etiqueta} -> ${JSON.stringify(salida)}`)
    return true
  } catch (error) {
    console.log(`  FALLA ${etiqueta} -> ${error.constructor.name}: ${error.message}`)
    return false
  }
}

console.log('\n=== Config tal como está en el perfil (rutaCore vacío = null) ===')
const real = { rutaCore: null, umbralSimilitud: 0.15, maxEntradas: 2000, ordenMarkov: 2 }
probar('rutaCore: null', real)

console.log('\n=== Variantes ===')
probar("rutaCore: ''", { rutaCore: '', umbralSimilitud: 0.15, maxEntradas: 2000, ordenMarkov: 2 })
probar('rutaCore ausente', { umbralSimilitud: 0.15, maxEntradas: 2000, ordenMarkov: 2 })
probar('config vacía', {})
probar('rutaCore: null (solo)', { rutaCore: null })

console.log('\n=== ¿Qué tipo acepta realmente el esquema? ===')
const soloRuta = Config.dict?.rutaCore
console.log('  rutaCore meta:', JSON.stringify(soloRuta?.meta ?? null))
try {
  console.log('  z.string()(null) =', JSON.stringify(z.string()(null)))
} catch (e) {
  console.log('  z.string()(null) lanza:', e.constructor.name, e.message)
}
