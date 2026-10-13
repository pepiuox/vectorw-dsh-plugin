// VectorW — nucleo original de Jose Ricardo Mantilla Mantilla (PePiuoX), https://github.com/PePiuoX
//
// Package vectorw es un port de referencia, en Go, del algoritmo de firma W 4D
// y de la cache semantica de VectorW.
//
// ATRIBUCION
//
//	Arquitectura y autor del nucleo VectorW original:
//	    Jose Ricardo Mantilla Mantilla (PePiuoX)
//	    https://github.com/PePiuoX
//	    Licencia LAMC v1.0 / LULA v1.1
//
// FUENTE DE VERDAD
//
//	Este paquete es un port literal de:
//	    implementaciones/python/vectorw_w.py
//	Esa implementacion de Python es la referencia VERIFICADA (su geometria esta
//	comprobada punto por punto contra el nucleo original en
//	pruebas/verificar_equivalencia.py) y es la que genero los vectores
//	compartidos pruebas/vectores_w.json que consume vectorw_test.go.
//
// ESTADO: NO COMPILADO NI VERIFICADO
//
//	En la maquina donde se escribio este archivo no estan instalados ni `go` ni
//	`gofmt`, de modo que el codigo NO ha sido compilado, formateado ni ejecutado
//	jamas. Esta escrito para ser autocontenido y logicamente correcto, pero
//	cualquier afirmacion sobre su comportamiento en ejecucion esta SIN VERIFICAR.
//	Para verificarlo:
//	    cd implementaciones/go && go test ./...
//
// DEPENDENCIAS
//
//	Ninguna: solo la biblioteca estandar de Go. En particular NO se usa
//	golang.org/x/text/unicode/norm. La descomposicion NFD de los diacriticos
//	latinos se hace con una tabla explicita (ver descomponerLatin), porque la
//	referencia Python solo produce diacriticos latinos al aplicar
//	unicodedata.normalize("NFKD", ...) sobre texto latino.
package vectorw

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Version del algoritmo portado (coincide con vectorw_w.VERSION de Python).
const Version = "1.1.0"

// ---------------------------------------------------------------------------
// Configuracion
// ---------------------------------------------------------------------------

// ConfigW contiene las constantes del espacio de memoria VectorW.
//
// Los valores reproducen los del nucleo v6.0: cubo de lado 1024 y 8 espacios por
// diagonal (32 espacios de resolucion total).
type ConfigW struct{}

const (
	// LadoCubo es la arista del cubo de memoria.
	LadoCubo = 1024.0
	// NEspacios es el numero de espacios W por diagonal.
	NEspacios = 8
	// UmbralSimilitud es la distancia maxima aceptada como acierto semantico.
	UmbralSimilitud = 0.15
	// MaxEntradas es el numero maximo de entradas de la cache por defecto.
	MaxEntradas = 2000
	// TTLSegundos es el tiempo de vida por defecto (0 = sin caducidad).
	TTLSegundos = 0.0
	// InvariantePermutaciones hace la comparacion geometrica invariante al
	// orden de las 4 diagonales.
	InvariantePermutaciones = true
	// PesoGeometria y PesoSolapamiento ponderan la distancia combinada.
	PesoGeometria    = 0.35
	PesoSolapamiento = 1.3
)

// ---------------------------------------------------------------------------
// Tokenizacion
// ---------------------------------------------------------------------------

// PalabrasVacias es el conjunto exacto de palabras vacias de la referencia
// Python (copiado literalmente de _PALABRAS_VACIAS).
var PalabrasVacias = map[string]struct{}{
	// Espanol
	"a": {}, "al": {}, "algo": {}, "algunas": {}, "algunos": {}, "ante": {},
	"antes": {}, "aqui": {}, "asi": {}, "aun": {}, "aunque": {}, "bien": {},
	"cada": {}, "como": {}, "con": {}, "contra": {}, "cual": {}, "cuando": {},
	"de": {}, "del": {}, "desde": {}, "donde": {}, "dos": {}, "el": {},
	"ella": {}, "ellas": {}, "ellos": {}, "en": {}, "entre": {}, "era": {},
	"eran": {}, "es": {}, "esa": {}, "esas": {}, "ese": {}, "eso": {},
	"esos": {}, "esta": {}, "estaba": {}, "estado": {}, "estas": {}, "este": {},
	"esto": {}, "estos": {}, "fue": {}, "fueron": {}, "ha": {}, "hace": {},
	"hacia": {}, "han": {}, "hasta": {}, "hay": {}, "la": {}, "las": {},
	"le": {}, "les": {}, "lo": {}, "los": {}, "mas": {}, "me": {}, "mi": {},
	"mis": {}, "mucho": {}, "muy": {}, "nada": {}, "ni": {}, "no": {},
	"nos": {}, "nosotros": {}, "nuestra": {}, "nuestro": {}, "o": {}, "os": {},
	"otra": {}, "otro": {}, "para": {}, "pero": {}, "poco": {}, "por": {},
	"porque": {}, "que": {}, "quien": {}, "se": {}, "sea": {}, "segun": {},
	"ser": {}, "si": {}, "sin": {}, "sobre": {}, "son": {}, "su": {},
	"sus": {}, "tal": {}, "tambien": {}, "tanto": {}, "te": {}, "tiene": {},
	"tienen": {}, "todo": {}, "todos": {}, "tu": {}, "tus": {}, "un": {},
	"una": {}, "uno": {}, "unos": {}, "y": {}, "ya": {},
	// Ingles
	"the": {}, "is": {}, "at": {}, "which": {}, "on": {}, "an": {}, "and": {},
	"are": {}, "as": {}, "be": {}, "been": {}, "but": {}, "by": {}, "can": {},
	"for": {}, "from": {}, "has": {}, "have": {}, "how": {}, "in": {},
	"into": {}, "it": {}, "its": {}, "of": {}, "or": {}, "that": {},
	"their": {}, "there": {}, "these": {}, "this": {}, "to": {}, "was": {},
	"were": {}, "what": {}, "when": {}, "where": {}, "who": {}, "will": {},
	"with": {}, "your": {},
}

// Sufijos son los sufijos que se recortan para tolerar plurales, genero y
// conjugaciones simples. El ORDEN es significativo: se aplica el primero de la
// lista que encaje (copiado literalmente de _SUFIJOS en la referencia Python).
var Sufijos = []string{
	"ciones", "cion", "mente", "ados", "adas", "ado", "ada",
	"idos", "idas", "ido", "ida", "es", "os", "as", "s",
}

// descomposicionLatina es la tabla de descomposicion NFD (canonica) de los
// caracteres latinos precompuestos. Cada entrada es la secuencia de runas por
// la que Python sustituye el caracter al hacer
// unicodedata.normalize("NFKD", ...); despues se descartan las runas
// combinantes (unicode.Mn), que es exactamente lo que hace _sin_acentos.
//
// Se incluyen las formas de Latin-1 Supplement y Latin Extended-A/B que pueden
// aparecer en texto latin, no solo las cinco vocales acentuadas espanolas.
var descomposicionLatina = map[rune][]rune{
	// Vocales con acento agudo
	'á': {'a', '\u0301'}, 'é': {'e', '\u0301'}, 'í': {'i', '\u0301'},
	'ó': {'o', '\u0301'}, 'ú': {'u', '\u0301'}, 'ý': {'y', '\u0301'},
	'Á': {'A', '\u0301'}, 'É': {'E', '\u0301'}, 'Í': {'I', '\u0301'},
	'Ó': {'O', '\u0301'}, 'Ú': {'U', '\u0301'}, 'Ý': {'Y', '\u0301'},
	// Vocales con acento grave
	'à': {'a', '\u0300'}, 'è': {'e', '\u0300'}, 'ì': {'i', '\u0300'},
	'ò': {'o', '\u0300'}, 'ù': {'u', '\u0300'},
	'À': {'A', '\u0300'}, 'È': {'E', '\u0300'}, 'Ì': {'I', '\u0300'},
	'Ò': {'O', '\u0300'}, 'Ù': {'U', '\u0300'},
	// Vocales con circunflejo
	'â': {'a', '\u0302'}, 'ê': {'e', '\u0302'}, 'î': {'i', '\u0302'},
	'ô': {'o', '\u0302'}, 'û': {'u', '\u0302'},
	'Â': {'A', '\u0302'}, 'Ê': {'E', '\u0302'}, 'Î': {'I', '\u0302'},
	'Ô': {'O', '\u0302'}, 'Û': {'U', '\u0302'},
	// Vocales con dieresis
	'ä': {'a', '\u0308'}, 'ë': {'e', '\u0308'}, 'ï': {'i', '\u0308'},
	'ö': {'o', '\u0308'}, 'ü': {'u', '\u0308'}, 'ÿ': {'y', '\u0308'},
	'Ä': {'A', '\u0308'}, 'Ë': {'E', '\u0308'}, 'Ï': {'I', '\u0308'},
	'Ö': {'O', '\u0308'}, 'Ü': {'U', '\u0308'}, 'Ÿ': {'Y', '\u0308'},
	// Vocal con tilde
	'ã': {'a', '\u0303'}, 'õ': {'o', '\u0303'},
	'Ã': {'A', '\u0303'}, 'Õ': {'O', '\u0303'},
	// Vocal con macron / breve / caron
	'ā': {'a', '\u0304'}, 'ē': {'e', '\u0304'}, 'ī': {'i', '\u0304'},
	'ō': {'o', '\u0304'}, 'ū': {'u', '\u0304'},
	'Ă': {'A', '\u0306'}, 'ă': {'a', '\u0306'},
	'ǎ': {'a', '\u030c'}, 'ě': {'e', '\u030c'}, 'ǐ': {'i', '\u030c'},
	'ǒ': {'o', '\u030c'}, 'ǔ': {'u', '\u030c'},
	// Enye (en minuscula y mayuscula)
	'ñ': {'n', '\u0303'}, 'Ñ': {'N', '\u0303'},
	// C con cedilla / agudo
	'ç': {'c', '\u0327'}, 'Ç': {'C', '\u0327'},
	'ć': {'c', '\u0301'}, 'Ć': {'C', '\u0301'},
	'č': {'c', '\u030c'}, 'Č': {'C', '\u030c'},
	// S, Z, N con acentos
	'ś': {'s', '\u0301'}, 'Ś': {'S', '\u0301'},
	'š': {'s', '\u030c'}, 'Š': {'S', '\u030c'},
	'ź': {'z', '\u0301'}, 'Ź': {'Z', '\u0301'},
	'ż': {'z', '\u0307'}, 'Ż': {'Z', '\u0307'},
	'ž': {'z', '\u030c'}, 'Ž': {'Z', '\u030c'},
	'ń': {'n', '\u0301'}, 'Ń': {'N', '\u0301'},
	// Diacriticos de Europa central que NFKD descompone con signo
	'ő': {'o', '\u030b'}, 'ű': {'u', '\u030b'},
	'Ő': {'O', '\u030b'}, 'Ű': {'U', '\u030b'},
	// Letras compuestas: NFKD las descompone en dos letras base
	'æ': {'a', 'e'}, 'Æ': {'A', 'E'},
	'œ': {'o', 'e'}, 'Œ': {'O', 'E'},
	'ß': {'s', 's'}, // solo por completitud; strings.ToLower no lo produce
}

// descomponerLatin aplica la descomposicion NFD a cada runa de s y elimina las
// runas combinantes, replicando el comportamiento de _sin_acentos en la
// referencia Python para texto latino.
func descomponerLatin(s string) string {
	// Camino rapido: si no hay nada que descomponer ni combinar, se devuelve
	// la misma cadena.
	ascii := true
	for i := 0; i < len(s); i++ {
		if s[i] >= utf8.RuneSelf {
			ascii = false
			break
		}
	}
	if ascii {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		if descompuesto, ok := descomposicionLatina[r]; ok {
			for _, d := range descompuesto {
				if unicode.Is(unicode.Mn, d) {
					continue // se descarta el diacritico
				}
				b.WriteRune(d)
			}
			continue
		}
		if unicode.Is(unicode.Mn, r) {
			continue // diacritico suelto: tambien se descarta
		}
		b.WriteRune(r)
	}
	return b.String()
}

// Raiz devuelve la raiz aproximada de un token, conservadora y determinista.
// Reproduce _raiz de la referencia: se recorta el PRIMER sufijo de Sufijos que
// encaje y cumpla len(token) > len(sufijo)+3.
func Raiz(token string) string {
	for _, sufijo := range Sufijos {
		if len(token) > len(sufijo)+3 && strings.HasSuffix(token, sufijo) {
			return token[:len(token)-len(sufijo)]
		}
	}
	return token
}

// esPalabraContinua indica si una runa es un caracter de palabra Unicode, es
// decir el equivalente de \w en Python (letras, numeros y guion bajo).
//
// Nota de fidelidad: la expresion regular de la referencia usa [\w...], que en
// Python tambien incluye digitos no decimales (por ejemplo el superindice '2'
// de U+00B2). Por eso aqui se usa unicode.IsNumber y no unicode.IsDigit.
func esPalabraContinua(r rune) bool {
	return r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r)
}

// Tokenizar extrae los tokens significativos de un texto.
//
// Aplica minusculas, quita acentos (descomposicion NFD y descarte de las runas
// combinantes), descarta palabras vacias y palabras de menos de 3 caracteres,
// reduce a raiz y elimina duplicados conservando el orden de primera aparicion.
//
// La determinacion de la raiz debe ser identica en todos los lenguajes porque
// de ella depende que las firmas coincidan.
//
//   - texto: texto arbitrario (consulta, pregunta, tarea).
//   - retorna: lista de tokens con raiz, sin duplicados.
func Tokenizar(texto string) []string {
	if texto == "" {
		return nil
	}
	// La referencia hace unicodedata.normalize("NFKD", texto.lower()): primero
	// minusculas, despues descomposicion. strings.ToLower coincide con
	// str.lower de Python para el texto latino que maneja este algoritmo
	// (la unica diferencia conocida es 'İ' U+0130).
	texto = strings.ToLower(texto)

	salida := make([]string, 0, 8)
	vistos := make(map[string]struct{})
	// Los tokens de la referencia son siempre ASCII despues de quitar acentos,
	// de modo que usar el indice de bytes como clave es equivalente.
	for _, crudo := range camposDePalabra(texto) {
		normalizado := descomponerLatin(crudo)
		if len(normalizado) < 3 {
			continue
		}
		if _, vacia := PalabrasVacias[normalizado]; vacia {
			continue
		}
		raiz := Raiz(normalizado)
		if _, repetido := vistos[raiz]; repetido {
			continue
		}
		vistos[raiz] = struct{}{}
		salida = append(salida, raiz)
	}
	return salida
}

// camposDePalabra devuelve las secuencias maximales de caracteres de palabra de
// s, equivalente a _RE_TOKEN.findall(texto) en la referencia Python.
func camposDePalabra(s string) []string {
	var campos []string
	inicio := -1
	for i, r := range s {
		if esPalabraContinua(r) {
			if inicio < 0 {
				inicio = i
			}
			continue
		}
		if inicio >= 0 {
			campos = append(campos, s[inicio:i])
			inicio = -1
		}
	}
	if inicio >= 0 {
		campos = append(campos, s[inicio:])
	}
	return campos
}

// ---------------------------------------------------------------------------
// Firma W 4D
// ---------------------------------------------------------------------------

// Vec3 es un punto 3D dentro del cubo de memoria.
type Vec3 struct {
	X float64
	Y float64
	Z float64
}

// FirmaW es la firma W 4D de un texto, con su procedencia.
//
// Campos:
//   - Tokens: tokens significativos usados.
//   - Coords: centroide 3D de los tokens dentro del cubo.
//   - Componentes: las 4 proyecciones t sobre las diagonales (sin normalizar).
//   - Firma: las 4 proyecciones normalizadas por la longitud de la diagonal.
//   - Espacios: indice de espacio W (0..n-1) en cada diagonal.
//   - EsVacia: true si el texto no aporto ningun token.
type FirmaW struct {
	Tokens      []string
	Coords      Vec3
	Componentes [4]float64
	Firma       [4]float64
	Espacios    [4]int
	EsVacia     bool
}

// FirmaWComoDict devuelve una representacion JSON-serializable, equivalente a
// FirmaW.como_dict() de la referencia.
func (f FirmaW) ComoDict() map[string]any {
	return map[string]any{
		"tokens":      append([]string{}, f.Tokens...),
		"coords":      []float64{f.Coords.X, f.Coords.Y, f.Coords.Z},
		"componentes": f.Componentes[:],
		"firma":       f.Firma[:],
		"espacios":    f.Espacios[:],
		"es_vacia":    f.EsVacia,
	}
}

// FamiliaDiagonalesW contiene las 4 diagonales del cubo de memoria y la
// aritmetica de firmas W 4D.
//
// Reproduce exactamente la geometria del nucleo original. Cada diagonal es una
// recta dirigida entre dos vertices opuestos del cubo y la proyeccion de un
// punto sobre ella es la forma afin verificada contra el nucleo:
//
//	t_k(p) = ( b_k · L + s_k · p ) / sqrt(3)
//
// con s_k los coeficientes de la diagonal (±1) y b_k su termino constante:
//
//	k   diagonal   b_k              s_k
//	1   W1 (+++)   0                (+1, +1, +1)
//	2   W2 (-++)   1+sqrt(3)         (-1, +1, +1)
//	3   W3 (+-+)   1+sqrt(3)         (+1, -1, +1)
//	4   W4 (++-)   1+sqrt(3)         (+1, +1, -1)
//
// La firma normalizada es t_k / (L·sqrt(3)) = (b_k + s_k · p') / 3, con
// p' = p/L. Por eso los componentes 2..4 arrancan en ~0.9107 (= (1+sqrt(3))/3)
// y no en 0: el nucleo situa el inicio de esas tres rectas fuera del cubo
// (2797.62 con lado 1024), asi que cualquier punto del interior proyecta un
// valor alto. El recorrido de la firma es:
//
//	(0,0,0)  -> (0.000, 0.911, 0.911, 0.911)
//	(L,L,L)  -> (1.000, 1.244, 1.244, 1.244)
//
// Es una propiedad del nucleo, no un error; por eso la firma W 4D sirve para
// clasificar y comparar, no como medida absoluta. La tabla se obtuvo midiendo
// el nucleo y se verifica punto por punto (a dos tamanos de cubo) en
// pruebas/verificar_equivalencia.py.
type FamiliaDiagonalesW struct {
	// Lado es la arista del cubo.
	Lado float64
	// NEspacios es el numero de espacios W por diagonal (>= 1).
	NEspacios int
	// Longitud es la longitud de la diagonal (L·sqrt(3)); tambien es el
	// normalizador de la firma.
	Longitud float64
	// Raiz3 es sqrt(3).
	Raiz3 float64
	// Normalizador es el divisor de la firma (igual a Longitud).
	Normalizador float64

	bases [4]float64
}

// SignosW son los coeficientes s_k de las 4 diagonales, en el orden
// W1(+++), W2(-++), W3(+-+), W4(++-).
var SignosW = [4][3]float64{
	{1, 1, 1},
	{-1, 1, 1},
	{1, -1, 1},
	{1, 1, -1},
}

// Nuevo construye la familia de diagonales para un cubo de lado `lado` y
// `nEspacios` espacios por diagonal.
//
// Valores no validos se corrigen como en la referencia: nEspacios < 1 pasa a 1
// y el lado <= 0 pasa al lado canonico (1024). Este ultimo caso no existe en
// Python (que no lo comprueba) y se anade aqui solo para evitar una geometria
// degenerada.
func Nuevo(lado float64, nEspacios int) *FamiliaDiagonalesW {
	if math.IsNaN(lado) || lado <= 0 {
		lado = LadoCubo
	}
	if nEspacios < 1 {
		nEspacios = 1
	}
	raiz3 := math.Sqrt(3.0)
	f := &FamiliaDiagonalesW{
		Lado:      lado,
		NEspacios: nEspacios,
		Raiz3:     raiz3,
	}
	f.Longitud = f.Lado * raiz3
	f.Normalizador = f.Longitud
	f.bases = [4]float64{0, 1 + raiz3, 1 + raiz3, 1 + raiz3}
	return f
}

// EsGeometriaCanonica indica si el lado del cubo es el del nucleo (1024).
//
// La forma afin escala con el lado del cubo, asi que este modulo coincide con
// el nucleo en cualquier tamano (verificado a 1024 y 32000). La marca se
// conserva para poder distinguir la configuracion por defecto.
func (f *FamiliaDiagonalesW) EsGeometriaCanonica() bool {
	return math.Abs(f.Lado-1024.0) < 1e-9
}

// PuntoW devuelve el punto 3D determinista de un token dentro del cubo.
//
// Es la proyeccion de un hash criptografico, no una posicion semantica real: lo
// que importa es que sea determinista, uniforme y estable, para que dos textos
// con los mismos tokens den el mismo centroide.
//
//   - token: token ya normalizado.
//   - retorna: terna (x, y, z) en [0, lado).
func (f *FamiliaDiagonalesW) PuntoW(token string) Vec3 {
	resumen := sha256.Sum256([]byte(token))
	hexresumen := hex.EncodeToString(resumen[:])
	// La referencia toma las subcadenas 0:8, 8:16 y 16:24 del hexadecimal, es
	// decir los primeros 12 bytes del resumen, de 4 en 4.
	lado := int64(math.Trunc(f.Lado))
	if lado <= 0 {
		lado = 1
	}
	x := float64(parseHex32(hexresumen[0:8]) % lado)
	y := float64(parseHex32(hexresumen[8:16]) % lado)
	z := float64(parseHex32(hexresumen[16:24]) % lado)
	return Vec3{X: x, Y: y, Z: z}
}

// parseHex32 interpreta 8 digitos hexadecimales como un entero sin signo.
func parseHex32(s string) int64 {
	v, err := strconv.ParseUint(s, 16, 32)
	if err != nil {
		// No puede ocurrir: sha256 siempre produce 16 digitos hex por bloque
		// de 8, y aqui se le pasan exactamente 8.
		return 0
	}
	return int64(v)
}

// Centroide es el punto medio de los puntos W de los tokens.
//
// Si no hay tokens se usa el punto del texto completo, para que una consulta
// vacia siga teniendo una firma valida.
func (f *FamiliaDiagonalesW) Centroide(tokens []string, texto string) Vec3 {
	if len(tokens) == 0 {
		return f.PuntoW(texto)
	}
	var x, y, z float64
	for _, token := range tokens {
		p := f.PuntoW(token)
		x += p.X
		y += p.Y
		z += p.Z
	}
	n := float64(len(tokens))
	return Vec3{X: x / n, Y: y / n, Z: z / n}
}

// ParametroT es la proyeccion escalar del punto sobre la diagonal `indice`.
//
// Forma lineal verificada punto por punto contra el nucleo:
//
//	t_k(p) = ( b_k · L + s_k · p ) / sqrt(3)
//
// donde s_k son los coeficientes (±1) de la diagonal y b_k su termino
// constante: 0 en W1 y 1+sqrt(3) ~ 2.7321 en W2, W3 y W4. Ese desplazamiento es
// lo que hace que las tres ultimas ramas de la firma empiecen en
// (1+sqrt(3))/3 ~ 0.9107 en lugar de en 0.
//
//   - indice: 0..3, en el orden W1, W2, W3, W4.
//   - punto: terna de coordenadas dentro del cubo.
//   - retorna: la proyeccion sin normalizar.
func (f *FamiliaDiagonalesW) ParametroT(indice int, punto Vec3) float64 {
	if indice < 0 || indice > 3 {
		return math.NaN()
	}
	signos := SignosW[indice]
	proyeccion := signos[0]*punto.X + signos[1]*punto.Y + signos[2]*punto.Z
	return (f.bases[indice]*f.Lado + proyeccion) / f.Raiz3
}

// ComponentesDe devuelve las 4 proyecciones t sin normalizar.
func (f *FamiliaDiagonalesW) ComponentesDe(punto Vec3) [4]float64 {
	var componentes [4]float64
	for i := 0; i < 4; i++ {
		componentes[i] = f.ParametroT(i, punto)
	}
	return componentes
}

// FirmaDePunto devuelve la firma W 4D normalizada de un punto 3D.
//
// Equivale a FamiliaDiagonales.calcular_firma_normalizada del nucleo: divide
// cada proyeccion por el normalizador (L·sqrt(3)).
func (f *FamiliaDiagonalesW) FirmaDePunto(punto Vec3) [4]float64 {
	componentes := f.ComponentesDe(punto)
	var firma [4]float64
	for i, t := range componentes {
		firma[i] = t / f.Normalizador
	}
	return firma
}

// EspaciosDe devuelve el indice de espacio W (0..n-1) de cada diagonal para un
// punto.
//
// El nucleo acota la proyeccion a [0, longitud] (la diagonal completa) antes de
// repartirla en espacios, no al normalizador. La conversion a entero trunca
// hacia cero, igual que int() en Python.
func (f *FamiliaDiagonalesW) EspaciosDe(punto Vec3) [4]int {
	n := f.NEspacios
	var salida [4]int
	for i := 0; i < 4; i++ {
		t := f.ParametroT(i, punto)
		tAcotado := math.Max(0.0, math.Min(t, f.Longitud))
		indice := int(tAcotado / f.Longitud * float64(n))
		if indice > n-1 {
			indice = n - 1
		}
		salida[i] = indice
	}
	return salida
}

// FirmaDeTexto devuelve la firma W 4D completa de un texto.
//
//   - texto: consulta o tarea a indexar.
//   - retorna: una FirmaW con tokens, centroide, firma y espacios.
func (f *FamiliaDiagonalesW) FirmaDeTexto(texto string) FirmaW {
	tokens := Tokenizar(texto)
	coords := f.Centroide(tokens, texto)
	componentes := f.ComponentesDe(coords)
	var firma [4]float64
	for i, t := range componentes {
		firma[i] = t / f.Normalizador
	}
	return FirmaW{
		Tokens:      tokens,
		Coords:      coords,
		Componentes: componentes,
		Firma:       firma,
		Espacios:    f.EspaciosDe(coords),
		EsVacia:     len(tokens) == 0,
	}
}

// -- distancias -------------------------------------------------------------

// DistanciaGeometrica es la distancia euclidea directa entre dos firmas W 4D.
func (f *FamiliaDiagonalesW) DistanciaGeometrica(f1, f2 [4]float64) float64 {
	var suma float64
	for i := 0; i < 4; i++ {
		d := f1[i] - f2[i]
		suma += d * d
	}
	return math.Sqrt(suma)
}

// DistanciaPermutaciones es la distancia minima sobre las 24 permutaciones de
// la segunda firma.
//
// Hace la comparacion invariante al orden de las diagonales, de modo que un
// punto que cae simetrico respecto a un eje no se penalice. Es sensiblemente
// mas caro (24 distancias en lugar de 1).
func (f *FamiliaDiagonalesW) DistanciaPermutaciones(f1, f2 [4]float64) float64 {
	mejor := math.Inf(1)
	// 4! = 24 permutaciones de los 4 componentes, enumeradas igual que en la
	// referencia: a, b, c y el indice restante d = 6-a-b-c.
	for a := 0; a < 4; a++ {
		for b := 0; b < 4; b++ {
			if b == a {
				continue
			}
			for c := 0; c < 4; c++ {
				if c == a || c == b {
					continue
				}
				d := 6 - a - b - c
				perm := [4]float64{f2[a], f2[b], f2[c], f2[d]}
				dist := f.DistanciaGeometrica(f1, perm)
				if dist < mejor {
					mejor = dist
				}
			}
		}
	}
	return mejor
}

// Distancia es la distancia combinada W 4D mas solapamiento de vocabulario.
//
// La geometria sola produce falsos aciertos: dos consultas sin ninguna palabra
// en comun pueden caer cerca por azar. El solapamiento (Jaccard sobre las raices
// de los tokens) actua de penalizacion, y sin vocabulario compartido la
// distancia no puede bajar del umbral.
//
//   - f1, f2: firmas a comparar.
//   - invariantePermutaciones: si es true se usa DistanciaPermutaciones.
//   - retorna: (distancia, solapamiento).
func (f *FamiliaDiagonalesW) Distancia(
	f1, f2 FirmaW,
	invariantePermutaciones bool,
) (float64, float64) {
	var geometrica float64
	if invariantePermutaciones {
		geometrica = f.DistanciaPermutaciones(f1.Firma, f2.Firma)
	} else {
		geometrica = f.DistanciaGeometrica(f1.Firma, f2.Firma)
	}

	conjunto1 := conjuntoDe(f1.Tokens)
	conjunto2 := conjuntoDe(f2.Tokens)
	if len(conjunto1) == 0 || len(conjunto2) == 0 {
		return geometrica, 0.0
	}

	interseccion := 0
	for token := range conjunto1 {
		if _, ok := conjunto2[token]; ok {
			interseccion++
		}
	}
	union := len(conjunto1) + len(conjunto2) - interseccion
	var solapamiento float64
	if union != 0 {
		solapamiento = float64(interseccion) / float64(union)
	}
	penalizacion := PesoGeometria + PesoSolapamiento*(1.0-solapamiento)
	return geometrica * penalizacion, solapamiento
}

// conjuntoDe construye el conjunto (sin repeticiones) de los tokens.
func conjuntoDe(tokens []string) map[string]struct{} {
	conjunto := make(map[string]struct{}, len(tokens))
	for _, token := range tokens {
		conjunto[token] = struct{}{}
	}
	return conjunto
}

// ---------------------------------------------------------------------------
// Cache semantica
// ---------------------------------------------------------------------------

// EntradaCache es una entrada guardada en la cache.
type EntradaCache struct {
	// Query es la consulta original tal como se guardo.
	Query string
	// QueryNorm es la consulta normalizada (minusculas y espacios colapsados).
	QueryNorm string
	// Valor es el resultado cacheado.
	Valor any
	// Tokens es el coste estimado en tokens de obtener el valor.
	Tokens int
	// Firma es la firma W 4D de la consulta normalizada.
	Firma FirmaW
	// Metadata son metadatos libres.
	Metadata map[string]any
	// Timestamp es el instante de insercion (segundos desde la época).
	Timestamp float64
	// Expira es el instante de caducidad, o 0 si no caduca.
	Expira float64
}

// ResultadoCache es el resultado de Buscar, tanto si hay acierto como si no.
//
// En un acierto (Hit == true) son validos Query, Value, TokensAhorrados,
// Distancia, Solapamiento, FirmaCache, Espacios, Metadata y AntiguedadSegs.
// En un fallo (Hit == false) son validos Firma y TokensConsulta (la firma y los
// tokens de la consulta buscada), Candidatos y MejorSolapamiento, y
// MejorDistancia solo si alguna candidata compartio al menos un token.
type ResultadoCache struct {
	Hit            bool
	Kind           string
	Query          string
	Value          any
	Firma          [4]float64
	Espacios       [4]int
	TokensConsulta []string

	Distancia         float64
	Solapamiento      float64
	Umbral            float64
	Candidatos        int
	MejorDistancia    *float64
	MejorSolapamiento float64
	QueryConsultada   string
	TokensAhorrados   int
	FirmaCache        [4]float64
	Metadata          map[string]any
	AntiguedadSegs    float64
}

// EstadisticasCache son las metricas de acierto y ahorro acumulado.
type EstadisticasCache struct {
	Entradas          int
	MaxEntradas       int
	UmbralSimilitud   float64
	HitsExactos       int
	HitsSemanticos    int
	Fallos            int
	HitRate           float64
	TokensAhorrados   int
	TokensAlmacenados int
}

// CacheSemanticaW es una cache de pares consulta->valor con recuperacion por
// similitud W 4D.
//
// Sustituye la coincidencia literal de cadenas por coincidencia semantica: una
// consulta reformulada recupera la respuesta ya calculada, que es el ahorro real
// de tokens.
//
// Diferencias de representacion respecto a la referencia Python (judgement
// call, documentada): Python indexa las entradas por la tupla de 4 flotantes de
// la firma, que es hashable. Go no permite usar una clave con flotantes, asi que
// aqui se usa la consulta normalizada como clave. El efecto observable es el
// mismo que en Python y ademas evita colisiones por redondeo: dos consultas que
// se normalizan a la misma cadena tienen exactamente la misma firma y solo
// pueden proceder de la misma consulta.
type CacheSemanticaW struct {
	Familia     *FamiliaDiagonalesW
	Umbral      float64
	MaxEntradas int
	TTL         float64

	entradas []*EntradaCache

	HitsExactos       int
	HitsSemanticos    int
	Fallos            int
	TokensAhorrados   int
	TokensAlmacenados int
}

// CacheOpcion configura una CacheSemanticaW.
type CacheOpcion func(*CacheSemanticaW)

// CacheOpcionUmbral fija el umbral de similitud.
func CacheOpcionUmbral(umbral float64) CacheOpcion {
	return func(c *CacheSemanticaW) { c.Umbral = umbral }
}

// CacheOpcionMaxEntradas fija el numero maximo de entradas.
func CacheOpcionMaxEntradas(maxEntradas int) CacheOpcion {
	return func(c *CacheSemanticaW) { c.MaxEntradas = maxEntradas }
}

// CacheOpcionTTL fija el tiempo de vida en segundos (0 = sin caducidad).
func CacheOpcionTTL(ttlSegundos float64) CacheOpcion {
	return func(c *CacheSemanticaW) { c.TTL = ttlSegundos }
}

// CacheOpcionFamilia usa una familia de diagonales concreta.
func CacheOpcionFamilia(familia *FamiliaDiagonalesW) CacheOpcion {
	return func(c *CacheSemanticaW) {
		if familia != nil {
			c.Familia = familia
		}
	}
}

// NuevaCache construye una cache semantica. Sin opciones usa los valores por
// defecto de ConfigW (umbral 0.15, 2000 entradas, sin TTL).
func NuevaCache(opciones ...CacheOpcion) *CacheSemanticaW {
	c := &CacheSemanticaW{
		Familia:     Nuevo(LadoCubo, NEspacios),
		Umbral:      UmbralSimilitud,
		MaxEntradas: MaxEntradas,
		TTL:         TTLSegundos,
	}
	for _, opcion := range opciones {
		opcion(c)
	}
	return c
}

// NormalizarCache es la normalizacion usada para la coincidencia exacta:
// minusculas y espacios colapsados.
func NormalizarCache(texto string) string {
	return strings.Join(strings.Fields(strings.ToLower(texto)), " ")
}

// Buscar busca una consulta equivalente en la cache.
//
// Primero intenta coincidencia exacta normalizada y despues similitud
// semantica; nunca acepta una entrada si no comparte al menos un token.
func (c *CacheSemanticaW) Buscar(consulta string) ResultadoCache {
	normalizada := NormalizarCache(consulta)
	firma := c.Familia.FirmaDeTexto(normalizada)
	ahora := ahoraSegundos()

	// 1) coincidencia exacta. Las expiradas se recogen y se eliminan despues
	// de recorrer, igual que en la referencia.
	var expiradas []int
	for i := 0; i < len(c.entradas); i++ {
		entrada := c.entradas[i]
		if c.TTL > 0 && entrada.Expira > 0 && entrada.Expira < ahora {
			expiradas = append(expiradas, i)
			continue
		}
		if entrada.QueryNorm == normalizada {
			// move_to_end: la entrada exacta pasa al final (politica LRU).
			c.entradas = append(c.entradas[:i], c.entradas[i+1:]...)
			c.entradas = append(c.entradas, entrada)
			c.HitsExactos++
			c.TokensAhorrados += entrada.Tokens
			return c.vista(entrada, "exacto", 0.0, 1.0, consulta, firma)
		}
	}
	c.eliminarIndices(expiradas)

	// 2) coincidencia semantica
	//
	// Solo se consideran candidatas las entradas que comparten al menos un
	// token. Filtrar *antes* de elegir la mas cercana es imprescindible: si se
	// elige primero la de menor distancia y luego se exige solapamiento, una
	// entrada sin nada en comun puede adelantarse a la que si coincide
	// (distancia pequena por azar) y convertir un acierto valido en un fallo.
	mejorDist := math.Inf(1)
	var mejorSolape float64
	var mejorEntrada *EntradaCache
	for _, entrada := range c.entradas {
		if c.TTL > 0 && entrada.Expira > 0 && entrada.Expira < ahora {
			continue
		}
		dist, solape := c.Familia.Distancia(firma, entrada.Firma, InvariantePermutaciones)
		if solape <= 0 {
			continue
		}
		if dist < mejorDist {
			mejorDist, mejorSolape, mejorEntrada = dist, solape, entrada
		}
	}

	if mejorEntrada != nil && mejorDist <= c.Umbral {
		c.HitsSemanticos++
		c.TokensAhorrados += mejorEntrada.Tokens
		return c.vista(mejorEntrada, "semantico", mejorDist, mejorSolape, consulta, firma)
	}

	c.Fallos++
	resultado := ResultadoCache{
		Hit:               false,
		Kind:              "miss",
		Query:             consulta,
		Firma:             firma.Firma,
		Espacios:          firma.Espacios,
		TokensConsulta:    firma.Tokens,
		Umbral:            c.Umbral,
		Candidatos:        len(c.entradas),
		MejorSolapamiento: mejorSolape,
	}
	if mejorEntrada != nil {
		dist := mejorDist
		resultado.MejorDistancia = &dist
	}
	return resultado
}

// Guardar guarda un resultado asociado a una consulta.
//
//   - consulta: consulta que produjo el resultado.
//   - valor: resultado a cachear.
//   - tokens: coste estimado en tokens de obtenerlo (para medir el ahorro).
//   - metadata: metadatos libres.
func (c *CacheSemanticaW) Guardar(
	consulta string,
	valor any,
	tokens int,
	metadata map[string]any,
) GuardadoCache {
	normalizada := NormalizarCache(consulta)
	firma := c.Familia.FirmaDeTexto(normalizada)
	if tokens < 0 {
		tokens = 0
	}
	if metadata == nil {
		metadata = map[string]any{}
	}

	// Se elimina cualquier entrada previa con la misma clave (en Python, la
	// misma tupla de firma sobrescribe la entrada) y luego se evacua la mas
	// antigua mientras no quepa una entrada mas. El limite se aplica tambien a
	// la clave repetida, igual que el bucle while de la referencia.
	for i := range c.entradas {
		if c.entradas[i].QueryNorm == normalizada {
			c.entradas = append(c.entradas[:i], c.entradas[i+1:]...)
			break
		}
	}
	for len(c.entradas) >= c.MaxEntradas {
		if len(c.entradas) == 0 {
			break
		}
		// popitem(last=False): se descarta la entrada mas antigua. Se copia el
		// resto a un slice nuevo para no retener el array original.
		c.entradas = append([]*EntradaCache(nil), c.entradas[1:]...)
	}

	ahora := ahoraSegundos()
	entrada := &EntradaCache{
		Query:     consulta,
		QueryNorm: normalizada,
		Valor:     valor,
		Tokens:    tokens,
		Firma:     firma,
		Metadata:  metadata,
		Timestamp: ahora,
	}
	if c.TTL > 0 {
		entrada.Expira = ahora + c.TTL
	}
	c.entradas = append(c.entradas, entrada) // move_to_end
	c.TokensAlmacenados += tokens

	return GuardadoCache{
		Stored:   true,
		Query:    consulta,
		Firma:    firma.Firma,
		Espacios: firma.Espacios,
		Tokens:   tokens,
		Entradas: len(c.entradas),
	}
}

// GuardadoCache es el acuse de Guardar.
type GuardadoCache struct {
	Stored   bool
	Query    string
	Firma    [4]float64
	Espacios [4]int
	Tokens   int
	Entradas int
}

// Estadisticas devuelve las metricas de acierto y ahorro acumulado.
func (c *CacheSemanticaW) Estadisticas() EstadisticasCache {
	total := c.HitsExactos + c.HitsSemanticos + c.Fallos
	var tasa float64
	if total != 0 {
		tasa = float64(c.HitsExactos+c.HitsSemanticos) / float64(total)
	}
	return EstadisticasCache{
		Entradas:          len(c.entradas),
		MaxEntradas:       c.MaxEntradas,
		UmbralSimilitud:   c.Umbral,
		HitsExactos:       c.HitsExactos,
		HitsSemanticos:    c.HitsSemanticos,
		Fallos:            c.Fallos,
		HitRate:           tasa,
		TokensAhorrados:   c.TokensAhorrados,
		TokensAlmacenados: c.TokensAlmacenados,
	}
}

// Limpiar vacia la cache y devuelve cuantas entradas habia.
func (c *CacheSemanticaW) Limpiar() int {
	cantidad := len(c.entradas)
	c.entradas = nil
	return cantidad
}

// Entradas devuelve una copia de las entradas en orden de insercion (mas
// antigua primero). Es util para inspeccion y pruebas.
func (c *CacheSemanticaW) Entradas() []EntradaCache {
	copia := make([]EntradaCache, 0, len(c.entradas))
	for _, entrada := range c.entradas {
		copia = append(copia, *entrada)
	}
	return copia
}

// vista construye el resultado de un acierto.
func (c *CacheSemanticaW) vista(
	entrada *EntradaCache,
	tipo string,
	dist float64,
	solape float64,
	consultada string,
	firma FirmaW,
) ResultadoCache {
	return ResultadoCache{
		Hit:               true,
		Kind:              tipo,
		Query:             entrada.Query,
		QueryConsultada:   consultada,
		Value:             entrada.Valor,
		TokensAhorrados:   entrada.Tokens,
		Distancia:         dist,
		Solapamiento:      solape,
		Umbral:            c.Umbral,
		FirmaCache:        entrada.Firma.Firma,
		Espacios:          entrada.Firma.Espacios,
		Metadata:          entrada.Metadata,
		AntiguedadSegs:    ahoraSegundos() - entrada.Timestamp,
		Firma:             firma.Firma,
		TokensConsulta:    firma.Tokens,
		Candidatos:        len(c.entradas),
		MejorSolapamiento: solape,
	}
}

// eliminarIndices quita las posiciones indicadas (en orden creciente).
func (c *CacheSemanticaW) eliminarIndices(indices []int) {
	if len(indices) == 0 {
		return
	}
	quitar := make(map[int]struct{}, len(indices))
	for _, i := range indices {
		quitar[i] = struct{}{}
	}
	restantes := make([]*EntradaCache, 0, len(c.entradas)-len(indices))
	for i, entrada := range c.entradas {
		if _, fuera := quitar[i]; fuera {
			continue
		}
		restantes = append(restantes, entrada)
	}
	c.entradas = restantes
}

// ahoraSegundos devuelve el tiempo actual en segundos con fraccion, como
// time.time() en Python.
func ahoraSegundos() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}

// FormatearFirma es una ayuda de depuracion que reproduce el __repr__ de
// Python: firma redondeada a 6 decimales y espacios.
func (f FirmaW) FormatearFirma() string {
	return fmt.Sprintf("FirmaW(firma=%s, espacios=%v)", formatearFloats(f.Firma), f.Espacios)
}

// formatearFloats redondea a 6 decimales para la representacion textual.
func formatearFloats(valores [4]float64) string {
	partes := make([]string, 0, len(valores))
	for _, v := range valores {
		partes = append(partes, strconv.FormatFloat(math.Round(v*1e6)/1e6, 'g', -1, 64))
	}
	return "[" + strings.Join(partes, " ") + "]"
}
