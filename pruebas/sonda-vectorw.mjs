// Sonda: comprueba si el loader de Cordis puede resolver el plugin desde el
// perfil y si el plugin, a su vez, resuelve sus propias dependencias.
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { realpathSync } from 'node:fs'

const req = createRequire(import.meta.url)
let entrada
try {
  entrada = req.resolve('@deepseek-ai/dsh-plugin-vectorw')
  console.log('resolve OK ->', entrada)
} catch (e) {
  console.log('resolve FALLO ->', e.code, e.message)
  process.exit(1)
}

try {
  const mod = await import(pathToFileURL(entrada).href)
  console.log('import OK -> exports:', Object.keys(mod).join(', '))
  console.log('realpath plugin ->', realpathSync(entrada))
} catch (e) {
  console.log('import FALLO ->', e.code, e.message)
  process.exit(1)
}
