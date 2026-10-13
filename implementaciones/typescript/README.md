# TypeScript — port verificado

Puerto fiel de la implementación de referencia de Python. **Verificado: 140/140
comprobaciones** contra el corpus compartido `../pruebas/vectores_w.json`.

> VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
> https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1

## Requisitos

- **Node.js 22.6+** (con `--experimental-strip-types`) o **Node.js 24+**, que
  ejecuta TypeScript directamente sin compilar.
- Sin dependencias: solo `node:crypto` para SHA-256.

## Verificación

```bash
# Desde la raíz del repositorio del plugin
node implementaciones/typescript/prueba.ts
```

Salida esperada:

```
Vectores: 9 puntos, 15 textos, 5 distancias, 3 casos de caché
Cubo: lado 1024, 8 espacios por diagonal

RESULTADO: 140/140 comprobaciones OK
  El port TypeScript coincide con la referencia Python.
```

La prueba compara, con tolerancia `1e-9`, la tokenización, los centroides, las
firmas de puntos y de textos, los índices de espacio, las distancias y las
decisiones de la caché.

## Uso

```ts
import { CacheSemanticaW, FamiliaDiagonalesW, tokenizar } from './vectorw_w.ts'

const familia = new FamiliaDiagonalesW()        // cubo 1024, 8 espacios
const firma = familia.firmaDeTexto('optimizar consultas vectoriales con octree')

console.log(firma.tokens)     // ['optimizar', 'consult', 'vectorial', 'octree']
console.log(firma.firma)      // [0.674…, 1.085…, 1.134…, 1.186…]
console.log(firma.espacios)   // [5, 7, 7, 7]

const cache = new CacheSemanticaW(familia)
cache.guardar('optimizar consultas vectoriales con octree', 'resultado', 4200)

const r = cache.buscar('optimizar consultas vectoriales con octree y podado espacial')
console.log(r.hit, r.kind, r.distancia?.toFixed(4))
// true semantico 0.1010      ← acierto: ~4200 tokens evitados
```

## Compilar a JavaScript

Si tu proyecto necesita JavaScript compilado (por ejemplo, para publicar en
npm), `tsc` funciona sin configuración especial:

```bash
npx tsc implementaciones/typescript/vectorw_w.ts \
  --target es2022 --module nodenext --moduleResolution nodenext --outDir dist
```

No hacen falta tipos de `@types/node` para usar la clase: los tipos de Node
solo aparecen en la importación de `node:crypto`, que es estándar.

## API

Mismos símbolos que la referencia de Python, en estilo TypeScript:

| Símbolo | Descripción |
|---|---|
| `ConfigW` | Constantes (objeto congelado). |
| `tokenizar(texto)` | Raíces significativas. |
| `sinAcentos(texto)`, `raiz(token)` | Pasos de la tokenización, expuestos para depurar. |
| `FamiliaDiagonalesW` | Las 4 diagonales y la aritmética de firmas. |
| `CacheSemanticaW` | Caché consulta→valor con recuperación por similitud. |
| tipos `Punto`, `Firma`, `FirmaW`, `ResultadoCache`, `EstadisticasCache` | Contratos públicos. |

Métodos de `FamiliaDiagonalesW`: `parametroT`, `componentesDe`, `firmaDePunto`,
`espaciosDe`, `puntoW`, `centroide`, `firmaDeTexto`, `distanciaGeometrica`,
`distanciaPermutaciones`, `distancia`.

## Nota sobre el SHA-256

Se usa `createHash('sha256')` de `node:crypto`, que produce exactamente los
mismos bytes que `hashlib.sha256` de Python, así que los puntos W coinciden.
Para un uso en navegador sin dependencias de Node, usa el port de
`../javascript/`, que incorpora su propio SHA-256.
