# Go — port de referencia · **NO COMPILADO NI VERIFICADO**

> ## ⚠️ ESTE PORT NO SE HA COMPILADO NI EJECUTADO
>
> En el equipo donde se escribió **no están instalados `go` ni `gofmt`**, así que
> el código **nunca** se ha compilado, formateado, pasado por `go vet` ni
> ejecutado. No existe ninguna medida de su comportamiento en ejecución. Está
> escrito para ser autocontenido y lógicamente correcto, pero **la única
> implementación verificada es la de Python**:
> [`implementaciones/python/vectorw_w.py`](../python/vectorw_w.py).
>
> Si algo de este port no coincide con la referencia, **la referencia tiene
> razón**.

> VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
> https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1

## Contenido

| Archivo | Qué es |
|---|---|
| `go.mod` | Módulo `github.com/PePiuoX/vectorw-dsh-plugin/implementaciones/go`, `go 1.22`. |
| `vectorw/vectorw.go` | El port completo (paquete `vectorw`). |
| `vectorw/vectorw_test.go` | Pruebas contra el corpus compartido `pruebas/vectores_w.json`. |

Sin dependencias: solo biblioteca estándar. **No** se usa
`golang.org/x/text/unicode/norm`.

## Cómo compilar y probar

```bash
cd implementaciones/go
go build ./...
go vet ./...
gofmt -l .            # no debería listar nada
go test -v ./...      # lee ../../pruebas/vectores_w.json
```

La ruta del corpus es relativa y depende del directorio de trabajo: `go test`
ejecuta el paquete `vectorw` con `implementaciones/go/vectorw/` como directorio
actual, y desde ahí `../../pruebas/vectores_w.json` resuelve al corpus
compartido. Si se ejecuta desde otro sitio, la lectura falla con un mensaje que
lo explica.

## Verificar la referencia (fuente de verdad)

```bash
# Desde la raíz del repositorio del plugin
python pruebas/verificar_equivalencia.py    # geometría contra el núcleo original
python pruebas/generar_vectores.py          # regenera pruebas/vectores_w.json
```

## API

| Símbolo | Descripción |
|---|---|
| `ConfigW`, `LadoCubo`, `NEspacios`, `UmbralSimilitud`, `MaxEntradas`, `InvariantePermutaciones` | Constantes del espacio W (1024, 8, 0.15, 2000, `true`). |
| `Tokenizar(texto string) []string` | Raíces significativas, sin duplicados. |
| `Raiz(token string) string`, `PalabrasVacias`, `Sufijos` | Pasos de la tokenización, expuestos para depurar. |
| `Vec3`, `FirmaW` | Punto 3D y firma W 4D con su procedencia. |
| `Nuevo(lado float64, nEspacios int) *FamiliaDiagonalesW` | Las 4 diagonales y la aritmética de firmas. |
| `PuntoW`, `Centroide` | Punto SHA-256 de un token y centroide de un texto. |
| `ParametroT`, `ComponentesDe`, `FirmaDePunto`, `EspaciosDe`, `FirmaDeTexto` | Proyección, firma y clasificación en espacios. |
| `DistanciaGeometrica`, `DistanciaPermutaciones`, `Distancia` | Las tres distancias. |
| `NuevaCache(opciones ...CacheOpcion) *CacheSemanticaW` | Caché semántica (umbral, entradas máximas, TTL, familia). |
| `Buscar`, `Guardar`, `Estadisticas`, `Limpiar`, `Entradas` | Operaciones de la caché. |

```go
familia := vectorw.Nuevo(vectorw.LadoCubo, vectorw.NEspacios)
f := familia.FirmaDeTexto("optimizar consultas vectoriales con octree")
// f.Tokens      -> [optimizar consult vectorial octree]
// f.Firma       -> [0.674…, 1.085…, 1.134…, 1.186…]
// f.Espacios    -> [5 7 7 7]

cache := vectorw.NuevaCache(vectorw.CacheOpcionFamilia(familia))
cache.Guardar("optimizar consultas vectoriales con octree", "resultado", 4200, nil)
r := cache.Buscar("optimizar consultas vectoriales con octree y podado espacial")
// r.Hit == true, r.Kind == "semantico", r.Distancia ≈ 0.100977
```

## Decisiones de port (judgement calls)

1. **NFD sin dependencias.** No se usa `golang.org/x/text/unicode/norm`. La
   descomposición de diacríticos latinos se hace con una tabla explícita
   (`descomposicionLatina`) que cubre Latin-1 Supplement y Latin Extended-A
   (á é í ó ú ü ñ, à è ì ò ù, â ê î ô û, ä ë ï ö ü ÿ, ã õ, ç, æ, œ, …). Tras la
   descomposición se descartan las runas de la categoría `Mn`, igual que
   `_sin_acentos` en Python.
   La tabla **no** cubre todo Unicode (no hay plegado completo de Hangul, ni
   katakana con sonorización, ni descomposiciones de compatibilidad completas):
   solo se comporta igual que la referencia sobre texto latino, que es el único
   que el algoritmo produce. Si necesitas cobertura total, añade
   `golang.org/x/text/unicode/norm` y sustituye `descomponerLatin` por
   `norm.NFD.String(strings.ToLower(texto))` más el filtro de `Mn`.
2. **Extracción de palabras.** La referencia usa `re.compile(r"[\w...]+")`. En
   Go se recorre runa a runa aceptando `unicode.IsLetter`, `unicode.IsNumber` o
   `_`, lo que reproduce el `\w` de Python (que incluye números no decimales
   como el superíndice `²`). Las marcas combinantes quedan fuera en ambos
   casos.
3. **Minúsculas.** Se usa `strings.ToLower`, que coincide con `str.lower()` de
   Python para texto latino. La única divergencia conocida es `'İ'` (U+0130),
   que Python convierte en `"i̇"` (i + punto) y Go deja igual.
4. **Clave de la caché.** Python indexa por la tupla de 4 flotantes, que es
   hashable; Go no admite flotantes como clave. Se indexa por la **consulta
   normalizada**, que además evita cualquier colisión por redondeo: dos
   consultas que se normalizan a la misma cadena tienen exactamente la misma
   firma. El comportamiento observable (acierto exacto, FIFO/LRU, métricas) es
   el de la referencia.
5. **Constructor de la caché.** Go no tiene valores por defecto, así que se usan
   funciones de opción (`CacheOpcionUmbral`, `CacheOpcionMaxEntradas`,
   `CacheOpcionTTL`, `CacheOpcionFamilia`); sin opciones se usan las constantes
   de `ConfigW`.
6. **Cambio en el orden de guardado** (línea de `Guardar`): la referencia
   sobreescribe la entrada de la misma clave y luego aplica la evacuación. Aquí
   se elimina primero la entrada repetida y después se evacúa la más antigua
   mientras no quepa; el resultado observable es el mismo y el límite
   `max_entradas` sigue aplicándose.
7. **Corrección defensiva ausente en Python:** `Nuevo` sustituye un lado no
   positivo o `NaN` por 1024 y fuerza `nEspacios >= 1`. La referencia solo hace
   lo segundo.

## Qué se comprobó y qué no

**No comprobado:** absolutamente nada del código Go (no se compiló ni ejecutó).

**Comprobado fuera del compilador** — las partes traducibles a Python se
reprodujeron paso a paso en un script auxiliar y se compararon con la
referencia:

* la aritmética de `parametro_t`, `componentes_de`, `firma_de_punto` y
  `espacios_de` coincide con los 9 puntos de `vectores_w.json`;
* la tokenización coincide con las 15 entradas de `tokenizacion`;
* los centroides calculados con el SHA-256 **escrito a mano** (el mismo
  algoritmo del port de Rust) coinciden con los 15 `coords` del corpus;
* `raiz()` coincide con `_raiz` en 17 sufijos/casos límite.

El port de Go usa `crypto/sha256`, que la biblioteca estándar garantiza, así que
esa parte no necesita la comprobación anterior; se hizo porque el mismo
algoritmo está escrito a mano en el port de Rust.

## Diferencias con la referencia de Python

Ninguna en el resultado numérico **por diseño**. Las diferencias son de
representación: la firma es `[4]float64` en lugar de una tupla, `Tokenizar`
devuelve `nil` (no `[]`) cuando no hay tokens, y `Buscar`/`Guardar` devuelven
estructuras en lugar de `dict`. Las pruebas comparan los valores, no la forma.
