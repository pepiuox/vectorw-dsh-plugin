// VectorW — nucleo original de Jose Ricardo Mantilla Mantilla (PePiuoX), https://github.com/PePiuoX
//
//! Port de referencia, en Rust, del algoritmo de firma W 4D y de la cache
//! semantica de VectorW.
//!
//! # Atribucion
//!
//! Arquitectura y autor del nucleo VectorW original:
//! Jose Ricardo Mantilla Mantilla (PePiuoX),
//! <https://github.com/PePiuoX>, Licencia LAMC v1.0 / LULA v1.1.
//!
//! # Fuente de verdad
//!
//! Este crate es un port literal de `implementaciones/python/vectorw_w.py`. Esa
//! implementacion de Python es la referencia **verificada** (su geometria esta
//! comprobada punto por punto contra el nucleo original en
//! `pruebas/verificar_equivalencia.py`) y es la que genero los vectores
//! compartidos `pruebas/vectores_w.json`.
//!
//! # Estado: NO COMPILADO NI VERIFICADO
//!
//! En la maquina donde se escribio este archivo no estan instalados ni `rustc`
//! ni `cargo`, de modo que el codigo NO ha sido compilado, formateado
//! (`cargo fmt`), analizado (`cargo clippy`) ni ejecutado jamas. Esta escrito
//! para ser autocontenido y logicamente correcto, pero cualquier afirmacion
//! sobre su comportamiento en ejecucion esta SIN VERIFICAR. Para verificarlo:
//!
//! ```text
//! cd implementaciones/rust && cargo test
//! ```
//!
//! # Dependencias
//!
//! Ninguna: `[dependencies]` esta vacio y **no se usa ningun crate externo**,
//! ni siquiera `sha2` ni `unicode-normalization`. Por eso:
//!
//! * SHA-256 esta implementado a mano en este archivo (es corto y esta
//!   completamente especificado en FIPS 180-4);
//! * la descomposicion NFD de los diacriticos latinos se hace con una tabla
//!   explicita (`descomponer_latin`);
//! * la clasificacion de "caracter de palabra" usa un conjunto de rangos
//!   Unicode escritos a mano (`es_palabra_continua`), porque `char::is_alphabetic`
//!   de la biblioteca estandar no basta para reproducir el `\w` de Python.

#![forbid(unsafe_code)]

use std::collections::{HashMap, HashSet};
use std::time::{SystemTime, UNIX_EPOCH};

/// Version del algoritmo portado (coincide con `vectorw_w.VERSION` en Python).
pub const VERSION: &str = "1.1.0";

// ---------------------------------------------------------------------------
// Configuracion
// ---------------------------------------------------------------------------

/// Constantes del espacio de memoria VectorW.
///
/// Los valores reproducen los del nucleo v6.0: cubo de lado 1024 y 8 espacios
/// por diagonal (32 espacios de resolucion total).
pub mod config_w {
    /// Arista del cubo de memoria.
    pub const LADO_CUBO: f64 = 1024.0;
    /// Numero de espacios W por diagonal.
    pub const N_ESPACIOS: usize = 8;
    /// Distancia maxima aceptada como acierto semantico.
    pub const UMBRAL_SIMILITUD: f64 = 0.15;
    /// Numero maximo de entradas de la cache por defecto.
    pub const MAX_ENTRADAS: usize = 2000;
    /// Tiempo de vida por defecto de una entrada, en segundos (0 = sin caducidad).
    pub const TTL_SEGUNDOS: f64 = 0.0;
    /// Hace la comparacion geometrica invariante al orden de las 4 diagonales.
    pub const INVARIANTE_PERMUTACIONES: bool = true;
    /// Peso de la geometria en la distancia combinada.
    pub const PESO_GEOMETRIA: f64 = 0.35;
    /// Peso del solapamiento en la distancia combinada.
    pub const PESO_SOLAPAMIENTO: f64 = 1.3;
}

/// Reexportacion plana de las constantes, para comodidad del consumidor.
pub use config_w::{
    INVARIANTE_PERMUTACIONES, LADO_CUBO, MAX_ENTRADAS, N_ESPACIOS, PESO_GEOMETRIA,
    PESO_SOLAPAMIENTO, TTL_SEGUNDOS, UMBRAL_SIMILITUD,
};

// ---------------------------------------------------------------------------
// Tokenizacion
// ---------------------------------------------------------------------------

/// Sufijos que se recortan para tolerar plurales, genero y conjugaciones
/// simples. El ORDEN es significativo: se aplica el PRIMER sufijo de la lista
/// que encaje. Copiado literalmente de `_SUFIJOS` en la referencia Python.
pub const SUFIJOS: [&str; 15] = [
    "ciones", "cion", "mente", "ados", "adas", "ado", "ada", "idos", "idas", "ido", "ida", "es",
    "os", "as", "s",
];

/// Palabras vacias, copiadas literalmente de `_PALABRAS_VACIAS` en la
/// referencia Python (148 palabras: 110 en espanol y 38 en ingles).
pub const PALABRAS_VACIAS: [&str; 148] = [
    // Espanol
    "a", "al", "algo", "algunas", "algunos", "ante", "antes", "aqui", "asi", "aun", "aunque",
    "bien", "cada", "como", "con", "contra", "cual", "cuando", "de", "del", "desde", "donde",
    "dos", "el", "ella", "ellas", "ellos", "en", "entre", "era", "eran", "es", "esa", "esas",
    "ese", "eso", "esos", "esta", "estaba", "estado", "estas", "este", "esto", "estos", "fue",
    "fueron", "ha", "hace", "hacia", "han", "hasta", "hay", "la", "las", "le", "les", "lo",
    "los", "mas", "me", "mi", "mis", "mucho", "muy", "nada", "ni", "no", "nos", "nosotros",
    "nuestra", "nuestro", "o", "os", "otra", "otro", "para", "pero", "poco", "por", "porque",
    "que", "quien", "se", "sea", "segun", "ser", "si", "sin", "sobre", "son", "su", "sus",
    "tal", "tambien", "tanto", "te", "tiene", "tienen", "todo", "todos", "tu", "tus", "un",
    "una", "uno", "unos", "y", "ya",
    // Ingles
    "the", "is", "at", "which", "on", "an", "and", "are", "as", "be", "been", "but", "by",
    "can", "for", "from", "has", "have", "how", "in", "into", "it", "its", "of", "or", "that",
    "their", "there", "these", "this", "to", "was", "were", "what", "when", "where", "who",
    "will", "with", "your",
];

/// True si la palabra esta en el conjunto de palabras vacias.
///
/// Se usa una comprobacion lineal explicita en lugar de busqueda binaria porque
/// la tabla original de Python no esta ordenada globalmente (sus dos secciones,
/// espanol e ingles, si lo estan por separado).
fn es_palabra_vacia(palabra: &str) -> bool {
    PALABRAS_VACIAS.contains(&palabra)
}

/// True si la runa es un caracter de palabra Unicode, equivalente al `\w` de
/// Python usado por la referencia (`re.UNICODE`, que incluye letras, digitos
/// decimales y de otros tipos, y guion bajo).
///
/// `char::is_alphanumeric` de la biblioteca estandar reproduce exactamente esa
/// clasificacion (letras y numeros de cualquier script, incluidos los
/// superindices y las fracciones como caracteres numericos), y las marcas
/// combinantes (Mn) quedan fuera, igual que en Python. El guion bajo se anade
/// aparte porque no es alfanumerico.
fn es_palabra_continua(c: char) -> bool {
    c == '_' || c.is_alphanumeric()
}

/// Tabla de descomposicion NFD (canonica) de los caracteres latinos
/// precompuestos: cada entrada es la secuencia de caracteres en la que Python
/// sustituye el caracter al aplicar `unicodedata.normalize("NFKD", ...)`.
///
/// Se incluyen las formas de Latin-1 Supplement y Latin Extended-A que pueden
/// aparecer en texto latino, no solo las cinco vocales acentuadas espanolas.
/// Las runas combinantes de la descomposicion se descartan despues, que es
/// exactamente lo que hace `_sin_acentos` al filtrar `unicodedata.combining`.
const DESCOMPOSICION_LATINA: &[(char, &str)] = &[
    // Vocales con acento agudo
    ('á', "a\u{301}"), ('é', "e\u{301}"), ('í', "i\u{301}"),
    ('ó', "o\u{301}"), ('ú', "u\u{301}"), ('ý', "y\u{301}"),
    ('Á', "A\u{301}"), ('É', "E\u{301}"), ('Í', "I\u{301}"),
    ('Ó', "O\u{301}"), ('Ú', "U\u{301}"), ('Ý', "Y\u{301}"),
    // Vocales con acento grave
    ('à', "a\u{300}"), ('è', "e\u{300}"), ('ì', "i\u{300}"),
    ('ò', "o\u{300}"), ('ù', "u\u{300}"),
    ('À', "A\u{300}"), ('È', "E\u{300}"), ('Ì', "I\u{300}"),
    ('Ò', "O\u{300}"), ('Ù', "U\u{300}"),
    // Vocales con circunflejo
    ('â', "a\u{302}"), ('ê', "e\u{302}"), ('î', "i\u{302}"),
    ('ô', "o\u{302}"), ('û', "u\u{302}"),
    ('Â', "A\u{302}"), ('Ê', "E\u{302}"), ('Î', "I\u{302}"),
    ('Ô', "O\u{302}"), ('Û', "U\u{302}"),
    // Vocales con dieresis
    ('ä', "a\u{308}"), ('ë', "e\u{308}"), ('ï', "i\u{308}"),
    ('ö', "o\u{308}"), ('ü', "u\u{308}"), ('ÿ', "y\u{308}"),
    ('Ä', "A\u{308}"), ('Ë', "E\u{308}"), ('Ï', "I\u{308}"),
    ('Ö', "O\u{308}"), ('Ü', "U\u{308}"), ('Ÿ', "Y\u{308}"),
    // Vocal con tilde
    ('ã', "a\u{303}"), ('õ', "o\u{303}"),
    ('Ã', "A\u{303}"), ('Õ', "O\u{303}"),
    // Vocales con macron / breve / caron
    ('ā', "a\u{304}"), ('ē', "e\u{304}"), ('ī', "i\u{304}"),
    ('ō', "o\u{304}"), ('ū', "u\u{304}"),
    ('Ă', "A\u{306}"), ('ă', "a\u{306}"),
    ('ǎ', "a\u{30C}"), ('ě', "e\u{30C}"), ('ǐ', "i\u{30C}"),
    ('ǒ', "o\u{30C}"), ('ǔ', "u\u{30C}"),
    // Enye
    ('ñ', "n\u{303}"), ('Ñ', "N\u{303}"),
    // C con cedilla / agudo / caron
    ('ç', "c\u{327}"), ('Ç', "C\u{327}"),
    ('ć', "c\u{301}"), ('Ć', "C\u{301}"),
    ('č', "c\u{30C}"), ('Č', "C\u{30C}"),
    // S, Z, N con acentos
    ('ś', "s\u{301}"), ('Ś', "S\u{301}"),
    ('š', "s\u{30C}"), ('Š', "S\u{30C}"),
    ('ź', "z\u{301}"), ('Ź', "Z\u{301}"),
    ('ż', "z\u{307}"), ('Ż', "Z\u{307}"),
    ('ž', "z\u{30C}"), ('Ž', "Z\u{30C}"),
    ('ń', "n\u{301}"), ('Ń', "N\u{301}"),
    // Diacriticos de Europa central con doble acento
    ('ő', "o\u{30B}"), ('ű', "u\u{30B}"),
];

/// Descomposicion de letras compuestas que NFKD separa en dos letras base.
const DESCOMPOSICION_COMPUESTA: &[(char, &str)] = &[
    ('æ', "ae"),
    ('Æ', "AE"),
    ('œ', "oe"),
    ('Œ', "OE"),
    ('ß', "ss"),
];

/// True si el caracter es una marca combinante (categoria general Mn/Mc/Me),
/// es decir un diacritico que `_sin_acentos` descarta.
fn es_combinante(c: char) -> bool {
    let punto = c as u32;
    // Rangos de marcas combinantes mas comunes (el mismo criterio amplio que
    // usa `unicodedata.combining` != 0, que cubre Mn/Mc/Me).
    (0x0300..=0x036F).contains(&punto)
        || (0x0483..=0x0489).contains(&punto)
        || (0x0591..=0x05BD).contains(&punto)
        || (0x0610..=0x061A).contains(&punto)
        || (0x064B..=0x065F).contains(&punto)
        || (0x0E31..=0x0E3A).contains(&punto)
        || (0x1AB0..=0x1AFF).contains(&punto)
        || (0x1DC0..=0x1DFF).contains(&punto)
        || (0x20D0..=0x20F0).contains(&punto)
        || (0xFE20..=0xFE2F).contains(&punto)
}

/// Aplica la descomposicion NFD a cada caracter de `s` y elimina las marcas
/// combinantes, replicando `_sin_acentos` de la referencia Python para texto
/// latino.
pub fn descomponer_latin(s: &str) -> String {
    if s.is_ascii() {
        return s.to_string();
    }
    let mut salida = String::with_capacity(s.len());
    for c in s.chars() {
        if let Some(pos) = DESCOMPOSICION_LATINA
            .iter()
            .position(|(base, _)| *base == c)
        {
            for d in DESCOMPOSICION_LATINA[pos].1.chars() {
                if !es_combinante(d) {
                    salida.push(d);
                }
            }
            continue;
        }
        if let Some(pos) = DESCOMPOSICION_COMPUESTA
            .iter()
            .position(|(base, _)| *base == c)
        {
            salida.push_str(DESCOMPOSICION_COMPUESTA[pos].1);
            continue;
        }
        if es_combinante(c) {
            continue; // diacritico suelto: se descarta
        }
        salida.push(c);
    }
    salida
}

/// Raiz aproximada de un token, conservadora y determinista.
///
/// Reproduce `_raiz`: se recorta el PRIMER sufijo de [`SUFIJOS`] que encaje y
/// cumpla `len(token) > len(sufijo) + 3`.
pub fn raiz(token: &str) -> String {
    for sufijo in SUFIJOS.iter() {
        if token.len() > sufijo.len() + 3 && token.ends_with(sufijo) {
            return token[..token.len() - sufijo.len()].to_string();
        }
    }
    token.to_string()
}

/// Extrae los tokens significativos de un texto.
///
/// Aplica minusculas, quita acentos, descarta palabras vacias y palabras de
/// menos de 3 caracteres, reduce a raiz y elimina duplicados conservando el
/// orden de primera aparicion.
///
/// La determinacion de la raiz debe ser identica en todos los lenguajes porque
/// de ella depende que las firmas coincidan.
pub fn tokenizar(texto: &str) -> Vec<String> {
    if texto.is_empty() {
        return Vec::new();
    }
    // La referencia hace unicodedata.normalize("NFKD", texto.lower()): primero
    // minusculas (to_lowercase en Rust) y despues la descomposicion.
    let minusculas: String = texto.to_lowercase();

    let mut salida: Vec<String> = Vec::new();
    let mut vistos: HashSet<String> = HashSet::new();
    let mut actual = String::new();

    // Cierre que procesa el campo acumulado, equivalente a cada coincidencia de
    // _RE_TOKEN.findall(texto).
    let mut procesar = |crudo: &str, salida: &mut Vec<String>, vistos: &mut HashSet<String>| {
        if crudo.is_empty() {
            return;
        }
        let normalizado = descomponer_latin(crudo);
        if normalizado.chars().count() < 3 {
            return;
        }
        if es_palabra_vacia(&normalizado) {
            return;
        }
        let raiz_token = raiz(&normalizado);
        if vistos.contains(&raiz_token) {
            return;
        }
        vistos.insert(raiz_token.clone());
        salida.push(raiz_token);
    };

    for c in minusculas.chars() {
        if es_palabra_continua(c) {
            actual.push(c);
        } else if !actual.is_empty() {
            procesar(&actual, &mut salida, &mut vistos);
            actual.clear();
        }
    }
    if !actual.is_empty() {
        procesar(&actual, &mut salida, &mut vistos);
    }

    salida
}

// ---------------------------------------------------------------------------
// SHA-256 (implementacion propia, sin dependencias)
// ---------------------------------------------------------------------------

/// Constantes de ronda SHA-256 (FIPS 180-4, seccion 4.2.2).
const K_SHA256: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

/// Estado inicial de SHA-256 (FIPS 180-4, seccion 5.3.3).
const H0_SHA256: [u32; 8] = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
];

/// Compresion de un bloque de 64 bytes sobre el estado.
fn sha256_compresion(estado: &mut [u32; 8], bloque: &[u8]) {
    let mut w = [0u32; 64];
    for i in 0..16 {
        let j = i * 4;
        w[i] = ((bloque[j] as u32) << 24)
            | ((bloque[j + 1] as u32) << 16)
            | ((bloque[j + 2] as u32) << 8)
            | (bloque[j + 3] as u32);
    }
    for i in 16..64 {
        let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
        let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16]
            .wrapping_add(s0)
            .wrapping_add(w[i - 7])
            .wrapping_add(s1);
    }

    let mut a = estado[0];
    let mut b = estado[1];
    let mut c = estado[2];
    let mut d = estado[3];
    let mut e = estado[4];
    let mut f = estado[5];
    let mut g = estado[6];
    let mut h = estado[7];

    for i in 0..64 {
        let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
        let ch = (e & f) ^ ((!e) & g);
        let temp1 = h
            .wrapping_add(s1)
            .wrapping_add(ch)
            .wrapping_add(K_SHA256[i])
            .wrapping_add(w[i]);
        let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
        let maj = (a & b) ^ (a & c) ^ (b & c);
        let temp2 = s0.wrapping_add(maj);

        h = g;
        g = f;
        f = e;
        e = d.wrapping_add(temp1);
        d = c;
        c = b;
        b = a;
        a = temp1.wrapping_add(temp2);
    }

    estado[0] = estado[0].wrapping_add(a);
    estado[1] = estado[1].wrapping_add(b);
    estado[2] = estado[2].wrapping_add(c);
    estado[3] = estado[3].wrapping_add(d);
    estado[4] = estado[4].wrapping_add(e);
    estado[5] = estado[5].wrapping_add(f);
    estado[6] = estado[6].wrapping_add(g);
    estado[7] = estado[7].wrapping_add(h);
}

/// SHA-256 completo, implementado a mano.
///
/// Es necesario porque este crate no admite dependencias externas (no se puede
/// usar `sha2`). La implementacion sigue FIPS 180-4: relleno con un bit 1,
/// ceros hasta 56 mod 64, y la longitud del mensaje en bits como entero de 64
/// bits big-endian.
pub fn sha256(mensaje: &[u8]) -> [u8; 32] {
    let mut estado = H0_SHA256;

    // Bloques completos.
    let mut bloques = mensaje.chunks_exact(64);
    for bloque in bloques.by_ref() {
        sha256_compresion(&mut estado, bloque);
    }

    // Ultimo bloque parcial mas el relleno.
    let resto = bloques.remainder();
    let longitud_original = resto.len();
    let hay_segundo = longitud_original >= 56;
    let tam_final = if hay_segundo { 128 } else { 64 };
    let mut ultimo = [0u8; 128];
    ultimo[..longitud_original].copy_from_slice(resto);
    ultimo[longitud_original] = 0x80;
    let bits = (mensaje.len() as u64).wrapping_mul(8);
    ultimo[tam_final - 8..tam_final].copy_from_slice(&bits.to_be_bytes());

    sha256_compresion(&mut estado, &ultimo[0..64]);
    if hay_segundo {
        sha256_compresion(&mut estado, &ultimo[64..128]);
    }

    let mut resumen = [0u8; 32];
    for (i, palabra) in estado.iter().enumerate() {
        resumen[i * 4..i * 4 + 4].copy_from_slice(&palabra.to_be_bytes());
    }
    resumen
}

// ---------------------------------------------------------------------------
// Firma W 4D
// ---------------------------------------------------------------------------

/// Punto 3D dentro del cubo de memoria.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Vec3 {
    /// Coordenada x.
    pub x: f64,
    /// Coordenada y.
    pub y: f64,
    /// Coordenada z.
    pub z: f64,
}

impl Vec3 {
    /// Construye un punto 3D.
    pub fn nuevo(x: f64, y: f64, z: f64) -> Self {
        Vec3 { x, y, z }
    }
}

/// Firma W 4D de un texto, con su procedencia.
#[derive(Debug, Clone, PartialEq)]
pub struct FirmaW {
    /// Tokens significativos usados.
    pub tokens: Vec<String>,
    /// Centroide 3D de los tokens dentro del cubo.
    pub coords: Vec3,
    /// Las 4 proyecciones `t` sobre las diagonales (sin normalizar).
    pub componentes: [f64; 4],
    /// Las 4 proyecciones normalizadas por la longitud de la diagonal.
    pub firma: [f64; 4],
    /// Indice de espacio W (0..n-1) en cada diagonal.
    pub espacios: [usize; 4],
    /// True si el texto no aporto ningun token.
    pub es_vacia: bool,
}

impl FirmaW {
    /// Representacion estilo `__repr__` de la referencia.
    pub fn repr(&self) -> String {
        let firmas: Vec<String> = self
            .firma
            .iter()
            .map(|v| format!("{:.6}", v))
            .collect();
        format!(
            "FirmaW(firma=[{}], espacios={:?})",
            firmas.join(", "),
            self.espacios
        )
    }
}

/// Coeficientes `s_k` de las 4 diagonales, en el orden W1(+++), W2(-++),
/// W3(+-+), W4(++-).
pub const SIGNOS_W: [[f64; 3]; 4] = [
    [1.0, 1.0, 1.0],
    [-1.0, 1.0, 1.0],
    [1.0, -1.0, 1.0],
    [1.0, 1.0, -1.0],
];

/// Las 4 diagonales del cubo de memoria y la aritmetica de firmas W 4D.
///
/// Reproduce exactamente la geometria del nucleo original. Cada diagonal es una
/// recta dirigida entre dos vertices opuestos del cubo y la proyeccion de un
/// punto sobre ella es la forma afin verificada contra el nucleo:
///
/// ```text
/// t_k(p) = ( b_k * L + s_k . p ) / sqrt(3)
/// ```
///
/// con `s_k` los coeficientes de la diagonal (±1) y `b_k` su termino constante:
///
/// ```text
/// k   diagonal   b_k              s_k
/// 1   W1 (+++)   0                (+1, +1, +1)
/// 2   W2 (-++)   1+sqrt(3)        (-1, +1, +1)
/// 3   W3 (+-+)   1+sqrt(3)        (+1, -1, +1)
/// 4   W4 (++-)   1+sqrt(3)        (+1, +1, -1)
/// ```
///
/// La firma normalizada es `t_k / (L*sqrt(3)) = (b_k + s_k . p') / 3`, con
/// `p' = p/L`. Por eso los componentes 2..4 arrancan en ~0.9107
/// (= (1+sqrt(3))/3) y no en 0: el nucleo situa el inicio de esas tres rectas
/// fuera del cubo (2797.62 con lado 1024), asi que cualquier punto del interior
/// proyecta un valor alto. El recorrido de la firma es:
///
/// ```text
/// (0,0,0)  -> (0.000, 0.911, 0.911, 0.911)
/// (L,L,L)  -> (1.000, 1.244, 1.244, 1.244)
/// ```
///
/// Es una propiedad del nucleo, no un error; por eso la firma W 4D sirve para
/// clasificar y comparar, no como medida absoluta. La tabla se obtuvo midiendo
/// el nucleo y se verifica punto por punto (a dos tamanos de cubo) en
/// `pruebas/verificar_equivalencia.py`.
#[derive(Debug, Clone)]
pub struct FamiliaDiagonalesW {
    /// Arista del cubo.
    pub lado: f64,
    /// Numero de espacios W por diagonal (>= 1).
    pub n_espacios: usize,
    /// Longitud de la diagonal (`L * sqrt(3)`); tambien es el normalizador.
    pub longitud: f64,
    /// sqrt(3).
    pub raiz3: f64,
    /// Divisor de la firma (igual a `longitud`).
    pub normalizador: f64,
    /// Termino constante `b_k` de cada diagonal.
    pub bases: [f64; 4],
}

impl Default for FamiliaDiagonalesW {
    fn default() -> Self {
        FamiliaDiagonalesW::nuevo(LADO_CUBO, N_ESPACIOS)
    }
}

impl FamiliaDiagonalesW {
    /// Construye la familia de diagonales para un cubo de lado `lado` y
    /// `n_espacios` espacios por diagonal.
    ///
    /// Valores no validos se corrigen como en la referencia: `n_espacios < 1`
    /// pasa a 1 y un lado no positivo o NaN pasa al lado canonico (1024). Este
    /// ultimo caso no existe en Python (que no lo comprueba) y se anade aqui
    /// solo para evitar una geometria degenerada.
    pub fn nuevo(lado: f64, n_espacios: usize) -> Self {
        let lado = if lado.is_nan() || lado <= 0.0 {
            LADO_CUBO
        } else {
            lado
        };
        let n_espacios = if n_espacios < 1 { 1 } else { n_espacios };
        let raiz3 = 3.0f64.sqrt();
        let longitud = lado * raiz3;
        FamiliaDiagonalesW {
            lado,
            n_espacios,
            longitud,
            raiz3,
            normalizador: longitud,
            bases: [0.0, 1.0 + raiz3, 1.0 + raiz3, 1.0 + raiz3],
        }
    }

    /// True si el lado del cubo es el del nucleo (1024).
    ///
    /// La forma afin escala con el lado del cubo, asi que este modulo coincide
    /// con el nucleo en cualquier tamano (verificado a 1024 y 32000). La marca
    /// se conserva para poder distinguir la configuracion por defecto.
    pub fn es_geometria_canonica(&self) -> bool {
        (self.lado - 1024.0).abs() < 1e-9
    }

    /// Punto 3D determinista de un token dentro del cubo.
    ///
    /// Es la proyeccion de un hash criptografico, no una posicion semantica
    /// real: lo que importa es que sea determinista, uniforme y estable, para
    /// que dos textos con los mismos tokens den el mismo centroide.
    ///
    /// Usa [`sha256`] (implementacion propia, sin dependencias) sobre los bytes
    /// UTF-8 del token, igual que `hashlib.sha256(token.encode("utf-8"))`.
    pub fn punto_w(&self, token: &str) -> Vec3 {
        let resumen = sha256(token.as_bytes());
        // La referencia toma las subcadenas hex 0:8, 8:16 y 16:24, es decir los
        // primeros 12 bytes del resumen, de 4 en 4, en orden big-endian.
        let lado = self.lado.trunc() as i64;
        let lado = if lado <= 0 { 1 } else { lado };
        let mut valores = [0i64; 3];
        for i in 0..3 {
            let j = i * 4;
            let trozo = u32::from_be_bytes([resumen[j], resumen[j + 1], resumen[j + 2], resumen[j + 3]]);
            valores[i] = (trozo as i64) % lado;
        }
        Vec3::nuevo(
            valores[0] as f64,
            valores[1] as f64,
            valores[2] as f64,
        )
    }

    /// Punto medio de los puntos W de los tokens.
    ///
    /// Si no hay tokens se usa el punto del texto completo, para que una
    /// consulta vacia siga teniendo una firma valida.
    pub fn centroide(&self, tokens: &[String], texto: &str) -> Vec3 {
        if tokens.is_empty() {
            return self.punto_w(texto);
        }
        let mut x = 0.0;
        let mut y = 0.0;
        let mut z = 0.0;
        for token in tokens {
            let p = self.punto_w(token);
            x += p.x;
            y += p.y;
            z += p.z;
        }
        let n = tokens.len() as f64;
        Vec3::nuevo(x / n, y / n, z / n)
    }

    /// Proyeccion escalar del punto sobre la diagonal `indice`.
    ///
    /// Forma lineal verificada punto por punto contra el nucleo:
    ///
    /// ```text
    /// t_k(p) = ( b_k * L + s_k . p ) / sqrt(3)
    /// ```
    ///
    /// donde `s_k` son los coeficientes (±1) de la diagonal y `b_k` su termino
    /// constante: 0 en W1 y `1+sqrt(3) ~ 2.7321` en W2, W3 y W4. Ese
    /// desplazamiento es lo que hace que las tres ultimas ramas de la firma
    /// empiecen en `(1+sqrt(3))/3 ~ 0.9107` en lugar de en 0.
    ///
    /// Devuelve `f64::NAN` si el indice no esta en 0..3 (Go devuelve lo mismo).
    pub fn parametro_t(&self, indice: usize, punto: Vec3) -> f64 {
        if indice > 3 {
            return f64::NAN;
        }
        let signos = SIGNOS_W[indice];
        let proyeccion = signos[0] * punto.x + signos[1] * punto.y + signos[2] * punto.z;
        (self.bases[indice] * self.lado + proyeccion) / self.raiz3
    }

    /// Las 4 proyecciones `t` sin normalizar.
    pub fn componentes_de(&self, punto: Vec3) -> [f64; 4] {
        [
            self.parametro_t(0, punto),
            self.parametro_t(1, punto),
            self.parametro_t(2, punto),
            self.parametro_t(3, punto),
        ]
    }

    /// Firma W 4D normalizada de un punto 3D.
    ///
    /// Equivale a `FamiliaDiagonales.calcular_firma_normalizada` del nucleo:
    /// divide cada proyeccion por el normalizador (`L * sqrt(3)`).
    pub fn firma_de_punto(&self, punto: Vec3) -> [f64; 4] {
        let componentes = self.componentes_de(punto);
        [
            componentes[0] / self.normalizador,
            componentes[1] / self.normalizador,
            componentes[2] / self.normalizador,
            componentes[3] / self.normalizador,
        ]
    }

    /// Indice de espacio W (0..n-1) de cada diagonal para un punto.
    ///
    /// El nucleo acota la proyeccion a `[0, longitud]` (la diagonal completa)
    /// antes de repartirla en espacios, no al normalizador. La conversion a
    /// entero trunca hacia cero, igual que `int()` en Python.
    pub fn espacios_de(&self, punto: Vec3) -> [usize; 4] {
        let n = self.n_espacios as f64;
        let mut salida = [0usize; 4];
        for (i, hueco) in salida.iter_mut().enumerate() {
            let t = self.parametro_t(i, punto);
            let t_acotado = t.max(0.0).min(self.longitud);
            let indice = (t_acotado / self.longitud * n).trunc() as i64;
            let indice = if indice < 0 { 0 } else { indice as usize };
            *hueco = if indice > self.n_espacios - 1 {
                self.n_espacios - 1
            } else {
                indice
            };
        }
        salida
    }

    /// Firma W 4D completa de un texto.
    pub fn firma_de_texto(&self, texto: &str) -> FirmaW {
        let tokens = tokenizar(texto);
        let coords = self.centroide(&tokens, texto);
        let componentes = self.componentes_de(coords);
        let firma = [
            componentes[0] / self.normalizador,
            componentes[1] / self.normalizador,
            componentes[2] / self.normalizador,
            componentes[3] / self.normalizador,
        ];
        let es_vacia = tokens.is_empty();
        FirmaW {
            tokens,
            coords,
            componentes,
            firma,
            espacios: self.espacios_de(coords),
            es_vacia,
        }
    }

    // -- distancias ---------------------------------------------------------

    /// Distancia euclidea directa entre dos firmas W 4D.
    pub fn distancia_geometrica(&self, f1: &[f64; 4], f2: &[f64; 4]) -> f64 {
        let mut suma = 0.0;
        for i in 0..4 {
            let d = f1[i] - f2[i];
            suma += d * d;
        }
        suma.sqrt()
    }

    /// Distancia minima sobre las 24 permutaciones de la segunda firma.
    ///
    /// Hace la comparacion invariante al orden de las diagonales, de modo que
    /// un punto que cae simetrico respecto a un eje no se penalice. Es
    /// sensiblemente mas caro (24 distancias en lugar de 1).
    pub fn distancia_permutaciones(&self, f1: &[f64; 4], f2: &[f64; 4]) -> f64 {
        let mut mejor = f64::INFINITY;
        // 4! = 24 permutaciones, enumeradas igual que en la referencia.
        for a in 0..4usize {
            for b in 0..4usize {
                if b == a {
                    continue;
                }
                for c in 0..4usize {
                    if c == a || c == b {
                        continue;
                    }
                    let d = 6 - a - b - c; // el indice restante
                    let perm = [f2[a], f2[b], f2[c], f2[d]];
                    let dist = self.distancia_geometrica(f1, &perm);
                    if dist < mejor {
                        mejor = dist;
                    }
                }
            }
        }
        mejor
    }

    /// Distancia combinada W 4D mas solapamiento de vocabulario.
    ///
    /// La geometria sola produce falsos aciertos: dos consultas sin ninguna
    /// palabra en comun pueden caer cerca por azar. El solapamiento (Jaccard
    /// sobre las raices de los tokens) actua de penalizacion, y sin vocabulario
    /// compartido la distancia no puede bajar del umbral.
    ///
    /// Devuelve `(distancia, solapamiento)`.
    pub fn distancia(&self, f1: &FirmaW, f2: &FirmaW, invariante_permutaciones: bool) -> (f64, f64) {
        let geometrica = if invariante_permutaciones {
            self.distancia_permutaciones(&f1.firma, &f2.firma)
        } else {
            self.distancia_geometrica(&f1.firma, &f2.firma)
        };

        let conjunto1: HashSet<&str> = f1.tokens.iter().map(|s| s.as_str()).collect();
        let conjunto2: HashSet<&str> = f2.tokens.iter().map(|s| s.as_str()).collect();
        if conjunto1.is_empty() || conjunto2.is_empty() {
            return (geometrica, 0.0);
        }

        let interseccion = conjunto1.intersection(&conjunto2).count();
        let union = conjunto1.union(&conjunto2).count();
        let solapamiento = if union != 0 {
            interseccion as f64 / union as f64
        } else {
            0.0
        };
        let penalizacion = PESO_GEOMETRIA + PESO_SOLAPAMIENTO * (1.0 - solapamiento);
        (geometrica * penalizacion, solapamiento)
    }
}

// ---------------------------------------------------------------------------
// Cache semantica
// ---------------------------------------------------------------------------

/// Entrada guardada en la cache.
#[derive(Debug, Clone)]
pub struct EntradaCache {
    /// Consulta original tal como se guardo.
    pub query: String,
    /// Consulta normalizada (minusculas y espacios colapsados).
    pub query_norm: String,
    /// Resultado cacheado.
    pub valor: String,
    /// Coste estimado en tokens de obtener el valor.
    pub tokens: i64,
    /// Firma W 4D de la consulta normalizada.
    pub firma: FirmaW,
    /// Metadatos libres.
    pub metadata: HashMap<String, String>,
    /// Instante de insercion (segundos desde la época).
    pub timestamp: f64,
    /// Instante de caducidad; `None` si no caduca.
    pub expira: Option<f64>,
}

/// Resultado de una busqueda, tanto si hay acierto como si no.
#[derive(Debug, Clone)]
pub struct ResultadoCache {
    /// True si hubo acierto.
    pub hit: bool,
    /// `"exacto"`, `"semantico"` o `"miss"`.
    pub kind: String,
    /// Consulta que devuelve la cache (la guardada, en caso de acierto).
    pub query: String,
    /// Valor cacheado, si lo hay.
    pub value: Option<String>,
    /// Tokens ahorrados por el acierto.
    pub tokens_ahorrados: i64,
    /// Distancia de la coincidencia; `None` si no hubo candidata con
    /// solapamiento (equivale al `None`/`null` de la referencia en el fallo).
    pub distancia: Option<f64>,
    /// Solapamiento de la coincidencia.
    pub solapamiento: f64,
    /// Umbral de similitud vigente.
    pub umbral: f64,
    /// Firma W 4D de la entrada recuperada.
    pub firma_cache: [f64; 4],
    /// Espacios W de la entrada recuperada.
    pub espacios: [usize; 4],
    /// Numero de candidatas en la cache.
    pub candidatos: usize,
    /// Mejor distancia observada, si hubo alguna candidata con solapamiento.
    pub mejor_distancia: Option<f64>,
    /// Mejor solapamiento observado.
    pub mejor_solapamiento: f64,
}

/// Resultado de guardar una entrada.
#[derive(Debug, Clone)]
pub struct ResultadoGuardado {
    /// Siempre true.
    pub stored: bool,
    /// Consulta guardada.
    pub query: String,
    /// Firma W 4D de la consulta normalizada.
    pub firma: [f64; 4],
    /// Espacios W de la consulta normalizada.
    pub espacios: [usize; 4],
    /// Coste en tokens declarado.
    pub tokens: i64,
    /// Numero de entradas tras guardar.
    pub entradas: usize,
}

/// Metricas de acierto y ahorro acumulado.
#[derive(Debug, Clone, PartialEq)]
pub struct EstadisticasCache {
    /// Entradas actuales.
    pub entradas: usize,
    /// Capacidad maxima.
    pub max_entradas: usize,
    /// Umbral de similitud vigente.
    pub umbral_similitud: f64,
    /// Aciertos exactos.
    pub hits_exactos: i64,
    /// Aciertos semanticos.
    pub hits_semanticos: i64,
    /// Fallos.
    pub fallos: i64,
    /// Tasa de acierto.
    pub hit_rate: f64,
    /// Tokens ahorrados acumulados.
    pub tokens_ahorrados: i64,
    /// Tokens almacenados acumulados.
    pub tokens_almacenados: i64,
}

/// Cache de pares consulta->valor con recuperacion por similitud W 4D.
///
/// Sustituye la coincidencia literal de cadenas por coincidencia semantica:
/// una consulta reformulada recupera la respuesta ya calculada, que es el
/// ahorro real de tokens.
///
/// # Diferencia de representacion respecto a Python (judgement call)
///
/// Python indexa las entradas por la tupla de 4 flotantes de la firma, que es
/// hashable. Rust tampoco permite usar flotantes como clave de un `HashMap`, de
/// modo que aqui se indexa por la **consulta normalizada** y se mantiene un
/// `Vec<String>` con el orden de insercion para reproducir el comportamiento
/// FIFO/LRU de `OrderedDict`. El efecto observable es el mismo que en Python y
/// ademas evita cualquier colision por redondeo: dos consultas que se
/// normalizan a la misma cadena tienen exactamente la misma firma.
#[derive(Debug, Clone)]
pub struct CacheSemanticaW {
    /// Familia de diagonales usada para firmar.
    pub familia: FamiliaDiagonalesW,
    /// Umbral de similitud.
    pub umbral: f64,
    /// Capacidad maxima.
    pub max_entradas: usize,
    /// Tiempo de vida en segundos (0 = sin caducidad).
    pub ttl: f64,

    entradas: HashMap<String, EntradaCache>,
    orden: Vec<String>,

    /// Aciertos exactos.
    pub hits_exactos: i64,
    /// Aciertos semanticos.
    pub hits_semanticos: i64,
    /// Fallos.
    pub fallos: i64,
    /// Tokens ahorrados acumulados.
    pub tokens_ahorrados: i64,
    /// Tokens almacenados acumulados.
    pub tokens_almacenados: i64,
}

impl Default for CacheSemanticaW {
    fn default() -> Self {
        CacheSemanticaW::nuevo(
            FamiliaDiagonalesW::default(),
            UMBRAL_SIMILITUD,
            MAX_ENTRADAS,
            TTL_SEGUNDOS,
        )
    }
}

impl CacheSemanticaW {
    /// Construye una cache semantica.
    ///
    /// El orden de los parametros reproduce el constructor de la referencia
    /// Python: familia, umbral de similitud, maximo de entradas y TTL.
    pub fn nuevo(
        familia: FamiliaDiagonalesW,
        umbral_similitud: f64,
        max_entradas: usize,
        ttl_segundos: f64,
    ) -> Self {
        CacheSemanticaW {
            familia,
            umbral: umbral_similitud,
            max_entradas,
            ttl: ttl_segundos,
            entradas: HashMap::new(),
            orden: Vec::new(),
            hits_exactos: 0,
            hits_semanticos: 0,
            fallos: 0,
            tokens_ahorrados: 0,
            tokens_almacenados: 0,
        }
    }

    /// Normalizacion para la coincidencia exacta: minusculas y espacios
    /// colapsados.
    pub fn normalizar(texto: &str) -> String {
        texto
            .to_lowercase()
            .split_whitespace()
            .collect::<Vec<&str>>()
            .join(" ")
    }

    /// Busca una consulta equivalente en la cache.
    ///
    /// Primero intenta coincidencia exacta normalizada y despues similitud
    /// semantica; nunca acepta una entrada si no comparte al menos un token.
    pub fn buscar(&mut self, consulta: &str) -> ResultadoCache {
        let normalizada = Self::normalizar(consulta);
        let firma = self.familia.firma_de_texto(&normalizada);
        let ahora = ahora_segundos();

        // 1) coincidencia exacta. Las expiradas se recogen y se eliminan
        // despues de recorrer, igual que en la referencia.
        let mut expiradas: Vec<String> = Vec::new();
        let mut acierto_exacto: Option<String> = None;
        for clave in self.orden.iter() {
            if let Some(entrada) = self.entradas.get(clave) {
                if self.ttl > 0.0 {
                    if let Some(expira) = entrada.expira {
                        if expira < ahora {
                            expiradas.push(clave.clone());
                            continue;
                        }
                    }
                }
                if entrada.query_norm == normalizada {
                    acierto_exacto = Some(clave.clone());
                    break;
                }
            }
        }
        if let Some(clave) = acierto_exacto {
            // move_to_end: la entrada exacta pasa al final (politica LRU).
            self.orden.retain(|c| *c != clave);
            self.orden.push(clave.clone());
            let entrada = self
                .entradas
                .get(&clave)
                .expect("la clave recien localizada debe existir");
            self.hits_exactos += 1;
            self.tokens_ahorrados += entrada.tokens;
            return self.vista(entrada, "exacto", 0.0, 1.0);
        }
        for clave in expiradas {
            self.entradas.remove(&clave);
            self.orden.retain(|c| *c != clave);
        }

        // 2) coincidencia semantica
        //
        // Solo se consideran candidatas las entradas que comparten al menos un
        // token. Filtrar *antes* de elegir la mas cercana es imprescindible: si
        // se elige primero la de menor distancia y luego se exige solapamiento,
        // una entrada sin nada en comun puede adelantarse a la que si coincide
        // (distancia pequena por azar) y convertir un acierto valido en un
        // fallo.
        let mut mejor_dist = f64::INFINITY;
        let mut mejor_solape = 0.0;
        let mut mejor_clave: Option<String> = None;
        for clave in self.orden.iter() {
            let entrada = match self.entradas.get(clave) {
                Some(e) => e,
                None => continue,
            };
            if self.ttl > 0.0 {
                if let Some(expira) = entrada.expira {
                    if expira < ahora {
                        continue;
                    }
                }
            }
            let (dist, solape) =
                self.familia
                    .distancia(&firma, &entrada.firma, INVARIANTE_PERMUTACIONES);
            if solape <= 0.0 {
                continue;
            }
            if dist < mejor_dist {
                mejor_dist = dist;
                mejor_solape = solape;
                mejor_clave = Some(clave.clone());
            }
        }

        if let Some(clave) = mejor_clave {
            if mejor_dist <= self.umbral {
                let entrada = self
                    .entradas
                    .get(&clave)
                    .expect("la clave candidata debe existir");
                self.hits_semanticos += 1;
                self.tokens_ahorrados += entrada.tokens;
                let vista = self.vista(entrada, "semantico", mejor_dist, mejor_solape);
                return vista;
            }
        }

        self.fallos += 1;
        ResultadoCache {
            hit: false,
            kind: "miss".to_string(),
            query: consulta.to_string(),
            value: None,
            tokens_ahorrados: 0,
            distancia: mejor_clave.as_ref().map(|_| mejor_dist),
            solapamiento: mejor_solape,
            umbral: self.umbral,
            firma_cache: firma.firma,
            espacios: firma.espacios,
            candidatos: self.entradas.len(),
            mejor_distancia: mejor_clave.as_ref().map(|_| mejor_dist),
            mejor_solapamiento: mejor_solape,
        }
    }

    /// Guarda un resultado asociado a una consulta.
    ///
    /// * `consulta`: consulta que produjo el resultado.
    /// * `valor`: resultado a cachear.
    /// * `tokens`: coste estimado en tokens de obtenerlo (para medir el ahorro).
    /// * `metadata`: metadatos libres.
    pub fn guardar(
        &mut self,
        consulta: &str,
        valor: &str,
        tokens: i64,
        metadata: HashMap<String, String>,
    ) -> ResultadoGuardado {
        let normalizada = Self::normalizar(consulta);
        let firma = self.familia.firma_de_texto(&normalizada);
        let tokens = if tokens < 0 { 0 } else { tokens };

        // Se elimina cualquier entrada previa con la misma clave (en Python, la
        // misma tupla de firma sobrescribe la entrada) y luego se evacua la mas
        // antigua mientras no quepa una entrada mas.
        if self.entradas.remove(&normalizada).is_some() {
            self.orden.retain(|c| *c != normalizada);
        }
        while self.entradas.len() >= self.max_entradas {
            if self.orden.is_empty() {
                break;
            }
            let mas_antigua = self.orden.remove(0); // popitem(last=False)
            self.entradas.remove(&mas_antigua);
        }

        let ahora = ahora_segundos();
        let entrada = EntradaCache {
            query: consulta.to_string(),
            query_norm: normalizada.clone(),
            valor: valor.to_string(),
            tokens,
            firma,
            metadata,
            timestamp: ahora,
            expira: if self.ttl > 0.0 {
                Some(ahora + self.ttl)
            } else {
                None
            },
        };
        self.entradas.insert(normalizada.clone(), entrada);
        self.orden.push(normalizada); // move_to_end
        self.tokens_almacenados += tokens;

        ResultadoGuardado {
            stored: true,
            query: consulta.to_string(),
            firma: firma.firma,
            espacios: firma.espacios,
            tokens,
            entradas: self.entradas.len(),
        }
    }

    /// Metricas de acierto y ahorro acumulado.
    pub fn estadisticas(&self) -> EstadisticasCache {
        let total = self.hits_exactos + self.hits_semanticos + self.fallos;
        let hit_rate = if total != 0 {
            (self.hits_exactos + self.hits_semanticos) as f64 / total as f64
        } else {
            0.0
        };
        EstadisticasCache {
            entradas: self.entradas.len(),
            max_entradas: self.max_entradas,
            umbral_similitud: self.umbral,
            hits_exactos: self.hits_exactos,
            hits_semanticos: self.hits_semanticos,
            fallos: self.fallos,
            hit_rate,
            tokens_ahorrados: self.tokens_ahorrados,
            tokens_almacenados: self.tokens_almacenados,
        }
    }

    /// Vacia la cache y devuelve cuantas entradas habia.
    pub fn limpiar(&mut self) -> usize {
        let cantidad = self.entradas.len();
        self.entradas.clear();
        self.orden.clear();
        cantidad
    }

    /// Entradas en orden de insercion (mas antigua primero).
    pub fn claves_en_orden(&self) -> Vec<String> {
        self.orden.clone()
    }

    /// Vista de acierto.
    fn vista(
        &self,
        entrada: &EntradaCache,
        tipo: &str,
        dist: f64,
        solape: f64,
    ) -> ResultadoCache {
        ResultadoCache {
            hit: true,
            kind: tipo.to_string(),
            query: entrada.query.clone(),
            value: Some(entrada.valor.clone()),
            tokens_ahorrados: entrada.tokens,
            distancia: Some(dist),
            solapamiento: solape,
            umbral: self.umbral,
            firma_cache: entrada.firma.firma,
            espacios: entrada.firma.espacios,
            candidatos: self.entradas.len(),
            mejor_distancia: Some(dist),
            mejor_solapamiento: solape,
        }
    }
}

/// Tiempo actual en segundos con fraccion, como `time.time()` en Python.
fn ahora_segundos() -> f64 {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => d.as_secs_f64(),
        Err(_) => 0.0,
    }
}

// ---------------------------------------------------------------------------
// Pruebas
// ---------------------------------------------------------------------------

/// Pruebas de conformidad con el corpus compartido.
///
/// ESTADO: NO EJECUTADAS. No hay `rustc` ni `cargo` en la maquina donde se
/// escribio este archivo, de modo que estas pruebas nunca se han compilado ni
/// ejecutado. Para ejecutarlas hace falta un toolchain:
///
/// ```text
/// cd implementaciones/rust && cargo test
/// ```
///
/// COBERTURA: el corpus completo y autorizado es `pruebas/vectores_w.json`
/// (15 tokenizaciones, 9 puntos, 15 textos, 5 pares de distancias y 3 decisiones
/// de cache), generado por la implementacion de referencia en Python. Aqui se
/// incrusta un subconjunto representativo como constantes literales para no
/// depender de ningun crate de JSON. El resto del corpus se puede comprobar con
/// `serde_json` (ver el `dev-dependencies` comentado en `Cargo.toml`) o
/// generando desde Python las constantes equivalentes.
#[cfg(test)]
mod pruebas {
    use super::*;

    /// Tolerancia absoluta, la misma que usan las pruebas de Go (1e-9).
    const TOLERANCIA: f64 = 1e-9;

    // -- Subconjunto literal del corpus ------------------------------------

    /// config: lado_cubo, n_espacios, longitud_diagonal, normalizador, umbral.
    const CONFIG_CORPUS: (f64, usize, f64, f64, f64) = (
        1024.0,
        8,
        1773.62002695053,
        1773.62002695053,
        0.15,
    );

    /// geometria.bases del corpus.
    const BASES_CORPUS: [f64; 4] = [
        0.0,
        2.732050807569,
        2.732050807569,
        2.732050807569,
    ];

    /// geometria.signos del corpus.
    const SIGNOS_CORPUS: [[f64; 3]; 4] = [
        [1.0, 1.0, 1.0],
        [-1.0, 1.0, 1.0],
        [1.0, -1.0, 1.0],
        [1.0, 1.0, -1.0],
    ];

    /// tokenizacion del corpus: entrada -> tokens esperados.
    const TOKENIZACION_CORPUS: [(&str, &[&str]); 6] = [
        (
            "optimizar consultas vectoriales con octree",
            &["optimizar", "consult", "vectorial", "octree"],
        ),
        (
            "optimizar consultas vectoriales con octree y podado espacial",
            &[
                "optimizar",
                "consult",
                "vectorial",
                "octree",
                "podado",
                "espacial",
            ],
        ),
        (
            "como funciona la cache LRU con TTL y frecuencias",
            &["funciona", "cache", "lru", "ttl", "frecuenci"],
        ),
        ("desplegar el plugin en linux con systemd", &[
            "desplegar",
            "plugin",
            "linux",
            "systemd",
        ]),
        ("cachés y caches", &["cach"]),
        ("áéíóú ñ", &["aeiou"]),
    ];

    /// puntos del corpus: (punto, componentes, firma, espacios).
    /// Se usan los indices 0, 1 y 5 del JSON.
    const PUNTOS_CORPUS: [([f64; 3], [f64; 4], [f64; 4], [usize; 4]); 3] = [
        (
            [0.0, 0.0, 0.0],
            [
                0.0,
                1615.206675650177,
                1615.206675650177,
                1615.206675650177,
            ],
            [0.0, 0.910683602523, 0.910683602523, 0.910683602523],
            [0, 7, 7, 7],
        ),
        (
            [1024.0, 0.0, 0.0],
            [
                591.206675650177,
                1024.0,
                2206.413351300353,
                2206.413351300353,
            ],
            [0.333333333333, 0.57735026919, 1.244016935856, 1.244016935856],
            [2, 4, 7, 7],
        ),
        (
            [512.0, 512.0, 512.0],
            [
                886.810013475265,
                1910.810013475265,
                1910.810013475265,
                1910.810013475265,
            ],
            [0.5, 1.07735026919, 1.07735026919, 1.07735026919],
            [4, 7, 7, 7],
        ),
    ];

    /// Estructura auxiliar para los textos del corpus.
    struct TextoCorpus {
        texto: &'static str,
        tokens: &'static [&'static str],
        coords: [f64; 3],
        componentes: [f64; 4],
        firma: [f64; 4],
        espacios: [usize; 4],
    }

    /// textos del corpus: indices 0, 3 y 9 del JSON.
    const TEXTOS_CORPUS: [TextoCorpus; 3] = [
        TextoCorpus {
            texto: "optimizar consultas vectoriales con octree",
            tokens: &["optimizar", "consult", "vectorial", "octree"],
            coords: [767.75, 692.25, 611.5],
            componentes: [
                1195.98108262631,
                1924.666419935816,
                2011.84631058345,
                2105.088379057574,
            ],
            firma: [
                0.67431640625,
                1.08516276919,
                1.134316415023,
                1.186888029606,
            ],
            espacios: [5, 7, 7, 7],
        },
        TextoCorpus {
            texto: "como funciona la cache LRU con TTL y frecuencia",
            tokens: &["funciona", "cache", "lru", "ttl", "frecuencia"],
            coords: [671.8, 446.6, 688.0],
            componentes: [
                1042.92552626414,
                1882.404380231136,
                2142.442941474143,
                1863.698231509392,
            ],
            firma: [
                0.588020833333,
                1.06133464419,
                1.207949227523,
                1.05078776919,
            ],
            espacios: [4, 7, 7, 7],
        },
        TextoCorpus {
            texto: "prediccion markov de orden superior",
            tokens: &["predic", "markov", "orden", "superior"],
            coords: [440.75, 534.5, 852.75],
            componentes: [
                1055.396292078636,
                2161.668705438158,
                2053.415529965103,
                1685.932083625906,
            ],
            firma: [
                0.595052083333,
                1.218789071273,
                1.157753915023,
                0.950559904606,
            ],
            espacios: [4, 7, 7, 7],
        },
    ];

    /// distancias del corpus: indices 0 y 3 del JSON. La segunda no tiene
    /// tokens en comun, de modo que la referencia devuelve (geometrica, 0.0).
    const DISTANCIAS_CORPUS: [(&str, &str, f64, f64, bool); 2] = [
        (
            "optimizar consultas vectoriales con octree",
            "optimizar consultas vectoriales con octree y podado espacial",
            0.100977009664,
            0.666666666667,
            true,
        ),
        (
            "optimizar consultas vectoriales con octree",
            "desplegar el plugin en linux con systemd",
            0.311903580864,
            0.0,
            false,
        ),
    ];

    /// Consulta guardada y consultas de cache del corpus, en orden.
    const CACHE_CONSULTAS: [&str; 3] = [
        "optimizar consultas vectoriales con octree",
        "optimizar consultas vectoriales con octree y podado espacial",
        "desplegar el plugin en linux con systemd",
    ];

    /// Decisiones esperadas de la cache: (hit, kind, query, tokens, distancia).
    const CACHE_ESPERADO: [(bool, &str, &str, i64, Option<f64>); 3] = [
        (
            true,
            "exacto",
            "optimizar consultas vectoriales con octree",
            4200,
            Some(0.0),
        ),
        (
            true,
            "semantico",
            "optimizar consultas vectoriales con octree",
            4200,
            Some(0.100977009664),
        ),
        (false, "miss", "", 0, None),
    ];

    /// cache_estadisticas del corpus.
    const CACHE_ESTADISTICAS_CORPUS: (usize, usize, i64, i64, i64, f64, i64, i64) = (
        2,
        2000,
        1,
        1,
        1,
        0.666666666667,
        8400,
        4260,
    );

    /// Coste en tokens usado por el generador del corpus al guardar la primera
    /// consulta (`tokens_almacenados` 4260 = 4200 + 60 por la segunda).
    const COSTE_PRIMERA: i64 = 4200;
    const COSTE_SEGUNDA: i64 = 60;

    // -- Utilidades ---------------------------------------------------------

    fn aproximado(a: f64, b: f64) -> bool {
        (a - b).abs() <= TOLERANCIA
    }

    fn vectores_aproximados(a: &[f64], b: &[f64]) -> bool {
        a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| aproximado(*x, *y))
    }

    // -- Pruebas ------------------------------------------------------------

    /// La configuracion del port coincide con la del corpus.
    #[test]
    fn configuracion_compartida() {
        let (lado, n_espacios, longitud, normalizador, umbral) = CONFIG_CORPUS;
        assert_eq!(lado, LADO_CUBO);
        assert_eq!(n_espacios, N_ESPACIOS);
        assert_eq!(umbral, UMBRAL_SIMILITUD);

        let familia = FamiliaDiagonalesW::nuevo(lado, n_espacios);
        assert!(aproximado(familia.longitud, longitud));
        assert!(aproximado(familia.normalizador, normalizador));
        for i in 0..4 {
            assert!(
                aproximado(familia.bases[i], BASES_CORPUS[i]),
                "base {}: port={} corpus={}",
                i,
                familia.bases[i],
                BASES_CORPUS[i]
            );
            for j in 0..3 {
                assert_eq!(SIGNOS_W[i][j], SIGNOS_CORPUS[i][j]);
            }
        }
        assert!(familia.es_geometria_canonica());
    }

    /// Tokenizar coincide con cada entrada del corpus.
    #[test]
    fn tokenizacion_del_corpus() {
        for (texto, esperado) in TOKENIZACION_CORPUS.iter() {
            let obtenido = tokenizar(texto);
            let esperado: Vec<String> = esperado.iter().map(|s| s.to_string()).collect();
            assert_eq!(
                obtenido, esperado,
                "tokenizar({:?}) = {:?}, esperado {:?}",
                texto, obtenido, esperado
            );
        }

        // Casos limite del corpus completo.
        assert!(tokenizar("").is_empty());
        assert!(tokenizar("a de la el").is_empty());
    }

    /// Componentes, firma y espacios de los puntos del corpus.
    #[test]
    fn puntos_del_corpus() {
        let familia = FamiliaDiagonalesW::default();
        for (punto, componentes, firma, espacios) in PUNTOS_CORPUS.iter() {
            let p = Vec3::nuevo(punto[0], punto[1], punto[2]);

            let comp = familia.componentes_de(p);
            assert!(
                vectores_aproximados(&comp, componentes),
                "componentes de {:?} = {:?}, esperado {:?}",
                punto,
                comp,
                componentes
            );
            for k in 0..4 {
                assert!(aproximado(familia.parametro_t(k, p), componentes[k]));
            }

            let f = familia.firma_de_punto(p);
            assert!(
                vectores_aproximados(&f, firma),
                "firma de {:?} = {:?}, esperado {:?}",
                punto,
                f,
                firma
            );

            let esp = familia.espacios_de(p);
            assert_eq!(&esp, espacios, "espacios de {:?}", punto);
        }
    }

    /// Firma completa de texto (tokens, centroide, componentes, firma, espacios).
    #[test]
    fn textos_del_corpus() {
        let familia = FamiliaDiagonalesW::default();
        for caso in TEXTOS_CORPUS.iter() {
            let f = familia.firma_de_texto(caso.texto);

            let tokens: Vec<String> = caso.tokens.iter().map(|s| s.to_string()).collect();
            assert_eq!(f.tokens, tokens, "tokens de {:?}", caso.texto);

            let coords = [f.coords.x, f.coords.y, f.coords.z];
            assert!(
                vectores_aproximados(&coords, &caso.coords),
                "coords de {:?} = {:?}, esperado {:?}",
                caso.texto,
                coords,
                caso.coords
            );
            assert!(
                vectores_aproximados(&f.componentes, &caso.componentes),
                "componentes de {:?} = {:?}, esperado {:?}",
                caso.texto,
                f.componentes,
                caso.componentes
            );
            assert!(
                vectores_aproximados(&f.firma, &caso.firma),
                "firma de {:?} = {:?}, esperado {:?}",
                caso.texto,
                f.firma,
                caso.firma
            );
            assert_eq!(f.espacios, caso.espacios, "espacios de {:?}", caso.texto);
            assert!(!f.es_vacia, "{:?} no deberia ser vacia", caso.texto);
        }
    }

    /// Distancia combinada y solapamiento de los pares del corpus.
    #[test]
    fn distancias_del_corpus() {
        let familia = FamiliaDiagonalesW::default();
        for (a, b, distancia, solapamiento, acierto) in DISTANCIAS_CORPUS.iter() {
            let f1 = familia.firma_de_texto(a);
            let f2 = familia.firma_de_texto(b);
            let (dist, solape) = familia.distancia(&f1, &f2, INVARIANTE_PERMUTACIONES);

            assert!(
                aproximado(dist, *distancia),
                "distancia({:?}, {:?}) = {}, esperado {}",
                a,
                b,
                dist,
                distancia
            );
            assert!(
                aproximado(solape, *solapamiento),
                "solapamiento({:?}, {:?}) = {}, esperado {}",
                a,
                b,
                solape,
                solapamiento
            );
            // La marca `acierto` del corpus es "la distancia no supera el umbral".
            assert_eq!(dist <= UMBRAL_SIMILITUD, *acierto);
        }
    }

    /// Regla critica de seleccion: una entrada sin tokens en comun nunca puede
    /// ser candidata, aunque su distancia geometrica sea pequena.
    #[test]
    fn distancia_sin_vocabulario_compartido() {
        let familia = FamiliaDiagonalesW::default();
        let f1 = familia.firma_de_texto("optimizar consultas vectoriales con octree");
        let f2 = familia.firma_de_texto("recetas de cocina vegana con tofu");
        let (dist, solape) = familia.distancia(&f1, &f2, INVARIANTE_PERMUTACIONES);

        assert_eq!(solape, 0.0, "no hay tokens compartidos");
        assert!(dist.is_finite(), "la distancia geometrica debe ser finita");
        assert!(
            dist > UMBRAL_SIMILITUD,
            "sin vocabulario la distancia combinada (geometrica * 1.65) no puede quedar bajo el umbral"
        );
    }

    /// La secuencia de cache del corpus se reproduce exactamente.
    #[test]
    fn cache_del_corpus() {
        let mut cache = CacheSemanticaW::default();

        // Se guardan todas las entradas menos la ultima (igual que el generador).
        for (i, consulta) in CACHE_CONSULTAS[..CACHE_CONSULTAS.len() - 1]
            .iter()
            .enumerate()
        {
            let coste = if i == 0 { COSTE_PRIMERA } else { COSTE_SEGUNDA };
            let r = cache.guardar(consulta, "valor", coste, HashMap::new());
            assert!(r.stored);
        }

        for (i, consulta) in CACHE_CONSULTAS.iter().enumerate() {
            let resultado = cache.buscar(consulta);
            let (hit, kind, query, tokens, distancia) = &CACHE_ESPERADO[i];

            assert_eq!(resultado.hit, *hit, "hit de {:?}", consulta);
            assert_eq!(&resultado.kind, kind, "kind de {:?}", consulta);
            if *hit {
                assert_eq!(&resultado.query, query, "query de {:?}", consulta);
                assert_eq!(resultado.tokens_ahorrados, *tokens);
                let esperada = distancia.expect("un acierto siempre tiene distancia");
                let obtenida = resultado.distancia.expect("un acierto siempre tiene distancia");
                assert!(
                    aproximado(obtenida, esperada),
                    "distancia de {:?} = {}, esperado {}",
                    consulta,
                    obtenida,
                    esperada
                );
            } else {
                assert!(resultado.distancia.is_none());
            }
        }

        let e = cache.estadisticas();
        let (entradas, max, exactos, semanticos, fallos, rate, ahorrados, almacenados) =
            CACHE_ESTADISTICAS_CORPUS;
        assert_eq!(e.entradas, entradas);
        assert_eq!(e.max_entradas, max);
        assert_eq!(e.hits_exactos, exactos);
        assert_eq!(e.hits_semanticos, semanticos);
        assert_eq!(e.fallos, fallos);
        assert!(aproximado(e.hit_rate, rate));
        assert_eq!(e.tokens_ahorrados, ahorrados);
        assert_eq!(e.tokens_almacenados, almacenados);
    }

    /// La coincidencia exacta normaliza mayusculas y espacios, y la evacuacion
    /// es por orden de insercion.
    #[test]
    fn cache_exacta_y_evacuacion_fifo() {
        let mut cache = CacheSemanticaW::nuevo(FamiliaDiagonalesW::default(), UMBRAL_SIMILITUD, 2, 0.0);

        cache.guardar("Alfa   Beta", "v1", 10, HashMap::new());
        cache.guardar("gamma delta", "v2", 20, HashMap::new());

        let r = cache.buscar("  alfa beta  ");
        assert!(r.hit);
        assert_eq!(r.kind, "exacto");
        assert_eq!(r.value.as_deref(), Some("v1"));

        cache.guardar("epsilon zeta", "v3", 30, HashMap::new());
        let claves = cache.claves_en_orden();
        assert_eq!(claves.len(), 2);
        assert_eq!(claves[0], "gamma delta", "la mas antigua debe evacuarse");
    }

    /// SHA-256 propio contra los vectores oficiales FIPS 180-4. Es la unica
    /// forma de comprobar `punto_w` sin un crate externo, y conviene que falle
    /// ruidosamente si la implementacion a mano tiene un error.
    #[test]
    fn sha256_vectores_conocidos() {
        fn hex(resumen: &[u8; 32]) -> String {
            let mut s = String::with_capacity(64);
            for b in resumen.iter() {
                s.push_str(&format!("{:02x}", b));
            }
            s
        }
        assert_eq!(
            hex(&sha256(b"")),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            hex(&sha256(b"abc")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            hex(&sha256(
                b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
            )),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
        // Mensaje de mas de 55 bytes: ejercita el segundo bloque de relleno.
        assert_eq!(
            hex(&sha256(
                b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )),
            "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb"
        );
    }

    /// `punto_w` reproduce `hashlib.sha256(token.encode("utf-8"))` tomando los
    /// tres primeros enteros de 32 bits modulo el lado del cubo.
    #[test]
    fn punto_w_como_la_referencia() {
        let familia = FamiliaDiagonalesW::default();
        for token in ["octree", "consult", "optimizar"].iter() {
            let resumen = sha256(token.as_bytes());
            let esperado: Vec<f64> = (0..3)
                .map(|i| {
                    let j = i * 4;
                    let trozo = u32::from_be_bytes([
                        resumen[j],
                        resumen[j + 1],
                        resumen[j + 2],
                        resumen[j + 3],
                    ]);
                    (trozo as f64) % LADO_CUBO
                })
                .collect();
            let p = familia.punto_w(token);
            assert_eq!([p.x, p.y, p.z], esperado[..]);
        }

        // El centroide de una lista vacia es el punto del texto completo.
        let vacio = familia.centroide(&[], "optimizar");
        let directo = familia.punto_w("optimizar");
        assert_eq!(vacio, directo);
    }

    /// La tokenizacion reproduce el detalle fino de `_raiz`: se aplica el
    /// PRIMER sufijo que encaje y solo si `len(token) > len(sufijo) + 3`.
    #[test]
    fn detalles_de_raiz() {
        // "consultas" -> "consult": "as" es el primer sufijo que encaja.
        assert_eq!(raiz("consultas"), "consult");
        // "frecuencias" -> "frecuenci": el sufijo "as" se recorta porque
        // len("frecuencias") = 11 > 5.
        assert_eq!(raiz("frecuencias"), "frecuenci");
        // "cocina" no se toca: "as" no encaja.
        assert_eq!(raiz("cocina"), "cocina");
        // "poda" (4 caracteres) no se recorta con "as" (len > 5 es falso).
        assert_eq!(raiz("poda"), "poda");
        // "prediccion" -> "predic": el primer sufijo que encaja es "cion".
        assert_eq!(raiz("prediccion"), "predic");
        // Guarda de longitud: con exactamente len(sufijo)+3 no se recorta.
        assert_eq!(raiz("abcs"), "abcs");
        assert_eq!(raiz("abcds"), "abcd");
    }

    /// La descomposicion latina quita diacriticos y conserva la letra base.
    #[test]
    fn descomposicion_latina() {
        assert_eq!(descomponer_latin("áéíóúüñ"), "aeiouun");
        assert_eq!(descomponer_latin("ÁÉÍÓÚÜÑ"), "AEIOUUN");
        assert_eq!(descomponer_latin("cafés"), "cafes");
        assert_eq!(descomponer_latin("ascii"), "ascii");
        // Una marca combinante suelta tambien se descarta.
        assert_eq!(descomponer_latin("a\u{301}"), "a");
    }
}

