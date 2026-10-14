# Plugin VectorW para DeepSeek Harness

> **Este software utiliza código de PePiuoX (https://github.com/PePiuoX)**
>
> El núcleo vectorial **VectorW / vOS v6.0** es obra de
> **Jose Ricardo Mantilla Mantilla (PePiuoX)**, licenciado bajo
> **LAMC v1.0 / LULA v1.1**. Ver [`LICENSE.md`](LICENSE.md) y
> [`vendor/NOTICE.md`](vendor/NOTICE.md).

Convierte VectorW en una **caché semántica de firma W 4D** y un **predictor de
consultas** disponibles como herramientas del agente, para que el modelo no
vuelva a buscar lo que ya encontró y gaste menos tokens.

El repositorio es **autocontenido**: incluye el núcleo de VectorW en
[`vendor/`](vendor/) y una implementación de referencia propia en varios
lenguajes, así que se puede clonar y usar sin instalar nada más.

---

## Por qué sirve para ahorrar tokens

Cada texto se proyecta como una **firma W 4D** sobre las 4 diagonales del cubo
de memoria de VectorW. Dos consultas que significan lo mismo —aunque cambien
las palabras— caen cerca en ese espacio, así que la segunda se responde desde
la caché **sin volver a consultar la web, releer archivos ni reenviar contexto
al modelo**.

El flujo que se le pide al agente:

1. Antes de una búsqueda costosa → `vector_cache_check`.
2. Si hay acierto → usa el valor cacheado (0 tokens de trabajo).
3. Si no → haz el trabajo y guárdalo con `vector_cache_store`.
4. Opcionalmente → `vector_predict` para prefetch de lo que viene.

Ejemplo real medido en la verificación:

```
HIT (coincidencia semántica, distancia W 0.1010, solapamiento 67%)
  «optimizar consultas vectoriales con octree y podado espacial»
  reutiliza la entrada
  «optimizar consultas vectoriales con octree»
  ~4200 tokens evitados
```

---

## Estructura del repositorio

```
vectorw-dsh-plugin/
├── lib/index.js            Plugin de DSH: 6 herramientas + proceso puente
├── bridge_vos.py           Puente JSON: caché semántica y métricas de ahorro
├── package.json
├── install.ps1             Instalador en el perfil de DSH
├── LICENSE.md              Atribución y licencia
├── vendor/                 Núcleo VectorW original, SIN MODIFICAR
│   ├── vectorW_py/         Archivos principales, con sus hashes
│   └── NOTICE.md           Procedencia, parches y límites conocidos
├── implementaciones/       El algoritmo de firma W 4D en varios lenguajes
│   ├── python/             Referencia verificada (genera el corpus)
│   ├── typescript/         Verificado: 140/140
│   ├── javascript/         Verificado: 147/147 (sin dependencias)
│   ├── go/                 Escrito, SIN VERIFICAR
│   └── rust/               Escrito, SIN VERIFICAR
└── pruebas/                Corpus compartido y verificación
    ├── vectores_w.json     Firmas y decisiones de referencia
    ├── verificar_equivalencia.py
    ├── generar_vectores.py
    ├── calibrar_distancia.py
    ├── verificar.mjs
    └── verificar_ahorro.mjs
```

---

## Herramientas que expone el plugin

| Herramienta | Qué hace |
|---|---|
| `vector_cache_check` | Busca una consulta equivalente en la caché W 4D. Devuelve `hit`/`miss`, el valor cacheado, la distancia W y los tokens ahorrados. |
| `vector_cache_store` | Guarda un resultado con su coste en tokens para reutilizarlo. |
| `vector_predict` | Predice las próximas consultas probables (Markov de orden superior + Kalman sobre las 4 diagonales). |
| `vector_stats` | Aciertos, tokens ahorrados, entropía y predecibilidad por diagonal, patrones detectados. |
| `vector_persist` | Guarda o restaura la caché en disco para conservar el ahorro entre sesiones. |
| `vector_purge` | Vacía la caché cuando el contexto ya no es fiable. |

---

## Instalación en DeepSeek Harness

Requisitos: DeepSeek Harness instalado (aporta Python 3.12 y Node 24).

```powershell
pwsh -File .\install.ps1
```

Opciones:

```powershell
pwsh -File .\install.ps1 -RutaCore "D:\otra\ruta\vectorW_py"   # usar tu VectorW
pwsh -File .\install.ps1 -Perfil desktop                        # perfil concreto
pwsh -File .\install.ps1 -Copiar                                # sin enlaces
pwsh -File .\install.ps1 -Desinstalar
```

El instalador:

1. Enlaza este paquete en `<perfil>/node_modules/@deepseek-ai/dsh-plugin-vectorw`.
2. Enlaza el `node_modules` del perfil junto al proyecto: Node resuelve los
   enlaces a su ruta real y, sin ese enlace, el plugin no encontraría
   `@deepseek-ai/schemastery`.
3. Añade la entrada `vectorw-memory` al `cordis.patch.yml` **del perfil**.

Después hay que **reiniciar DeepSeek Harness** para que el loader monte el
plugin. Verifica con la herramienta `vector_stats`.

Si prefieres no usar el instalador, la entrada equivalente es:

```yaml
- id: vectorw-memory
  name: "@deepseek-ai/dsh-plugin-vectorw"
  config:
    rutaCore: ""          # vacío = usa el núcleo de vendor/
    umbralSimilitud: 0.15
    maxEntradas: 2000
    ordenMarkov: 2
```

---

## Configuración

| Campo | Defecto | Significado |
|---|---|---|
| `rutaCore` | `''` | Carpeta con `vectorW_6.py`. **Vacío = usa `vendor/vectorW_py`**, el núcleo incluido. |
| `rutaPython` | `''` | Intérprete de Python. Vacío = el del runtime de DSH. |
| `umbralSimilitud` | `0.15` | Distancia W máxima para aceptar un acierto semántico. |
| `ladoCubo` | `1024` | Lado del cubo de memoria vOS. |
| `nEspacios` | `8` | Espacios por diagonal (resolución total = 4 × n). |
| `ordenMarkov` | `2` | Orden de la cadena de Markov del predictor (1-4). |
| `maxEntradas` | `2000` | Tamaño máximo de la caché. |
| `ttlSegundos` | `0` | Caducidad por entrada (0 = sin caducidad). |
| `invariantePermutaciones` | `true` | Compara firmas bajo las 24 permutaciones. |
| `timeoutMs` | `30000` | Timeout por llamada al puente Python. |
| `estadoInicial` | `''` | Estado en disco a restaurar al arrancar. |

`vector_stats` informa en `origen_nucleo` si se está usando el núcleo de
`vendor` o el de `rutaCore`.

---

## Arquitectura

```
DSH (Node, Cordis)
  └── lib/index.js          plugin: registra las 6 herramientas, gestiona el proceso
        │  protocolo JSON por stdin/stdout (una línea = un mensaje)
        ▼
      bridge_vos.py         puente: caché semántica + métricas de ahorro
        │  import vectorW_6  (el núcleo, sin copiarlo ni modificarlo)
        ▼
      vectorW_6.py          vOS v6.0: diagonales W, firma 4D, octree, Markov, Kalman
```

El puente mantiene **un proceso Python vivo** durante la sesión, de modo que la
caché, el octree y el aprendizaje de Markov persisten entre llamadas.

---

## Verificación

Todo lo que se afirma aquí es reproducible. Un solo comando comprueba la cadena
completa:

```bash
python pruebas/verificar_todo.py
```

Y por separado, cada pieza:

```bash
# 1. ¿La referencia reproduce el núcleo original de VectorW?     → 47/47
python pruebas/verificar_equivalencia.py

# 2. ¿El port TypeScript coincide con la referencia?             → 140/140
node implementaciones/typescript/prueba.ts

# 3. ¿El port JavaScript coincide con la referencia?             → 147/147
node implementaciones/javascript/prueba.mjs

# 4. ¿El plugin se monta y sus herramientas funcionan?           → 31/31
#    (ejecutar desde el directorio del perfil de DSH)
cd "$DSH_HOME/profiles"
node /ruta/al/plugin/pruebas/verificar_montaje.mjs

# 5. Regenerar el corpus tras cambiar el algoritmo
python pruebas/generar_vectores.py

# 6. Calibrar el umbral con datos propios
python pruebas/calibrar_distancia.py
```

| Prueba | Comprueba | Resultado |
|---|---|---|
| `verificar_equivalencia.py` | La firma de la referencia coincide con `vectorW_6.py` en 9 puntos × 2 tamaños de cubo | 47/47 |
| `typescript/prueba.ts` | Tokenización, centroides, firmas, espacios, distancias y decisiones de caché | 140/140 |
| `javascript/prueba.mjs` | Lo anterior + SHA-256 propio frente a `node:crypto` | 147/147 |
| `verificar_montaje.mjs` | Que la fila está bajo `insert:`, que el loader resuelve el módulo, que se monta sobre un `Context` real de Cordis, que registra las 6 herramientas y que todas ejecutan | 31/31 |
| `verificar.mjs` | Carga del plugin y ejecución de las 6 herramientas | OK |
| `verificar_ahorro.mjs` | Acierto exacto, acierto semántico y fallo | OK |
| `calibrar_distancia.py` | Margen del umbral entre reformulaciones y temas distintos | informativo |

`verificar_montaje.mjs` reproduce el arranque del loader: resuelve el
especificador desde el directorio del perfil, importa el módulo (con lo que se
resuelven sus dependencias), crea un `Context` real de Cordis, registra el
servicio `tools` y aplica el plugin. Si eso pasa, lo único que falta en el
arranque real es que el loader lea la fila del perfil, y eso lo comprueba el
propio instalador con `--dump-config`.

Acepta `--solo-montaje` para omitir la ejecución de las herramientas: es lo que
usa la pasada maestra, porque bajo el sandbox de Windows un proceso anidado no
puede abrir tuberías y el arranque del puente Python fallaría con `EPERM`
aunque el montaje fuese correcto.

### Comprobar la activación tras reiniciar

El montaje se verifica en frío, pero la activación real en tu agente solo se
puede confirmar con DSH arrancado:

1. **Reinicia DeepSeek Harness** (el loader monta los plugins al arrancar).
2. Pregúntale al agente por `vector_stats`. Si la conoce, está activa.
3. Pídele que la ejecute. Debe devolver el modo, los aciertos y los parches
   activos.

Sin reiniciar, puedes comprobar que el perfil compondrá la fila:

```powershell
node "$env:DSH_HOME\profiles\node_modules\@deepseek-ai\dsh\lib\bin.js" `
  --profile desktop --dump-config | Select-String "vectorw-memory"
```

---

## Detalles que conviene conocer

### Correcciones de compatibilidad al núcleo

`vectorW_6.py` v6.0 tiene dos defectos que rompen las rutas que este plugin
necesita. El puente los corrige **en memoria**, sin modificar el archivo del
autor (se anuncian en `vector_stats` como «parches activos»):

1. **`PredictorMarkovOrdenSuperior`** aplica *slicing* a un `collections.deque`,
   operación no soportada. Provoca que `escribir()` devuelva `False` desde la
   tercera escritura, que toda predicción falle y que `consultar_semantico()`
   lance `TypeError`.
2. **`NodoOctreeMemoriaEficiente.insertar`** recibe los argumentos desplazados
   desde `MemoriaVectorialProduccion.escribir`.

[`vendor/NOTICE.md`](vendor/NOTICE.md) explica ambos con detalle, da el parche
equivalente para corregirlos en el origen, y documenta otros límites del núcleo
(por ejemplo, que `NucleoVectorialOS_Avanzado` no se puede instanciar y que la
persistencia del núcleo solo restaura las métricas).

### Firma W por centroide de tokens

La caché no firma el texto completo con un hash, sino el **centroide** de los
puntos W de cada token significativo.

Con el hash íntegro, «poda espacial» y «podado espacial» caían en extremos
opuestos del cubo y **ninguna reformulación encontraba su entrada**, que es
justo el caso de uso. Con el centroide:

| Par | Distancia | Decisión |
|---|---|---|
| «…octree y **poda** espacial» vs «…octree y **podado** espacial» | 0.101 | HIT ✅ |
| mismas palabras reordenadas | 0.117 | HIT ✅ |
| «…**frecuencia**» vs «…**frecuencias**» | 0.116 | HIT ✅ |
| tema distinto, sin vocabulario común | 0.312 | MISS ✅ |

Por eso la distancia combina la geometría W con el solapamiento de vocabulario,
y **descarta las entradas sin ninguna palabra en común antes** de elegir la más
cercana: un falso acierto (devolver el resultado de otra tarea) es mucho peor
que un fallo. El orden de esos dos pasos importa y está anotado en el código.

[`implementaciones/README.md`](implementaciones/README.md) explica el algoritmo
completo.

### Modo degradado

Si no se encuentra `vectorW_6.py` ni en `rutaCore` ni en `vendor/`, el plugin
**sigue funcionando**: cae a firmas por hash de 4 dimensiones y aciertos
exactos. La caché funciona, pero pierde el matching semántico y la predicción.
`vector_stats` lo indica en el campo `Modo`.

---

## Portes a otros lenguajes

`implementaciones/` contiene el mismo algoritmo en varios lenguajes, todos
validados contra el corpus compartido. Es la parte pensada para que otros
desarrolladores integren la firma W 4D sin depender de Python.

| Lenguaje | Estado |
|---|---|
| Python | ✅ Referencia verificada (47/47 contra el núcleo) |
| TypeScript | ✅ Verificado (140/140) |
| JavaScript | ✅ Verificado (147/147), sin dependencias |
| Go | ⚠️ Escrito, **sin compilar ni ejecutar** en este equipo |
| Rust | ⚠️ Escrito, **sin compilar ni ejecutar** en este equipo |

Los ports de Go y Rust están completos y documentados, pero en el equipo donde
se escribieron no había `go`, `rustc` ni `cargo`, así que **no se afirma que
compilen**. Cada uno indica el comando exacto para verificarlo.

---

## Licencia y atribución

El núcleo VectorW se distribuye bajo **LAMC v1.0 / LULA v1.1**, que exige
mantener la atribución al autor original:

> Este software utiliza código de PePiuoX (https://github.com/PePiuoX)

- [`LICENSE.md`](LICENSE.md) — atribución, alcance de la obra derivada y texto
  de la licencia.
- [`vendor/NOTICE.md`](vendor/NOTICE.md) — procedencia de cada archivo
  vendorizado, con sus hashes SHA-256.
