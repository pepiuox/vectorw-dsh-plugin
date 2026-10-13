# Núcleo VectorW vendorizado — atribución y procedencia

> **Este software utiliza código de PePiuoX (https://github.com/PePiuoX)**
>
> **Autor:** Jose Ricardo Mantilla Mantilla (PePiuoX)
> **Licencia:** LAMC v1.0 / LULA v1.1 — https://pepiuox.org/lamc/v1.0

## Qué hay en esta carpeta

Copias **sin modificar** de los archivos principales del núcleo VectorW
(`vectorW_py/`), incluidas aquí para que el plugin sea **autocontenido**: quien
clone este repositorio puede usar el plugin sin tener que conseguir aparte la
instalación original de VectorW.

| Archivo | Bytes | SHA-256 |
|---|---|---|
| `vectorW_6.py` | 98214 | `8BF8EF76F15683D51DCD66C66624C4FE1B42A6D6180E921445364BFEA58EF8D0` |
| `vectorW_v5-1.py` | 87612 | `39C6330942A3FA5054E3E0728900398F92F190FB3088D873BDD8FBE300801F02` |
| `vectorW_ai_predictor.py` | 58452 | `A9B2E27EC63BE60EDFBB391555F43B4510CD1F45F8F3DC8698D0B466A8D0AD6D` |
| `vectorW_v5.py` | 47593 | `66E93ABD2D330D93A5F9D5F63FD627D9E0FC8A6DA484C4F49FBED669B516FA5A` |
| `vectorW.py` | 40445 | `BEC03A1C70560314366E3BB38C56B43FA72EA8A19E663BBD470B75C843AF1D53` |
| `faiss_firma_w4d.py` | 40264 | `0A089328CE48CB3FD4EE081C5B0B305F14B52255F438479F53B3005471A721A7` |
| `ia_vectorial_adapter.py` | 15791 | `9D74B675E337F34BF7C39BD031D95E55C7709976C5303C8F205A693AEF2FE246` |
| `vector3D.py` | 15142 | `1AD049C1213C1A71823BB55AFCE39346A49F7ADACB375DA78F649D635B807330` |

## Estos archivos NO se modifican

Ninguno de los archivos de esta carpeta ha sido alterado. Las correcciones de
compatibilidad que el plugin necesita se aplican **en memoria**, desde
`bridge_vos.py`, sobre la clase ya importada (ver «Parches» más abajo). Así el
código del autor queda intacto y verificable por su hash.

Si prefieres usar tu propia instalación de VectorW en lugar de esta copia,
basta con indicar su ruta en `rutaCore` (ver el README principal). El puente
prueba primero `rutaCore` y solo después esta carpeta. El campo
`origen_nucleo` de `vector_stats` indica cuál se está usando (`rutaCore` o
`vendor`).

## Parches aplicados en memoria

`vectorW_6.py` v6.0 contiene dos defectos que rompen exactamente las rutas que
el plugin necesita. Se corrigen sin tocar el archivo:

1. **`PredictorMarkovOrdenSuperior`** aplica *slicing* a un
   `collections.deque` (`self.historial[-self.orden:]`), operación que `deque`
   no soporta en ninguna versión de CPython. Consecuencias:
   - `MemoriaVectorialProduccion.escribir()` devuelve `False` a partir de la
     tercera escritura;
   - toda predicción lanza `TypeError`;
   - `consultar_semantico()` falla por completo (la excepción no está
     capturada).
   → Se sustituye el `deque` interno por una `list`, que sí admite *slicing*
   manteniendo la misma semántica de cola acotada.

2. **`NodoOctreeMemoriaEficiente.insertar`** recibe los argumentos desplazados
   desde `MemoriaVectorialProduccion.escribir`: el diccionario de datos llega
   al parámetro `coords`, lo que produce
   `"sequence index must be integer, not 'slice'"`.
   → Se normaliza `coords` a una terna de números.

Ambos parches son idempotentes y quedan anunciados en `vector_stats` (campo
`parches`) para que el usuario sepa que están activos.

### Corregirlos en el origen

Si prefieres arreglar el núcleo en lugar de parchearlo en memoria, aplica en
`vectorW_py/vectorW_6.py`:

```python
# 1. En PredictorMarkovOrdenSuperior.__init__
#    self.historial: deque = deque(maxlen=10000)
self.historial: list = []

#    ...y en registrar(), acotar la lista a 10000 elementos:
def registrar(self, estado: int):
    self.historial.append(estado)
    if len(self.historial) > 10000:
        del self.historial[:-10000]
    if len(self.historial) > self.orden:
        secuencia = tuple(self.historial[-self.orden - 1:-1])
        siguiente = self.historial[-1]
        self.transiciones[secuencia][siguiente] += 1

# 2. En MemoriaVectorialProduccion.escribir, pasar coords explícitamente:
self.raiz.insertar(key, {'coords': coords, 'valor': valor,
                         'd_l': direccion_plana, 'timestamp': time.time()}, coords)
```

Con esos cambios, el núcleo funciona sin la capa de parches.

## Límites conocidos del núcleo, no del plugin

Los siguientes puntos se documentan porque afectan a lo que se puede prometer,
y se comprobaron ejecutando el código:

- **`NucleoVectorialOS_Avanzado` (vectorW_v5.py) no se puede instanciar.** Falla
  en tres puntos distintos: `NúcleoVectorialOSOptimizado.__init__` llama a
  `cargar_o_inicializar_nodos`, que no existe en el repositorio;
  `VectorW3D_MemoriaAdaptativa` pasa un argumento de más al `dataclass`
  `VectorW`; y se invoca `_calcular_parametro_t`, tampoco definido. Por eso el
  plugin usa `vectorW_6.MemoriaVectorialProduccion`, que sí funciona.
  Esto también deja sin efecto `vectorW_tools.py` y `suit_de_pruebas.py`.
- **`vectorW_ai_predictor.py` y `vectorW_ai_streaming.py` importan
  `vectorW_produccion`**, un módulo que no existe con ese nombre (el archivo es
  `vectorW_6.py`), así que su caché semántica (`CacheSemanticaW`) nunca llega a
  tener `FamiliaDiagonales` definido. Además `vectorW_ai_predictor.py` importa
  `requests` sin protección, dependencia que el runtime de DSH no incluye.
- **`CacheSemanticaW.buscar` incrementa `self._hits`**, atributo inexistente
  (el definido es `self.hits`), así que cualquier acierto semántico lanzaría
  `AttributeError`. Por eso el plugin implementa su propia caché de pares
  consulta→valor en lugar de reutilizar esa clase.
- **`guardar_modelo` / `cargar_modelo` / `cargar_checkpoint` solo restauran
  `metricas`**: la persistencia del núcleo es efectivamente de solo escritura.
- `ia_vectorial_adapter.py` importa tres nombres desde `vectorW` cuando viven en
  `vector3D.py`, por lo que el módulo no se puede importar tal cual.

Nada de esto se corrige aquí: son observaciones sobre el núcleo original,
útiles para quien lo use directamente.
