# JavaScript — port verificado, sin dependencias

Puerto fiel de la implementación de referencia, en JavaScript puro.
**Verificado: 147/147 comprobaciones** contra el corpus compartido
`../pruebas/vectores_w.json`, incluida la comprobación de que su **SHA-256
propio** coincide con el de `node:crypto`.

> VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
> https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1

## Por qué existe este port, habiendo TypeScript

- **Cero dependencias y cero compilación.** No usa `import` de Node ni
  `require`: SHA-256 está implementado en el propio archivo con
  `TextEncoder`.
- **Funciona en el navegador.** Ese mismo detalle lo hace usable en un Service
  Worker o en una web, donde `node:crypto` no existe y
  `crypto.subtle.digest` es asíncrono (y obligaría a que toda la API fuese
  `async`).

## Verificación

```bash
# Desde la raíz del repositorio del plugin
node implementaciones/javascript/prueba.mjs
```

Salida esperada:

```
Vectores: 9 puntos, 15 textos, 5 distancias, 3 casos de caché
Cubo: lado 1024, 8 espacios por diagonal

RESULTADO: 147/147 comprobaciones OK
  El port JavaScript coincide con la referencia Python.
```

## Uso

```js
import { CacheSemanticaW, FamiliaDiagonalesW, tokenizar } from './vectorw_w.mjs'

const familia = new FamiliaDiagonalesW()          // cubo 1024, 8 espacios
const firma = familia.firmaDeTexto('optimizar consultas vectoriales con octree')

console.log(firma.tokens)     // ['optimizar', 'consult', 'vectorial', 'octree']
console.log(firma.firma)      // [0.674…, 1.085…, 1.134…, 1.186…]
console.log(firma.espacios)   // [5, 7, 7, 7]

const cache = new CacheSemanticaW(familia)
cache.guardar('optimizar consultas vectoriales con octree', 'resultado', 4200)

const r = cache.buscar('optimizar consultas vectoriales con octree y podado espacial')
console.log(r.hit, r.kind, r.distancia.toFixed(4))
// true semantico 0.1010      ← acierto: ~4200 tokens evitados
```

En el navegador, sirve el archivo directamente:

```html
<script type="module">
  import { CacheSemanticaW, FamiliaDiagonalesW } from './vectorw_w.mjs'
  const cache = new CacheSemanticaW(new FamiliaDiagonalesW())
  // ...
</script>
```

## API

| Símbolo | Descripción |
|---|---|
| `ConfigW` | Constantes (objeto congelado). |
| `sha256Hex(texto)` | SHA-256 en hexadecimal, sin dependencias. |
| `tokenizar(texto)` | Raíces significativas. |
| `sinAcentos(texto)`, `raiz(token)` | Pasos de la tokenización, expuestos para depurar. |
| `FamiliaDiagonalesW` | Las 4 diagonales y la aritmética de firmas. |
| `CacheSemanticaW` | Caché consulta→valor con recuperación por similitud. |

Métodos de `FamiliaDiagonalesW`: `parametroT`, `componentesDe`, `firmaDePunto`,
`espaciosDe`, `puntoW`, `centroide`, `firmaDeTexto`, `distanciaGeometrica`,
`distanciaPermutaciones`, `distancia`.

## Rendimiento

Para cada entrada de la caché se calcula la distancia bajo las 24 permutaciones
de los 4 componentes, así que una consulta cuesta `24 × n_entradas`
distancias. Con el umbral por defecto y un corpus de miles de entradas, eso
sigue siendo del orden de milisegundos en JavaScript moderno; si hiciera falta
más, el primer paso barato es agrupar por índice de espacio W (la firma incluye
`espacios`) y permutar solo dentro del grupo.

## Diferencias con la referencia de Python

Ninguna en el resultado numérico: las 147 comprobaciones del corpus lo
confirman. La única diferencia es la representación de la firma, que aquí es un
`Array` de 4 números y en Python una `tuple`.
