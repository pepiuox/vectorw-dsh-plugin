# Plugin VectorW para DeepSeek Harness

> **Este software utiliza código de PePiuoX (https://github.com/PePiuoX)**
>
> El núcleo vectorial **VectorW / vOS v6.0** es obra de
> **Jose Ricardo Mantilla Mantilla (PePiuoX)**, licenciado bajo
> **LAMC v1.0 / LULA v1.1**. Ver [`LICENSE.md`](LICENSE.md) y
> [`vendor/NOTICE.md`](vendor/NOTICE.md).

Convierte VectorW en una **caché semántica de firma W 4D**, un **predictor de
consultas** y una **memoria de procesos y lecciones en SQLite** disponibles como
herramientas del agente, para que el modelo no vuelva a buscar lo que ya
encontró, no repita una tarea ya resuelta y gaste menos tokens.

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
├── lib/index.js            Plugin de DSH: 9 herramientas + proceso puente
├── bridge_vos.py           Puente JSON: caché semántica, memoria y métricas
├── memoria_vectorw.py      Memoria SQLite: procesos, lecciones, recursos, eventos
├── package.json
├── cordis.patch.yml        Patch del bundle: declara la fila vectorw-memory
├── verificar-plugin.ps1    Diagnóstico de instalación y compatibilidad
├── install.ps1             Obsoleto a propósito: solo avisa del camino correcto
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
| `vector_proceso_buscar` | Recupera de SQLite los procesos ya resueltos y las lecciones equivalentes, con sus pasos y su resultado, antes de repetir trabajo. |
| `vector_proceso_guardar` | Guarda un proceso resuelto (pasos + resultado) y una lección opcional, para que otra sesión o agente lo reutilice. |
| `vector_recurso_buscar` | Busca semánticamente en el catálogo indexado de skills, agentes, documentos y herramientas del preset. |

---

## Instalación en DeepSeek Harness

Requisitos: DeepSeek Harness instalado (aporta Python 3.12 y Node 24).

El plugin se instala como **bundle** con `plugin_manager` (acción
`install_bundle`). Es el único camino soportado: DSH añade el paquete al
`package.json` del perfil, ejecuta pnpm y aplica el patch del bundle como una
capa de primera clase, dejando la fila **habilitada** y gestionable desde
*Ajustes → Plugins*.

Dentro de DeepSeek Harness, pide al agente:

> instala el bundle de "C:\ruta\a\vectorw-dsh-plugin"

Después, comprueba el estado con:

```powershell
pwsh -File .\verificar-plugin.ps1
```

### Por qué NO se instala a mano

Escribir una fila en el `cordis.patch.yml` del perfil **no funciona** y fue el
fallo histórico de este plugin. Deja dos problemas:

1. **La fila aparece pero no se puede habilitar**: el loader la crea y DSH la
   mantiene deshabilitada por el control de versión (ver más abajo).
2. **Node no resuelve los imports** del plugin cuando vive fuera del perfil.

`install.ps1` se conserva solo como aviso de obsolescencia; no escribe nada.

### Requisito de versión (causa del bloqueo)

DSH **rechaza activar** un plugin cuyas `peerDependencies` no admiten el
runtime en ejecución. Este plugin declara:

```json
"peerDependencies": {
  "@deepseek-ai/cordis": "^4.0.1",
  "@deepseek-ai/dsh-tools": "^0.2.1-rc.2"
}
```

Si actualizas DSH y el plugin aparece como *no habilitable*, actualiza ese
rango. Fue exactamente la causa de que el plugin no se pudiera activar: el
runtime era `0.2.1-rc.2` y el rango declaraba `^0.1.1-rc.2`.

`verificar-plugin.ps1` reporta el runtime detectado y el rango declarado para
que el desajuste salte a la vista.

### Configuración de la fila

El patch del bundle ([`cordis.patch.yml`](cordis.patch.yml)) declara la fila:

```yaml
- insert:
    - id: vectorw-memory
      name: '@deepseek-ai/dsh-plugin-vectorw'
      config:
        rutaCore: ''          # vacío = usa el núcleo de vendor/
        umbralSimilitud: 0.15
        maxEntradas: 2000
        ordenMarkov: 2
```

Cámbiala desde *Ajustes → Plugins* o en ese archivo del repo, no en el perfil.

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
| `minTokensComunes` | `2` | Tokens compartidos mínimos para aceptar un acierto semántico. Evita falsos positivos con una sola palabra en común. |
| `minSolapamiento` | `0.0` | Jaccard mínimo adicional entre consulta y entrada. Súbelo (p. ej. `0.34`) para exigir más evidencia léxica. |
| `invariantePermutaciones` | `true` | Compara firmas bajo las 24 permutaciones. |
| `timeoutMs` | `30000` | Timeout por llamada al puente Python. |
| `estadoInicial` | `''` | Estado en disco a restaurar al arrancar. |
| `rutaMemoria` | `''` | Base SQLite de memoria. Vacío = `<paquete>/memoria/vectorw_memoria.db`. Compartirla entre perfil y presets reutiliza el aprendizaje entre sesiones. |
| `rutaSkills` | `''` | Carpeta de skills del preset (`<ruta>/*/SKILL.md`) a indexar como recursos buscables. |
| `rutaDocumentos` | `''` | Carpeta de documentos Markdown a indexar como recursos buscables. |
| `umbralProcesos` | `0.22` | Distancia W máxima para aceptar un proceso ya resuelto como equivalente. |
| `umbralRecursos` | `0.35` | Distancia W máxima para aceptar una skill/recurso como relevante. |
| `presupuestoCaracteres` | `6000` | Caracteres máximos del valor que se guarda; por encima se guarda un resumen recortado. |
| `maxTokensRespuesta` | `1500` | Tokens máximos que un acierto devuelve al contexto (≈4 car./token). |
| `usarIndiceEspacios` | `true` | Añade el índice de celdas W al índice invertido de tokens. |
| `reentrenarAlRestaurar` | `true` | Warm-start real: reinyecta las coordenadas restauradas en el predictor/octree. |
| `persistirAlCerrar` | `false` | Persiste la caché al descargar el plugin. |

`vector_stats` informa en `origen_nucleo` si se está usando el núcleo de
`vendor` o el de `rutaCore`.

---

## Arquitectura

```
DSH (Node, Cordis)
  └── lib/index.js          plugin: registra las 9 herramientas, gestiona el proceso
        │  protocolo JSON por stdin/stdout (una línea = un mensaje)
        ▼
      bridge_vos.py         puente: caché semántica + memoria + métricas de ahorro
        │  ├─ import vectorW_6  (el núcleo, sin copiarlo ni modificarlo)
        │  └─ import memoria_vectorw  (SQLite: procesos/lecciones/recursos/eventos)
        ▼
      vectorW_6.py          vOS v6.0: diagonales W, firma 4D, octree, Markov, Kalman
```

El puente mantiene **un proceso Python vivo** durante la sesión, de modo que la
caché, el octree y el aprendizaje de Markov persisten entre llamadas. La memoria
SQLite, además, sobrevive al reinicio y puede compartirse entre el perfil global
y los presets (WAL + `busy_timeout`: un escritor, varios lectores).

### Memoria de procesos y autoaprendizaje (SQLite)

`memoria_vectorw.py` guarda cuatro cosas:

| Tabla | Qué contiene |
|---|---|
| `procesos` | tareas resueltas: intención, pasos, resultado presupuestado, referencia, estado (`candidato` → `validado` → `obsoleto`/`rechazado`), éxito/fallo y tokens ahorrados. |
| `lecciones` | errores resueltos: `error_signature`, causa raíz, corrección, prevención y módulo. Se indexan también con la intención de la tarea, así que se recuperan buscando la tarea, no el error. |
| `recursos` | catálogo indexado de skills, agentes, documentos y herramientas, con su ruta y un extracto. `rutaSkills` lo alimenta con las skills del preset. |
| `eventos` | bitácora de aciertos/fallos usada para `hit_rate` y tokens ahorrados. |

Reglas de diseño:

- **Deduplicación**: `huella` = raíces de tokens ordenadas + `UNIQUE`, así que
  guardar dos veces la misma tarea actualiza en vez de duplicar.
- **Presupuesto**: el resultado se recorta a `presupuestoCaracteres` al guardar y
  la respuesta a `maxTokensRespuesta` al devolver; `truncado` avisa al agente.
- **Redacción**: claves API, contraseñas, tokens y cabeceras `Authorization` se
  sustituyen por `[REDACTADO]` antes de persistir.
- **Índices**: prefilter SQL por tokens compartidos + índice invertido en memoria
  para la caché; la puntuación fina la hace la geometría W 4D.
- **Autoaprendizaje**: al guardar un proceso con `estado: validado` (o al
  actualizarlo varias veces) queda disponible para cualquier agente; las
  lecciones se recuperan junto a la tarea equivalente. La promoción a
  `validado` exige evidencia del agente, nunca se inventa.

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

# 2. ¿La memoria SQLite, las lecciones y el presupuesto funcionan? → 45/45
python pruebas/verificar_memoria.py

# 3. ¿El port TypeScript coincide con la referencia?             → 140/140
node implementaciones/typescript/prueba.ts

# 4. ¿El port JavaScript coincide con la referencia?             → 147/147
node implementaciones/javascript/prueba.mjs

# 5. ¿El plugin se monta y sus 9 herramientas funcionan?         → OK
#    (ejecutar desde el directorio del perfil de DSH)
cd "$DSH_HOME/profiles"
node /ruta/al/plugin/pruebas/verificar_montaje.mjs

# 6. Regenerar el corpus tras cambiar el algoritmo
python pruebas/generar_vectores.py

# 7. Calibrar el umbral con datos propios
python pruebas/calibrar_distancia.py
```

| Prueba | Comprueba | Resultado |
|---|---|---|
| `verificar_equivalencia.py` | La firma de la referencia coincide con `vectorW_6.py` en 9 puntos × 2 tamaños de cubo | 47/47 |
| `verificar_memoria.py` | Esquema SQLite, recuperación semántica de procesos, lecciones, presupuesto de tokens, dedupe, gate de polaridad, catálogo de skills, índices, warm-start, redacción y purga | 45/45 |
| `typescript/prueba.ts` | Tokenización, centroides, firmas, espacios, distancias y decisiones de caché | 140/140 |
| `javascript/prueba.mjs` | Lo anterior + SHA-256 propio frente a `node:crypto` | 147/147 |
| `verificar_montaje.mjs` | Que el bundle declara la fila bajo `insert:`, que el loader resuelve el módulo, que se monta sobre un `Context` real de Cordis, que registra las 9 herramientas y que todas ejecutan | 42/42 |
| `verificar.mjs` | Carga del plugin y ejecución de las herramientas | OK |
| `verificar_ahorro.mjs` | Acierto exacto, acierto semántico y fallo | OK |
| `calibrar_distancia.py` | Margen del umbral entre reformulaciones y temas distintos | informativo |

### Defectos corregidos en la revisión de puesta en uso

| Defecto | Síntoma | Corrección |
|---|---|---|
| `peerDependencies` congeladas en `^0.1.1-rc.2` | El plugin aparecía en el perfil pero DSH lo mantenía **deshabilitado** («incompatible con dsh 0.2.1-rc.2») | Rango alineado al runtime (`^0.2.1-rc.2`) y comprobación en `verificar-plugin.ps1` |
| Instalación a mano en el perfil | Fila creada pero no habilitada; imports sin resolver | Empaquetado como **bundle** + `install_bundle` |
| Geometría incoherente | La caché firmaba el centroide de tokens, pero el predictor se entrenaba con el hash del texto completo: aprendía en puntos que no eran los de la caché | Una única función de coordenadas compartida por firma, espacios y entrenamiento |
| Claves por `time.time()` | El reloj de Windows avanza en saltos de ~15 ms, así que guardados seguidos repetían clave y se **sobrescribían**: `episodios` y `datos_en_octree` contaban menos de lo real | Contador monótono por entrada |
| Métricas del núcleo siempre a cero | `vector_stats` mostraba octree y episodios vacíos porque el puente nunca escribía en ellos | El puente registra ahora el episodio y el nodo de octree |

### Optimizaciones implementadas en 1.4.0 y pendientes

La revisión de la documentación (`docs/`) dejó cinco hallazgos. Estado real:

| # | Mejora | Estado en 1.4.0 |
|---|---|---|
| 1 | **Índice para la búsqueda** en vez de escaneo lineal: índice invertido por token (mismo recall, sin recorrer toda la caché) + índice de celdas W (`clasificar_en_espacios`, complemento geométrico) + índice exacto O(1) | ✅ implementado y medido en `verificar_memoria.py` |
| 2 | **Presupuesto de tokens y resumen** por entrada: recorte al guardar (`presupuestoCaracteres`) y al devolver (`maxTokensRespuesta`), con marca `truncado` | ✅ implementado |
| 3 | **Deduplicación por hash semántico** sin palabras vacías: huella de raíces ordenadas + `UNIQUE` en SQLite; actualiza en vez de duplicar | ✅ implementado |
| 4 | **Gate de confianza por entropía** y alertas operativas en `vector_stats` (hit rate, latencia, profundidad de octree) | ⚠️ parcial: `vector_stats` ya informa hit rate, índices, presupuesto y memoria; la entropía se muestra del núcleo, pero no bloquea aciertos |
| 5 | **Warm-start real**: restaurar reentrena el predictor/octree con las coordenadas guardadas y reconstruye los índices | ✅ implementado (`reentrenarAlRestaurar`) |

Además, la memoria SQLite añade lo que el escaneo lineal no resolvía: reutilizar
**procesos completos** (no solo valores) y **lecciones de error**, y enrutar una
necesidad al **recurso** correcto (skill/documento/herramienta) del preset.

### Límites medidos que conviene conocer

- **La distancia W por sí sola no distingue.** Medido con
  `pruebas/calibrar_distancia.py`: una consulta de tema distinto **sin
  vocabulario común** da distancia `0.0913`, menor que la peor reformulación
  válida (`0.1162`) y menor que el umbral (`0.15`). La seguridad la aporta el
  filtro de solapamiento, no el umbral; por eso el filtro se aplica antes de
  elegir la candidata.
- **La negación es invisible para el tokenizador.** «no optimizar X» y
  «optimizar X» comparten todos los tokens significativos (`no` es palabra
  vacía). Un gate de polaridad (`_polaridad`) bloquea ese falso acierto y la
  huella de deduplicación incluye la polaridad, así que ambas tareas no
  colisionan. Es una comprobación léxica, no comprensión del lenguaje: «evitar
  X» cuenta como negación, «dejar de no hacer X» no se resuelve.
- **Umbrales no intercambiables**: `0.15` aquí (firma normalizada + penalización)
  no equivale al `0.3` de la documentación de integración ni a un coseno de
  `0.85`.
- **`ladoCubo`**: el plugin usa `1024` (defecto del *constructor* del núcleo),
  mientras `ConfigVOS.LADO_CUBO_DEFAULT` vale `32000`. Se mantiene `1024` porque
  es el valor con el que la firma está verificada; no los mezcles.
- **Licencia**: todo el repositorio, su documentación (Markdown, ODT, DOCX y
  PDF) y este plugin usan **LAMC PEPIUOX v1.0 / LULA v1.1**, una licencia de
  uso libre con atribución. Ninguna otra licencia aplica a VectorW.


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
