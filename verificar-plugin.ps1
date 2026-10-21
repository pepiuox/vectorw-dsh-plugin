# verificar-plugin.ps1 — Diagnóstico e instrucciones de instalación del plugin VectorW.
#
# IMPORTANTE: este script YA NO escribe en el perfil de DeepSeek Harness.
#
# La instalación correcta la hace DeepSeek Harness con `plugin_manager`
# (acción `install_bundle`), que añade el bundle al `package.json` del perfil,
# ejecuta pnpm y aplica el patch del bundle como una capa de primera clase.
# Escribir a mano `cordis.patch.yml` o `node_modules` es lo que provocaba el
# fallo histórico: la fila quedaba creada pero sin habilitar, y además Node no
# podía resolver los imports del plugin.
#
# Uso:
#   pwsh -File .\verificar-plugin.ps1
#
# Salida: un diagnóstico con el estado real y los pasos exactos que faltan.

[CmdletBinding()]
param(
    [string] $Perfil = $env:DSH_PROFILE,
    [string] $DshHome = $env:DSH_HOME,
    [string] $RutaCore
)

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$NombrePaquete = '@deepseek-ai/dsh-plugin-vectorw'

if (-not $DshHome) { $DshHome = Join-Path $HOME '.dsh' }
if (-not $Perfil) { $Perfil = 'desktop' }
if (-not $RutaCore) { $RutaCore = Join-Path (Split-Path -Parent $Raiz) 'vectorW_py' }

$ok = 0
$fallos = 0
function Bien([string] $m) { Write-Host "  OK    $m" -ForegroundColor Green; $script:ok++ }
function Mal([string] $m) { Write-Host "  FALLO $m" -ForegroundColor Red; $script:fallos++ }
function Aviso([string] $m) { Write-Host "  AVISO $m" -ForegroundColor Yellow }

Write-Host "Diagnóstico del plugin VectorW"
Write-Host ("=" * 64)

# --- 1. Paquete -------------------------------------------------------------
Write-Host "`n1. Paquete y manifiesto"
$pkgRuta = Join-Path $Raiz 'package.json'
if (-not (Test-Path $pkgRuta)) { Mal 'no existe package.json'; exit 1 }
$pkg = Get-Content $pkgRuta -Raw | ConvertFrom-Json
Bien "package.json legible (name=$($pkg.name), version=$($pkg.version))"

if ($pkg.dsh.bundle.patch) { Bien "declara dsh.bundle.patch = $($pkg.dsh.bundle.patch)" }
else { Mal 'no declara dsh.bundle.patch: no es un bundle y DSH no lo podrá instalar' }

$patchBundle = Join-Path $Raiz $pkg.dsh.bundle.patch
if (Test-Path $patchBundle) { Bien 'el patch del bundle existe' } else { Mal "falta $patchBundle" }

if (Test-Path (Join-Path $Raiz 'lib\index.js')) { Bien 'lib/index.js presente' } else { Mal 'falta lib/index.js' }
if (Test-Path (Join-Path $Raiz 'bridge_vos.py')) { Bien 'bridge_vos.py presente' } else { Mal 'falta bridge_vos.py' }

# Checks de sintaxis
$node = Join-Path $DshHome 'dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
if (Test-Path $node) {
    $null = & $node --check (Join-Path $Raiz 'lib\index.js') 2>&1
    if ($LASTEXITCODE -eq 0) { Bien 'lib/index.js: sintaxis válida' } else { Mal 'lib/index.js: error de sintaxis' }
} else { Aviso 'no se encontró el Node de DSH; se omite el chequeo de sintaxis' }

# --- 2. Núcleo VectorW ------------------------------------------------------
Write-Host "`n2. Núcleo VectorW"
$vendor = Join-Path $Raiz 'vendor\vectorW_py\vectorW_6.py'
if (Test-Path $vendor) { Bien 'núcleo vendorizado presente (vendor/vectorW_py/vectorW_6.py)' }
else { Aviso 'sin núcleo vendorizado; el plugin quedará en modo degradado' }
if (Test-Path (Join-Path $RutaCore 'vectorW_6.py')) {
    Bien "núcleo de usuario disponible en rutaCore ($RutaCore)"
} else {
    Aviso "rutaCore no contiene vectorW_6.py ($RutaCore); se usará el vendorizado"
}

# --- 3. Instalación en el perfil -------------------------------------------
Write-Host "`n3. Instalación en el perfil '$Perfil'"
$perfilDir = Join-Path $DshHome "profiles\$Perfil"
$perfilPkg = Join-Path $perfilDir 'package.json'

if (-not (Test-Path $perfilPkg)) {
    Aviso "no existe el perfil '$Perfil' ($perfilDir). Abre DSH una vez o usa -Perfil."
} else {
    $pj = Get-Content $perfilPkg -Raw | ConvertFrom-Json
    $enBundles = @($pj.dsh.profile.bundles) -contains $NombrePaquete
    $enDeps = $pj.dependencies.PSObject.Properties.Name -contains $NombrePaquete
    if ($enBundles) { Bien "el bundle está declarado en dsh.profile.bundles" }
    else { Mal 'el bundle NO está en dsh.profile.bundles: falta instalarlo' }
    if ($enDeps) { Bien 'la dependencia está declarada en package.json' }
    else { Aviso 'la dependencia no está declarada (install_bundle la añade)' }

    # Enlace materializado por pnpm
    $enlace = Join-Path $DshHome "profiles\$Perfil\node_modules\$($NombrePaquete -replace '/', '\')"
    if (Test-Path $enlace) { Bien "el paquete está instalado en el perfil" }
    else {
        $enlaceAlt = Join-Path $DshHome "profiles\node_modules\$($NombrePaquete -replace '/', '\')"
        if (Test-Path $enlaceAlt) { Bien 'el paquete está instalado (node_modules hoisted del perfil)' }
        else { Mal 'el paquete no está materializado en node_modules del perfil' }
    }

    # Enlace de dependencias para instalaciones por enlace local (link:)
    $vecino = Join-Path (Split-Path -Parent $Raiz) 'node_modules'
    if ($enBundles) {
        if (Test-Path $vecino) {
            $item = Get-Item $vecino -Force
            if ($item.LinkType) {
                Bien "enlace de dependencias presente (necesario con instalación por enlace local)"
            } else {
                Aviso "$vecino existe y no es un enlace; revisa que contenga @deepseek-ai/*"
            }
        } else {
            Aviso 'no hay enlace de dependencias: si la instalación fue por enlace local, los imports del plugin fallarán'
            Aviso 'solución: instalar por nombre publicado, o crear el enlace node_modules junto al paquete'
        }
    }
}

# --- 4. Versión del runtime -------------------------------------------------
Write-Host "`n4. Compatibilidad de versión (causa del fallo histórico)"
$runtime = $null
$rt = Join-Path $DshHome 'dsh-runtimes\dsh-primary-runtime\runtime.json'
if (Test-Path $rt) { $runtime = (Get-Content $rt -Raw | ConvertFrom-Json).desktopVersion }
if ($runtime) { Bien "runtime de DSH detectado: $runtime" } else { Aviso 'no se pudo leer la versión del runtime' }
$req = $pkg.peerDependencies.'@deepseek-ai/dsh-tools'
if ($req) {
    Write-Host "        peer declarado @deepseek-ai/dsh-tools: $req"
    Write-Host '        DSH rechaza ACTIVAR el plugin si este rango no admite el runtime.' -ForegroundColor DarkGray
    Write-Host '        Si cambias de versión de DSH, actualiza ese rango; si no, el plugin' -ForegroundColor DarkGray
    Write-Host '        aparecerá como no habilitable aunque el código sea correcto.' -ForegroundColor DarkGray
} else { Aviso 'no declara peerDependencies: revisa la compatibilidad con el runtime' }

# --- Resumen y pasos --------------------------------------------------------
Write-Host "`n" + ("=" * 64)
if ($fallos -eq 0) {
    Write-Host "RESULTADO: $ok comprobaciones OK, sin fallos." -ForegroundColor Green
} else {
    Write-Host "RESULTADO: $fallos fallos, $ok OK." -ForegroundColor Red
}

Write-Host @"

Cómo se instala (camino soportado)
----------------------------------
No se debe escribir a mano en el perfil. Dentro de DeepSeek Harness, pide:

    instala el bundle de "$Raiz"

El agente llamará a plugin_manager con install_bundle y la ruta absoluta. Eso:
  1. añade el paquete al package.json del perfil y ejecuta pnpm;
  2. aplica cordis.patch.yml del bundle como una capa de primera clase;
  3. deja la fila habilitada y gestionable desde Ajustes > Plugins.

Después, verifica con la herramienta vector_stats y con:
    Ajustes > Plugins  (el plugin debe aparecer habilitado)

Si quieres usar tu copia del núcleo VectorW en vez de la vendorizada, pon la
ruta en la configuración del plugin (rutaCore); por defecto se usa vendor/.
"@ -ForegroundColor Cyan

if ($fallos -gt 0) { exit 1 }
