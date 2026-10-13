# Licencia y atribución — Plugin VectorW para DeepSeek Harness

## Atribución obligatoria

El núcleo vectorial **VectorW / vOS v6.0** (`vectorW_py/vectorW_6.py` y demás
archivos de `vectorW_py/`) es obra de:

    Jose Ricardo Mantilla Mantilla (PePiuoX)
    https://github.com/PePiuoX

y se distribuye bajo la **Licencia de Atribución, Mejora Continua y Exención de
Responsabilidad (LAMC) PEPIUOX v1.0** y la **Licencia de Uso Libre y Atribución
(LULA) v1.1**.

En cumplimiento de su cláusula 1, toda distribución de este plugin —modificado
o no— debe incluir de forma razonablemente visible:

> Este software utiliza código de PePiuoX (https://github.com/PePiuoX)

## Alcance de este plugin

Este directorio (`vectorw-dsh-plugin/`) contiene únicamente obra nueva:

- `lib/index.js` — plugin de DeepSeek Harness (Cordis): registro de herramientas
  y gestión del proceso puente.
- `bridge_vos.py` — puente JSON que **importa** el núcleo VectorW y expone su
  caché de firmas W 4D y su predictor. No reimplementa ni copia el núcleo.
- `install.ps1`, `verificar.mjs`, `verificar_ahorro.mjs`, `calibrar_distancia.py`,
  `README.md` — instalación, verificación y documentación.

El código del núcleo VectorW **no se copia ni se redistribuye** aquí: se ejecuta
desde la carpeta `vectorW_py` indicada en la configuración (`rutaCore`). Las
correcciones de compatibilidad que aplica `bridge_vos.py` (ver `README.md`) se
hacen **en memoria** y no modifican los archivos del autor.

## Texto de la licencia LULA v1.1

    LICENCIA DE USO LIBRE Y ATRIBUCIÓN (LULA) v1.1

    Copyright (c) 2026 Jose Ricardo Mantilla Mantilla (PePiuoX)

    Se concede permiso, de forma gratuita, a cualquier persona que obtenga una
    copia de este software y de los archivos de documentación asociados (el
    "Software"), para usar, copiar, modificar, fusionar, publicar, distribuir,
    sublicenciar y/o vender copias del Software, y para permitir a las personas
    a quienes se les proporcione el Software hacer lo mismo, sujeto a las
    siguientes condiciones:

    1. En toda distribución del Software, modificado o no, deberá incluirse la
       atribución al autor original de forma razonablemente visible:

       Este software utiliza código de PePiuoX (https://github.com/PePiuoX)

    2. Las modificaciones son propiedad de sus autores y pueden licenciarse bajo
       términos distintos, siempre que se mantenga la atribución al autor original
       y no se restrinjan los derechos otorgados sobre el código original.

    3. El Software se proporciona "TAL CUAL", sin garantía de ningún tipo, expresa
       o implícita. En ningún caso el autor o los contribuidores serán responsables
       por daños derivados del uso del Software.

    4. Cada contribuidor concede una licencia de patente gratuita, mundial,
       perpetua y libre de regalías para usar el Software. Esta licencia de
       patente terminará si el receptor inicia un litigio de patentes contra
       cualquier contribuidor basado en el Software.

El texto íntegro de las licencias del proyecto está en `docs/` y en la raíz de
VectorW (`LICENSE.md`, `LICENSE`, `LICENSE_EN`).
