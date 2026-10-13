# VectorW — port de referencia en Rust · **NO COMPILADO NI VERIFICADO**

> ## ⚠️ ESTE CRATE NO SE HA COMPILADO NI EJECUTADO
>
> En el equipo donde se escribió **no están instalados `rustc` ni `cargo`**, así
> que el código **nunca** se ha compilado, pasado por `cargo fmt`, `cargo clippy`
> ni ejecutado. No existe ninguna medida de su comportamiento en ejecución. Está
> escrito para ser autocontenido y lógicamente correcto, pero **la única
> implementación verificada es la de Python**:
> [`implementaciones/python/vectorw_w.py`](../python/vectorw_w.py).
>
> Si algo de este crate no coincide con la referencia, **la referencia tiene
> razón**.

> VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
> https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1

## Contenido

| Archivo | Qué es |
|---|---|
| `Cargo.toml` | Crate `vectorw`, edición 2021, **`[dependencies]` vacío**. |
| `src/lib.rs` | El port completo, incluido SHA-256 a mano y las pruebas. |

**Cero dependencias.** No se usa `sha2` ni `unicode-normalization` ni
`serde_json`.

## Cómo compilar y probar

```bash
cd implementaciones/rust
cargo build
cargo test              # ejecuta el módulo #[cfg(test)] de src/lib.rs
cargo fmt -- --check
cargo clippy -- -D warnings
```

## Verificar la referencia (fuente de verdad)

```bash
# Desde la raíz del repositorio del plugin
python pruebas/verificar_equivalencia.py    # geometría contra el núcleo original
python pruebas/generar_vectores.py          # regenera pruebas/vectores_w.json
```

El corpus completo y autorizado es `../pruebas/vectores_w.json` (15
tokenizaciones, 9 puntos, 15 textos, 5 pares de distancias y 3 decisiones de
caché), generado por la referencia de Python.

## API

| Símbolo | Descripción |
|---|---|
| `config_w` (`LADO_CUBO`, `N_ESPACIOS`, `UMBRAL_SIMILITUD`, `MAX_ENTRADAS`, `TTL_SEGUNDOS`, `INVARIANTE_PERMUTACIONES`) | Constantes del espacio W, reexportadas también en la raíz del crate. |
| `tokenizar(texto: &str) -> Vec<String>` | Raíces significativas, sin duplicados. |
| `raiz(token)`, `descomponer_latin(texto)`, `PALABRAS_VACIAS`, `SUFIJOS` | Pasos de la tokenización, expuestos para depurar. |
| `Vec3`, `FirmaW` | Punto 3D y firma W 4D con su procedencia. |
| `FamiliaDiagonalesW::nuevo(lado, n_espacios)`, `Default` | Las 4 diagonales y la aritmética de firmas. |
| `punto_w`, `centroide` | Punto SHA-256 de un token y centroide de un texto. |
| `parametro_t`, `componentes_de`, `firma_de_punto`, `espacios_de`, `firma_de_texto` | Proyección, firma y clasificación en espacios. |
| `distancia_geometrica`, `distancia_permutaciones`, `distancia` | Las tres distancias. |
| `CacheSemanticaW::nuevo(familia, umbral, max_entradas, ttl)`, `Default` | Caché semántica. |
| `buscar`, `guardar`, `estadisticas`, `limpiar`, `claves_en_orden` | Operaciones de la caché. |
| `sha256(mensaje: &[u8]) -> [u8; 32]` | SHA-256 propio, sin dependencias. |

```rust
use vectorw::{FamiliaDiagonalesW, CacheSemanticaW, LADO_CUBO, N_ESPACIOS,
              UMBRAL_SIMILITUD, MAX_ENTRADAS};

let familia = FamiliaDiagonalesW::nuevo(LADO_CUBO, N_ESPACIOS);
let f = familia.firma_de_texto("optimizar consultas vectoriales con octree");
// f.tokens   -> ["optimizar", "consult", "vectorial", "octree"]
// f.firma    -> [0.674…, 1.085…, 1.134…, 1.186…]
// f.espacios -> [5, 7, 7, 7]

let mut cache = CacheSemanticaW::nuevo(familia, UMBRAL_SIMILITUD, MAX_ENTRADAS, 0.0);
cache.guardar("optimizar consultas vectoriales con octree", "resultado", 4200,
              std::collections::HashMap::new());
let r = cache.buscar("optimizar consultas vectoriales con octree y podado espacial");
// r.hit == true, r.kind == "semantico", r.distancia == Some(≈0.100977)
```

## Decisiones de port (judgement calls)

1. **SHA-256 escrito a mano.** Está completamente especificado en FIPS 180-4 y
   son ~70 líneas, así que se implementa en `src/lib.rs` (`sha256`,
   `sha256_compresion`, `K_SHA256`, `H0_SHA256`) en lugar de añadir el crate
   `sha2`. Se comprueba contra los vectores oficiales en la prueba
   `sha256_vectores_conocidos` (cadena vacía, `"abc"`, el mensaje de 56 bytes y
   un mensaje de 64 bytes que ejercita el segundo bloque de relleno).
   **Riesgo:** un error tipográfico en las 64 constantes de ronda o en las
   rotaciones no lo detecta el compilador; la prueba citada es la red de
   seguridad, y hay que ejecutarla.
2. **NFD sin dependencias.** La descomposición de diacríticos latinos usa las
   tablas `DESCOMPOSICION_LATINA` (34 entradas de Latin-1 Supplement y Latin
   Extended-A: á é í ó ú ü ñ, à è ì ò ù, â ê î ô û, ä ë ï ö ü ÿ, ã õ, ç, …) y
   `DESCOMPOSICION_COMPUESTA` (æ, Æ, œ, Œ, ß). Tras descomponer se descartan las
   marcas combinantes (`es_combinante`), igual que `_sin_acentos` en Python.
   **Cobertura parcial:** no hay plegado completo de Hangul ni todas las
   descomposiciones de compatibilidad; solo se garantiza la equivalencia sobre
   texto latino.
3. **Clasificación de "caracter de palabra".** Se usa
   `c == '_' || c.is_alphanumeric()`, que reproduce el `\w` de Python (letras y
   números de cualquier script, incluidos superíndices y fracciones como
   caracteres numéricos), y deja fuera las marcas combinantes. Al principio se
   intentó una tabla de rangos propia, pero era **menos fiel** que la tabla
   Unicode de la biblioteca estándar; se descartó.
4. **Minúsculas.** `str::to_lowercase`, que coincide con `str.lower()` de Python
   para texto latino (divergencia conocida: `'İ'` U+0130).
5. **Clave de la caché.** Rust tampoco permite usar flotantes como clave de un
   `HashMap`, así que las entradas se indexan por la **consulta normalizada** y
   un `Vec<String>` mantiene el orden de inserción para reproducir el
   `move_to_end`/`popitem(last=False)` de `OrderedDict`.
6. **`parametro_t(indice: usize, …)`.** En Rust el índice no puede ser negativo,
   así que el `f64::NAN` que la referencia no contempla solo se devuelve para
   `indice > 3`.
7. **Corrección defensiva ausente en Python:** `nuevo` sustituye un lado no
   positivo o `NaN` por 1024 y fuerza `n_espacios >= 1`.
8. **Tipos con cadena propia.** `EntradaCache::valor` es `String` y `metadata`
   es `HashMap<String, String>` (la referencia usa `object` sin restringir). Un
   port de producción querría genéricos o `serde_json::Value`, pero eso obliga a
   fijar una dependencia que aquí se ha evitado a propósito.

## Qué se comprobó y qué no

**No comprobado:** absolutamente nada del código Rust. No se ha compilado ni
ejecutado; ni siquiera se ha verificado que los tipos cuadren.

**Comprobado fuera del compilador** — como no hay `rustc`, las partes
traducibles a Python se reprodujeron paso a paso (mismo orden de operaciones,
misma aritmética modular, mismo troceado big-endian) y se compararon con la
referencia:

* el SHA-256 escrito a mano coincide con `hashlib.sha256` en 12 mensajes,
  incluidos los tamaños 55, 56, 63, 64, 65, 119 y 120 bytes (los que ejercitan
  el relleno y el segundo bloque);
* la aritmética de `parametro_t`, `componentes_de`, `firma_de_punto` y
  `espacios_de` coincide con los 9 puntos del corpus;
* la tokenización coincide con las 15 entradas de `tokenizacion`;
* los centroides calculados con ese SHA-256 coinciden con los 15 `coords` del
  corpus;
* `raiz()` coincide con `_raiz` en 17 sufijos y casos límite;
* los delimitadores de `src/lib.rs` están balanceados.

Todo eso valida la **lógica**, no el código Rust compilado: queda pendiente
ejecutar `cargo test`.

## Pruebas incluidas

El módulo `#[cfg(test)] mod pruebas` incrusta un subconjunto representativo del
corpus como constantes literales (no depende de ningún crate de JSON):

* `configuracion_compartida` — constantes y geometría;
* `tokenizacion_del_corpus` — 6 entradas, incluidos `"cachés y caches"`,
  `"áéíóú ñ"`, `""` y `"a de la el"`;
* `puntos_del_corpus` — 3 puntos con componentes, firma y espacios;
* `textos_del_corpus` — 3 textos con tokens, centroide, componentes, firma y
  espacios;
* `distancias_del_corpus` — 2 pares (con y sin solapamiento);
* `distancia_sin_vocabulario_compartido` — la regla de selección;
* `cache_del_corpus` — la secuencia completa de la caché y sus estadísticas;
* `cache_exacta_y_evacuacion_fifo` — normalización y política de evacuación;
* `sha256_vectores_conocidos`, `punto_w_como_la_referencia`,
  `detalles_de_raiz`, `descomposicion_latina` — unidades del algoritmo a mano.

### Cómo extender las pruebas al corpus completo

Con un toolchain disponible, la forma barata es añadir `serde_json` como
dependencia **de desarrollo** (ya está comentada en `Cargo.toml`), declarar el
mismo `struct` que usa la prueba de Go (`implementaciones/go/vectorw/vectorw_test.go`)
y recorrer las cinco secciones del JSON. Alternativa sin dependencias: generar
desde Python un archivo `.rs` con las constantes del corpus completo y
`include!`-lo desde las pruebas.
