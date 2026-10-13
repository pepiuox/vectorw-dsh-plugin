# Implementaciones de la firma W 4D

El mismo algoritmo, en varios lenguajes, con **el mismo resultado numérico**.
Todas las implementaciones producen firmas idénticas porque comparten una única
fuente de verdad: los **vectores de prueba** de `../pruebas/vectores_w.json`,
que genera la implementación de Python — la cual está verificada contra el
núcleo original de VectorW (`../vendor/vectorW_py/vectorW_6.py`).

> **VectorW — núcleo original de Jose Ricardo Mantilla Mantilla (PePiuoX)**
> https://github.com/PePiuoX · Licencia LAMC v1.0 / LULA v1.1

## Cadena de confianza

```
vendor/vectorW_py/vectorW_6.py        núcleo del autor (sin modificar)
        │
        │  pruebas/verificar_equivalencia.py   → 47/47 OK
        ▼
implementaciones/python/vectorw_w.py  referencia verificada
        │
        │  pruebas/generar_vectores.py         → vectores_w.json
        ▼
pruebas/vectores_w.json               corpus compartido
        │
        ├── typescript/   → 140/140 OK   (verificado)
        ├── javascript/   → 147/147 OK   (verificado)
        ├── go/           → SIN VERIFICAR  (no hay toolchain Go aquí)
        └── rust/         → SIN VERIFICAR  (no hay toolchain Rust aquí)
```

Solo se declara **verificado** un port cuando sus pruebas se han ejecutado y
comparado contra el corpus. Los ports de Go y Rust están escritos con cuidado
pero **no se han compilado ni ejecutado** en este equipo: no había `go`,
`rustc` ni `cargo` disponibles. Sus README lo advierten y explican cómo
verificarlos.

## Estado de cada implementación

| Lenguaje | Archivo | Estado | Verificación |
|---|---|---|---|
| Python | `python/vectorw_w.py` | ✅ Verificado | `pruebas/verificar_equivalencia.py` (47/47) + `vectores_w.json` |
| TypeScript | `typescript/vectorw_w.ts` | ✅ Verificado | `node typescript/prueba.ts` (140/140) |
| JavaScript | `javascript/vectorw_w.mjs` | ✅ Verificado | `node javascript/prueba.mjs` (147/147) |
| Go | `go/vectorw/vectorw.go` | ⚠️ Sin verificar | `cd go && go test ./...` |
| Rust | `rust/src/lib.rs` | ⚠️ Sin verificar | `cd rust && cargo test` |

## Qué es la firma W 4D

Cada texto se convierte en 4 números que lo sitúan en el espacio de memoria
VectorW:

1. **Tokens.** El texto se pasa a minúsculas, se le quitan los acentos, se
   descartan las palabras vacías y las palabras de menos de 3 letras, y cada
   palabra se reduce a una raíz para tolerar plurales y género
   (`frecuencia` → `frecuenc`, `frecuencias` → `frecuenc`).
2. **Punto por token.** Cada raíz se resume con SHA-256 y sus primeros 24
   dígitos hexadecimales dan un punto `(x, y, z)` dentro del cubo de memoria
   (lado 1024 por defecto).
3. **Centroide.** El texto se representa por la media de los puntos de sus
   tokens. Dos textos con vocabulario parecido caen cerca.
4. **Proyección.** El centroide se proyecta sobre las 4 diagonales del cubo, lo
   que da los 4 componentes de la firma:

```
t_k(p) = ( b_k · L + s_k · p ) / √3

k   diagonal   b_k              s_k
1   W1 (+++)   0                (+1, +1, +1)
2   W2 (-++)   1+√3 ≈ 2.7321    (-1, +1, +1)
3   W3 (+-+)   1+√3 ≈ 2.7321    (+1, -1, +1)
4   W4 (++-)   1+√3 ≈ 2.7321    (+1, +1, -1)
```

La firma normalizada es `t_k / (L·√3) = (b_k + s_k · p') / 3`. Recorrido del
cubo:

```
(0,0,0) → (0.000, 0.911, 0.911, 0.911)
(L,L,L) → (1.000, 1.244, 1.244, 1.244)
```

Los componentes 2..4 **no empiezan en 0** sino en ≈0.9107: el núcleo sitúa el
inicio de esas tres rectas fuera del cubo. Es una propiedad del núcleo, no un
error; la firma sirve para clasificar y comparar, no como medida absoluta.

## Qué es la distancia

La distancia combina dos señales, porque la geometría sola produce falsos
aciertos (dos consultas sin nada en común pueden caer cerca por azar):

```
distancia = geometricaW × (0.35 + 1.3 × (1 − jaccard))
```

La geométrica es el mínimo sobre las **24 permutaciones** de la segunda firma,
lo que hace la comparación invariante al orden de las diagonales.

Regla de decisión de la caché, en dos pasos y en este orden:

1. se **descartan** las entradas sin ningún token en común;
2. entre las restantes, se toma la de menor distancia y se acepta si
   `distancia ≤ 0.15`.

El orden importa: si se elige primero la más cercana y luego se exige
solapamiento, una entrada sin nada en común puede adelantarse a la que sí
coincide y convertir un acierto válido en un fallo. Ese error existió en este
proyecto y está anotado en el código para no reintroducirlo.

## Cómo añadir otro lenguaje

1. Porta el algoritmo respetando la tokenización al detalle: el orden de los
   sufijos, la lista de palabras vacías y el tratamiento de acentos deben ser
   idénticos, porque de la raíz depende todo lo demás.
2. Escribe una prueba que lea `pruebas/vectores_w.json` y compare, con
   tolerancia `1e-9`, las secciones `tokenizacion`, `puntos`, `textos`,
   `distancias` y `cache`.
3. Añade una fila a la tabla de estado de este README, con el recuento real de
   comprobaciones y la etiqueta correcta: **verificado** solo si ejecutaste la
   prueba.

Si tu port cambia el algoritmo, cambia primero la referencia de Python y vuelve
a generar el corpus con `python ../pruebas/generar_vectores.py`.
