# Python — implementación de referencia

`vectorw_w.py` es la **fuente de verdad** del algoritmo de firma W 4D y de la
caché semántica en este repositorio:

- **Sin dependencias**: solo la biblioteca estándar de Python 3.8+.
- **Verificada contra el núcleo original**: su aritmética coincide número a
  número con `vendor/vectorW_py/vectorW_6.py`
  (`../pruebas/verificar_equivalencia.py`, 47/47 comprobaciones a dos tamaños de
  cubo).
- **Genera el corpus compartido** que verifican los ports a otros lenguajes.

> VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)
> https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1

## Uso

```python
from vectorw_w import CacheSemanticaW, FamiliaDiagonalesW, tokenizar

familia = FamiliaDiagonalesW()          # cubo de lado 1024, 8 espacios
firma = familia.firma_de_texto("optimizar consultas vectoriales con octree")
print(firma.tokens)      # ['optimizar', 'consult', 'vectorial', 'octree']
print(firma.firma)       # (0.674..., 1.085..., 1.134..., 1.186...)
print(firma.espacios)    # (5, 7, 7, 7)

cache = CacheSemanticaW(familia)
cache.guardar("optimizar consultas vectoriales con octree", "resultado", tokens=4200)

r = cache.buscar("optimizar consultas vectoriales con octree y podado espacial")
print(r["hit"], r["kind"], round(r["distancia"], 4))
# True semantico 0.101   ← acierto: ~4200 tokens evitados
```

Demostración completa:

```bash
python vectorw_w.py
```

## API

| Símbolo | Descripción |
|---|---|
| `ConfigW` | Constantes: lado del cubo, espacios, umbral, pesos. |
| `tokenizar(texto)` | Raíces significativas, sin acentos ni palabras vacías. |
| `FamiliaDiagonalesW` | Las 4 diagonales y la aritmética de firmas. |
| `FirmaW` | Firma de un texto: tokens, centroide, componentes, firma, espacios. |
| `CacheSemanticaW` | Caché consulta→valor con recuperación por similitud. |

Métodos principales de `FamiliaDiagonalesW`:

| Método | Devuelve |
|---|---|
| `parametro_t(indice, punto)` | Proyección sin normalizar sobre una diagonal. |
| `componentes_de(punto)` | Las 4 proyecciones. |
| `firma_de_punto(punto)` | Las 4 proyecciones normalizadas. |
| `espacios_de(punto)` | Índice de espacio W (0..n-1) por diagonal. |
| `punto_w(token)` | Punto 3D determinista de un token. |
| `centroide(tokens, texto)` | Punto medio de los puntos de los tokens. |
| `firma_de_texto(texto)` | Firma completa de un texto. |
| `distancia(f1, f2)` | `(distancia, solapamiento)` combinados. |

## Recalibrar el umbral

`ConfigW.UMBRAL_SIMILITUD` vale `0.15`. Para revisarlo con datos propios,
`../pruebas/calibrar_distancia.py` mide pares que *deberían* acertar
(reformulaciones) frente a pares que no *deberían* acertar nunca (temas
distintos) y muestra el margen disponible entre ambos grupos.

## Regenerar el corpus de pruebas

Tras cualquier cambio en el algoritmo:

```bash
python ../pruebas/generar_vectores.py
python ../pruebas/verificar_equivalencia.py
```

El primer comando reescribe `../pruebas/vectores_w.json`; el segundo confirma
que la aritmética sigue coincidiendo con el núcleo original.
