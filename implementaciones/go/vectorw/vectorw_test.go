// VectorW — nucleo original de Jose Ricardo Mantilla Mantilla (PePiuoX), https://github.com/PePiuoX
//
// Pruebas de conformidad del port de Go contra los vectores compartidos que
// genero la implementacion de referencia en Python.
//
// ESTADO: NO EJECUTADO
//
//	En la maquina donde se escribieron estas pruebas no esta instalado `go`, de
//	modo que NO se han compilado ni ejecutado. Se escribieron para ser la
//	comprobacion exacta del port una vez exista un toolchain:
//
//	    cd implementaciones/go && go test ./...
//
// RUTA DE LOS VECTORES
//
//	El archivo de vectores se lee con la ruta relativa
//	"../../pruebas/vectores_w.json". `go test` ejecuta cada paquete con su
//	directorio como directorio de trabajo, es decir
//
//	    implementaciones/go/vectorw/
//
//	de donde "../../pruebas/vectores_w.json" resuelve a
//
//	    vectorw-dsh-plugin/pruebas/vectores_w.json
//
//	Si se ejecutan los test desde otra ubicacion (por ejemplo con `go test` a
//	traves de un modulo anidado), la ruta deja de ser valida.
package vectorw

import (
	"encoding/json"
	"errors"
	"io/fs"
	"math"
	"os"
	"reflect"
	"testing"
)

// tolerancia es la tolerancia absoluta exigida a los flotantes. Los vectores
// guardan los valores redondeados a 12 decimales y el calculo usa las mismas
// operaciones IEEE-754 que la referencia, asi que 1e-9 deja margen sobrado para
// los redondeos de representacion (el error observado es < 1e-11).
const tolerancia = 1e-9

// rutaVectores es la ruta relativa al corpus de vectores (ver cabecera).
const rutaVectores = "../../pruebas/vectores_w.json"

// ---------------------------------------------------------------------------
// Estructuras del corpus de vectores
// ---------------------------------------------------------------------------

type vectoresConfig struct {
	LadoCubo          float64 `json:"lado_cubo"`
	NEspacios         int     `json:"n_espacios"`
	LongitudDiagonal  float64 `json:"longitud_diagonal"`
	Normalizador      float64 `json:"normalizador"`
	UmbralSimilitud   float64 `json:"umbral_similitud"`
}

type vectoresGeometria struct {
	Bases  []float64   `json:"bases"`
	Signos [][]float64 `json:"signos"`
}

type vectoresPunto struct {
	Punto       []float64 `json:"punto"`
	Componentes []float64 `json:"componentes"`
	Firma       []float64 `json:"firma"`
	Espacios    []int     `json:"espacios"`
}

type vectoresTexto struct {
	Texto       string    `json:"texto"`
	Tokens      []string  `json:"tokens"`
	Coords      []float64 `json:"coords"`
	Componentes []float64 `json:"componentes"`
	Firma       []float64 `json:"firma"`
	Espacios    []int     `json:"espacios"`
}

type vectoresDistancia struct {
	A             string  `json:"a"`
	B             string  `json:"b"`
	Distancia     float64 `json:"distancia"`
	Solapamiento  float64 `json:"solapamiento"`
	Acierto       bool    `json:"acierto"`
}

type vectoresCache struct {
	Consulta        string   `json:"consulta"`
	Hit             bool     `json:"hit"`
	Kind            string   `json:"kind"`
	Query           string   `json:"query"`
	TokensAhorrados int      `json:"tokens_ahorrados"`
	Distancia       *float64 `json:"distancia"`
	Solapamiento    *float64 `json:"solapamiento"`
}

type vectoresEstadisticas struct {
	Entradas          int     `json:"entradas"`
	MaxEntradas       int     `json:"max_entradas"`
	UmbralSimilitud   float64 `json:"umbral_similitud"`
	HitsExactos       int     `json:"hits_exactos"`
	HitsSemanticos    int     `json:"hits_semanticos"`
	Fallos            int     `json:"fallos"`
	HitRate           float64 `json:"hit_rate"`
	TokensAhorrados   int     `json:"tokens_ahorrados"`
	TokensAlmacenados int     `json:"tokens_almacenados"`
}

type vectores struct {
	VersionImplementacion string                          `json:"version_implementacion"`
	Config                vectoresConfig                  `json:"config"`
	Geometria             vectoresGeometria               `json:"geometria"`
	Tokenizacion          map[string][]string             `json:"tokenizacion"`
	Puntos                []vectoresPunto                 `json:"puntos"`
	Textos                []vectoresTexto                 `json:"textos"`
	Distancias            []vectoresDistancia             `json:"distancias"`
	Cache                 []vectoresCache                 `json:"cache"`
	CacheEstadisticas     vectoresEstadisticas            `json:"cache_estadisticas"`
}

// ---------------------------------------------------------------------------
// Utilidades de comparacion
// ---------------------------------------------------------------------------

func igualesFloat(a, b []float64) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if math.Abs(a[i]-b[i]) > tolerancia {
			return false
		}
	}
	return true
}

func igualesInt(a, b []int) bool {
	return reflect.DeepEqual(a, b)
}

func floatCercano(a, b float64) bool {
	return math.Abs(a-b) <= tolerancia
}

func cargarVectores(t *testing.T) *vectores {
	t.Helper()
	datos, err := os.ReadFile(rutaVectores)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			t.Fatalf("no se encontro el corpus de vectores %q; "+
				"ejecute `go test ./...` desde implementaciones/go. err=%v",
				rutaVectores, err)
		}
		t.Fatalf("no se pudo leer %q: %v", rutaVectores, err)
	}
	var v vectores
	if err := json.Unmarshal(datos, &v); err != nil {
		t.Fatalf("JSON invalido en %q: %v", rutaVectores, err)
	}
	if len(v.Tokenizacion) == 0 || len(v.Puntos) == 0 || len(v.Textos) == 0 {
		t.Fatalf("el corpus %q no tiene el contenido esperado", rutaVectores)
	}
	return &v
}

// ---------------------------------------------------------------------------
// Pruebas
// ---------------------------------------------------------------------------

// TestConfigCompartida comprueba que las constantes del port coinciden con las
// que declara el corpus de vectores.
func TestConfigCompartida(t *testing.T) {
	v := cargarVectores(t)

	if v.Config.LadoCubo != LadoCubo {
		t.Errorf("lado del cubo: corpus=%v port=%v", v.Config.LadoCubo, LadoCubo)
	}
	if v.Config.NEspacios != NEspacios {
		t.Errorf("n espacios: corpus=%v port=%v", v.Config.NEspacios, NEspacios)
	}
	if !floatCercano(v.Config.UmbralSimilitud, UmbralSimilitud) {
		t.Errorf("umbral: corpus=%v port=%v", v.Config.UmbralSimilitud, UmbralSimilitud)
	}

	familia := Nuevo(LadoCubo, NEspacios)
	if !floatCercano(familia.Longitud, v.Config.LongitudDiagonal) {
		t.Errorf("longitud: corpus=%v port=%v", v.Config.LongitudDiagonal, familia.Longitud)
	}
	if !floatCercano(familia.Normalizador, v.Config.Normalizador) {
		t.Errorf("normalizador: corpus=%v port=%v", v.Config.Normalizador, familia.Normalizador)
	}
	for i := 0; i < 4; i++ {
		if !floatCercano(familia.bases[i], v.Geometria.Bases[i]) {
			t.Errorf("base[%d]: corpus=%v port=%v", i, v.Geometria.Bases[i], familia.bases[i])
		}
		for j := 0; j < 3; j++ {
			if SignosW[i][j] != v.Geometria.Signos[i][j] {
				t.Errorf("signo[%d][%d]: corpus=%v port=%v",
					i, j, v.Geometria.Signos[i][j], SignosW[i][j])
			}
		}
	}
	if !familia.EsGeometriaCanonica() {
		t.Errorf("la geometria por defecto deberia ser la canonica")
	}
}

// TestTokenizacion comprueba Tokenizar contra cada entrada del corpus.
func TestTokenizacion(t *testing.T) {
	v := cargarVectores(t)

	for texto, esperado := range v.Tokenizacion {
		obtenido := Tokenizar(texto)
		if len(obtenido) == 0 && len(esperado) == 0 {
			continue // [] y nil son equivalentes para la referencia
		}
		if !reflect.DeepEqual(obtenido, esperado) {
			t.Errorf("Tokenizar(%q) =\n  %q\nesperado\n  %q", texto, obtenido, esperado)
		}
	}
}

// TestPuntos comprueba ParametroT/ComponentesDe, FirmaDePunto y EspaciosDe
// sobre los puntos 3D arbitrarios del corpus.
func TestPuntos(t *testing.T) {
	v := cargarVectores(t)
	familia := Nuevo(LadoCubo, NEspacios)

	for i, caso := range v.Puntos {
		if len(caso.Punto) != 3 {
			t.Fatalf("punto[%d] del corpus no tiene 3 coordenadas", i)
		}
		punto := Vec3{X: caso.Punto[0], Y: caso.Punto[1], Z: caso.Punto[2]}

		componentes := familia.ComponentesDe(punto)
		if !igualesFloat(componentes[:], caso.Componentes) {
			t.Errorf("componentes de %v =\n  %v\nesperado\n  %v",
				caso.Punto, componentes, caso.Componentes)
		}
		for k := 0; k < 4; k++ {
			if !floatCercano(familia.ParametroT(k, punto), caso.Componentes[k]) {
				t.Errorf("ParametroT(%d, %v) = %v, esperado %v",
					k, caso.Punto, familia.ParametroT(k, punto), caso.Componentes[k])
			}
		}

		firma := familia.FirmaDePunto(punto)
		if !igualesFloat(firma[:], caso.Firma) {
			t.Errorf("firma de %v =\n  %v\nesperado\n  %v", caso.Punto, firma, caso.Firma)
		}

		espacios := familia.EspaciosDe(punto)
		if !igualesInt(espacios[:], caso.Espacios) {
			t.Errorf("espacios de %v =\n  %v\nesperado\n  %v",
				caso.Punto, espacios, caso.Espacios)
		}
	}
}

// TestTextos comprueba la firma completa de texto: tokens, centroide,
// componentes, firma y espacios.
func TestTextos(t *testing.T) {
	v := cargarVectores(t)
	familia := Nuevo(LadoCubo, NEspacios)

	for _, caso := range v.Textos {
		f := familia.FirmaDeTexto(caso.Texto)

		if len(f.Tokens) == 0 && len(caso.Tokens) == 0 {
			// equivalencia entre nil y lista vacia
		} else if !reflect.DeepEqual(f.Tokens, caso.Tokens) {
			t.Errorf("tokens de %q =\n  %q\nesperado\n  %q", caso.Texto, f.Tokens, caso.Tokens)
		}

		coords := []float64{f.Coords.X, f.Coords.Y, f.Coords.Z}
		if !igualesFloat(coords, caso.Coords) {
			t.Errorf("coords de %q =\n  %v\nesperado\n  %v", caso.Texto, coords, caso.Coords)
		}
		if !igualesFloat(f.Componentes[:], caso.Componentes) {
			t.Errorf("componentes de %q =\n  %v\nesperado\n  %v",
				caso.Texto, f.Componentes, caso.Componentes)
		}
		if !igualesFloat(f.Firma[:], caso.Firma) {
			t.Errorf("firma de %q =\n  %v\nesperado\n  %v", caso.Texto, f.Firma, caso.Firma)
		}
		if !igualesInt(f.Espacios[:], caso.Espacios) {
			t.Errorf("espacios de %q =\n  %v\nesperado\n  %v",
				caso.Texto, f.Espacios, caso.Espacios)
		}

		esperadoVacia := len(caso.Tokens) == 0
		if f.EsVacia != esperadoVacia {
			t.Errorf("es_vacia de %q = %v, esperado %v", caso.Texto, f.EsVacia, esperadoVacia)
		}
	}
}

// TestDistancias comprueba la distancia combinada y su solapamiento.
func TestDistancias(t *testing.T) {
	v := cargarVectores(t)
	familia := Nuevo(LadoCubo, NEspacios)

	for _, caso := range v.Distancias {
		f1 := familia.FirmaDeTexto(caso.A)
		f2 := familia.FirmaDeTexto(caso.B)

		dist, solape := familia.Distancia(f1, f2, InvariantePermutaciones)
		if !floatCercano(dist, caso.Distancia) {
			t.Errorf("distancia(%q, %q) = %v, esperado %v",
				caso.A, caso.B, dist, caso.Distancia)
		}
		if !floatCercano(solape, caso.Solapamiento) {
			t.Errorf("solapamiento(%q, %q) = %v, esperado %v",
				caso.A, caso.B, solape, caso.Solapamiento)
		}
		// La marca `acierto` del corpus es "la distancia no supera el umbral".
		acierto := dist <= UmbralSimilitud
		if acierto != caso.Acierto {
			t.Errorf("acierto(%q, %q) = %v, esperado %v",
				caso.A, caso.B, acierto, caso.Acierto)
		}
	}
}

// TestCache reproduce la secuencia de decisiones de la cache del corpus: se
// guardan todas las entradas menos la ultima y despues se consultan todas.
func TestCache(t *testing.T) {
	v := cargarVectores(t)
	if len(v.Cache) < 2 {
		t.Fatalf("el corpus no tiene suficientes entradas de cache")
	}

	cache := NuevaCache(
		CacheOpcionUmbral(UmbralSimilitud),
		CacheOpcionMaxEntradas(MaxEntradas),
	)
	// Las consultas se guardan con el coste 4200 que uso el generador y que
	// refleja el campo tokens_ahorrados de las entradas exitosas.
	const costeTokens = 4200
	for _, caso := range v.Cache[:len(v.Cache)-1] {
		cache.Guardar(caso.Consulta, "valor:"+caso.Consulta, costeTokens, nil)
	}

	for _, caso := range v.Cache {
		resultado := cache.Buscar(caso.Consulta)
		if resultado.Hit != caso.Hit {
			t.Errorf("hit de %q = %v, esperado %v", caso.Consulta, resultado.Hit, caso.Hit)
			continue
		}
		if resultado.Kind != caso.Kind {
			t.Errorf("kind de %q = %q, esperado %q", caso.Consulta, resultado.Kind, caso.Kind)
			continue
		}
		if resultado.Hit {
			if resultado.Query != caso.Query {
				t.Errorf("query de %q = %q, esperado %q", caso.Consulta, resultado.Query, caso.Query)
			}
			if resultado.TokensAhorrados != caso.TokensAhorrados {
				t.Errorf("tokens_ahorrados de %q = %d, esperado %d",
					caso.Consulta, resultado.TokensAhorrados, caso.TokensAhorrados)
			}
			if caso.Distancia != nil && !floatCercano(resultado.Distancia, *caso.Distancia) {
				t.Errorf("distancia de %q = %v, esperado %v",
					caso.Consulta, resultado.Distancia, *caso.Distancia)
			}
			if caso.Solapamiento != nil && !floatCercano(resultado.Solapamiento, *caso.Solapamiento) {
				t.Errorf("solapamiento de %q = %v, esperado %v",
					caso.Consulta, resultado.Solapamiento, *caso.Solapamiento)
			}
		}
	}

	est := cache.Estadisticas()
	esperada := v.CacheEstadisticas
	if est.Entradas != esperada.Entradas {
		t.Errorf("entradas = %d, esperado %d", est.Entradas, esperada.Entradas)
	}
	if est.MaxEntradas != esperada.MaxEntradas {
		t.Errorf("max_entradas = %d, esperado %d", est.MaxEntradas, esperada.MaxEntradas)
	}
	if est.HitsExactos != esperada.HitsExactos {
		t.Errorf("hits_exactos = %d, esperado %d", est.HitsExactos, esperada.HitsExactos)
	}
	if est.HitsSemanticos != esperada.HitsSemanticos {
		t.Errorf("hits_semanticos = %d, esperado %d", est.HitsSemanticos, esperada.HitsSemanticos)
	}
	if est.Fallos != esperada.Fallos {
		t.Errorf("fallos = %d, esperado %d", est.Fallos, esperada.Fallos)
	}
	if !floatCercano(est.HitRate, esperada.HitRate) {
		t.Errorf("hit_rate = %v, esperado %v", est.HitRate, esperada.HitRate)
	}
	if est.TokensAhorrados != esperada.TokensAhorrados {
		t.Errorf("tokens_ahorrados = %d, esperado %d", est.TokensAhorrados, esperada.TokensAhorrados)
	}
	if est.TokensAlmacenados != esperada.TokensAlmacenados {
		t.Errorf("tokens_almacenados = %d, esperado %d",
			est.TokensAlmacenados, esperada.TokensAlmacenados)
	}
}

// TestCacheSeleccionComparteToken comprueba la regla critica de seleccion: una
// entrada geometricamente mas cercana pero SIN tokens en comun nunca puede
// adelantar a la que si comparte vocabulario.
func TestCacheSeleccionComparteToken(t *testing.T) {
	cache := NuevaCache(CacheOpcionUmbral(UmbralSimilitud))

	// Se guarda una consulta sin ninguna palabra en comun con la consulta de
	// prueba; su distancia geometrica por si sola no decide nada porque el
	// solapamiento es 0.
	cache.Guardar("recetas de cocina vegana con tofu", "irrelevante", 100, nil)

	resultado := cache.Buscar("optimizar consultas vectoriales con octree")
	if resultado.Hit {
		t.Errorf("no deberia haber acierto sin vocabulario compartido: kind=%q dist=%v solape=%v",
			resultado.Kind, resultado.Distancia, resultado.MejorSolapamiento)
	}
	if resultado.Kind != "miss" {
		t.Errorf("kind = %q, esperado miss", resultado.Kind)
	}
	if resultado.MejorDistancia != nil {
		t.Errorf("mejor_distancia = %v, esperado nil (ninguna candidata con solapamiento)",
			*resultado.MejorDistancia)
	}
}

// TestCacheExactoYFIFO comprueba la coincidencia exacta normalizada y la
// evacuacion por orden de insercion.
func TestCacheExactoYFIFO(t *testing.T) {
	cache := NuevaCache(CacheOpcionMaxEntradas(2))

	cache.Guardar("Alfa   Beta", "v1", 10, nil)
	cache.Guardar("gamma delta", "v2", 20, nil)

	// La coincidencia exacta normaliza mayusculas y espacios.
	resultado := cache.Buscar("  alfa beta  ")
	if !resultado.Hit || resultado.Kind != "exacto" {
		t.Fatalf("se esperaba acierto exacto, obtenido hit=%v kind=%q",
			resultado.Hit, resultado.Kind)
	}
	if resultado.Value != "v1" {
		t.Errorf("value = %v, esperado v1", resultado.Value)
	}

	// Una tercera entrada evacua la mas antigua por insercion.
	cache.Guardar("epsilon zeta", "v3", 30, nil)
	if entradas := cache.Entradas(); len(entradas) != 2 {
		t.Fatalf("entradas = %d, esperado 2", len(entradas))
	} else if entradas[0].QueryNorm != "gamma delta" {
		t.Errorf("la entrada mas antigua deberia ser 'gamma delta', es %q", entradas[0].QueryNorm)
	}
}
