# install.ps1 - Instala el plugin VectorW en el perfil de DeepSeek Harness.
#
# Uso:
#   pwsh -File .\install.ps1                            # perfil activo (DSH_PROFILE)
#   pwsh -File .\install.ps1 -Perfil desktop
#   pwsh -File .\install.ps1 -RutaCore "D:\otra\vectorW_py"
#   pwsh -File .\install.ps1 -Desinstalar
#
# Cómo funciona:
#   1. Crea un junction en <perfil>/node_modules/@deepseek-ai/dsh-plugin-vectorw
#      apuntando a esta carpeta, para que el loader de Cordis resuelva el
#      especificador "@deepseek-ai/dsh-plugin-vectorw".
#   2. Añade una entrada al cordis.patch.yml DEL PERFIL (la capa del usuario,
#      que se aplica después de todos los bundles).
#   3. No toca package.json: así un `pnpm install` posterior no rompe el enlace.
#
# El plugin no se copia: editar lib/index.js o bridge_vos.py aquí es suficiente.

[CmdletBinding()]
param(
    [string] $Perfil = $env:DSH_PROFILE,
    [string] $DshHome = $env:DSH_HOME,
    [string] $RutaCore,
    [string] $IdEntrada = 'vectorw-memory',
    [switch] $Copiar,
    [switch] $Desinstalar
)

$ErrorActionPreference = 'Stop'
$NombrePlugin = '@deepseek-ai/dsh-plugin-vectorw'
$RaizPaquete = Split-Path -Parent $MyInvocation.MyCommand.Path

# PowerShell 5.1: '-Encoding UTF8' escribe BOM y puede releer UTF-8 sin BOM como
# ANSI, corrompiendo acentos. Usamos siempre UTF-8 sin BOM de forma explícita.
$Utf8SinBom = New-Object System.Text.UTF8Encoding($false)
function Leer-Texto([string] $ruta) {
    if (-not (Test-Path $ruta)) { return '' }
    return [System.IO.File]::ReadAllText($ruta, $Utf8SinBom)
}
function Escribir-Texto([string] $ruta, [string] $texto) {
    [System.IO.File]::WriteAllText($ruta, $texto, $Utf8SinBom)
}

if (-not $DshHome) { $DshHome = Join-Path $HOME '.dsh' }
if (-not $Perfil) { $Perfil = 'desktop' }
if (-not $RutaCore) { $RutaCore = Join-Path (Split-Path -Parent $RaizPaquete) 'vectorW_py' }

$DirPerfil = Join-Path $DshHome "profiles\$Perfil"
$PatchPerfil = Join-Path $DirPerfil 'cordis.patch.yml'
$NodeModules = Join-Path $DshHome 'profiles\node_modules'
$DirNode = Join-Path $NodeModules '@deepseek-ai'
$Destino = Join-Path $DirNode 'dsh-plugin-vectorw'

# Node resuelve los enlaces a su ruta REAL antes de buscar dependencias. Como
# este plugin vive fuera del árbol del perfil, sus `import` de
# '@deepseek-ai/schemastery' y '@deepseek-ai/dsh-tools' no encontrarían el
# node_modules del perfil. La solución es enlazar ese node_modules junto al
# plugin, de modo que la búsqueda ascendente de Node lo alcance.
$PadrePlugin = Split-Path -Parent $RaizPaquete
$NodeModulesVecino = Join-Path $PadrePlugin 'node_modules'

function New-Enlace([string] $Enlace, [string] $DestinoReal, [string] $Etiqueta) {
    if (Test-Path $Enlace) {
        $existente = Get-Item $Enlace -Force
        if ($existente.LinkType) { [System.IO.Directory]::Delete($Enlace) }
        elseif ($existente.PSIsContainer) { Remove-Item $Enlace -Recurse -Force }
        else { Remove-Item $Enlace -Force }
    }
    try {
        New-Item -ItemType Junction -Path $Enlace -Target $DestinoReal -ErrorAction Stop | Out-Null
        Write-Host "Junction $Etiqueta`: $Enlace -> $DestinoReal" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "Junction $Etiqueta no disponible: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

if (-not (Test-Path $PatchPerfil)) {
    throw "No existe el perfil '$Perfil' ($PatchPerfil). Abre DSH una vez o usa -Perfil."
}
if (-not (Test-Path (Join-Path $RutaCore 'vectorW_6.py'))) {
    Write-Host "AVISO: no se encontro vectorW_6.py en '$RutaCore'." -ForegroundColor Yellow
    Write-Host '       El plugin arrancara en modo degradado (cache por hash, sin nucleo W).' -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Desinstalacion
# ---------------------------------------------------------------------------
if ($Desinstalar) {
    $lineas = (Leer-Texto $PatchPerfil) -split "`r?`n"
    $salida = New-Object System.Collections.Generic.List[string]
    $omitir = $false
    foreach ($linea in $lineas) {
        if ($linea -match "^\s*-\s*id:\s*$([regex]::Escape($IdEntrada))\s*$") { $omitir = $true; continue }
        if ($omitir) {
            if ($linea -match '^\s*-\s') { $omitir = $false } else { continue }
        }
        $salida.Add($linea)
    }
    Escribir-Texto $PatchPerfil ($salida -join "`n")

    if (Test-Path $Destino) {
        $item = Get-Item $Destino -Force
        if ($item.LinkType) { [System.IO.Directory]::Delete($Destino) }
        else { Remove-Item $Destino -Recurse -Force }
    }
    Write-Host 'Plugin VectorW desinstalado. Reinicia DeepSeek Harness.' -ForegroundColor Cyan
    exit 0
}

# ---------------------------------------------------------------------------
# 1. Enlace del paquete en el perfil
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $DirNode | Out-Null

$enlazado = $false
if (-not $Copiar) {
    # Quitar siempre el destino previo: si fuera un enlace, New-Item falla.
    if (Test-Path $Destino) {
        $previo = Get-Item $Destino -Force
        if ($previo.LinkType) { [System.IO.Directory]::Delete($Destino) }
        else { Remove-Item $Destino -Recurse -Force }
    }
    $enlazado = New-Enlace $Destino $RaizPaquete 'plugin'
}

if ($Copiar -or -not $enlazado) {
    if (Test-Path $Destino) { Remove-Item $Destino -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Destino | Out-Null
    # Solo lo que el loader y el puente necesitan: lib/, el puente, el núcleo
    # vendorizado, el manifiesto y las licencias.
    Copy-Item (Join-Path $RaizPaquete 'lib') -Destination $Destino -Recurse -Force
    Copy-Item (Join-Path $RaizPaquete 'vendor') -Destination $Destino -Recurse -Force
    foreach ($archivo in @('bridge_vos.py', 'package.json', 'README.md', 'LICENSE.md')) {
        Copy-Item (Join-Path $RaizPaquete $archivo) -Destination $Destino -Force
    }
    Write-Host "Copiado: $Destino (sin enlace: re-ejecuta install.ps1 tras cada cambio)" -ForegroundColor Yellow

    # Con copia, el plugin vive dentro del perfil y ya ve node_modules: no
    # hace falta el enlace vecino.
    if (Test-Path $NodeModulesVecino) {
        $ron = Get-Item $NodeModulesVecino -Force
        if ($ron.LinkType) { [System.IO.Directory]::Delete($NodeModulesVecino) }
    }
} else {
    # Datos de diagnóstico: se conserva el node_modules de este proyecto si ya
    # existía y no es un enlace, para no destruir dependencias del usuario.
    if (Test-Path $NodeModulesVecino) {
        $ron = Get-Item $NodeModulesVecino -Force
        if (-not $ron.LinkType) {
            $contenido = @(Get-ChildItem $NodeModulesVecino -Force -ErrorAction SilentlyContinue)
            if ($contenido.Count -gt 0) {
                Write-Host "AVISO: $NodeModulesVecino ya existe con contenido y no es un enlace." -ForegroundColor Yellow
                Write-Host '       El plugin usara ese node_modules; verifica que contenga @deepseek-ai/*.' -ForegroundColor Yellow
            } else {
                Remove-Item $NodeModulesVecino -Recurse -Force
                New-Enlace $NodeModulesVecino $NodeModules 'dependencias' | Out-Null
            }
        } elseif ($ron.Target -ne $NodeModules) {
            [System.IO.Directory]::Delete($NodeModulesVecino)
            New-Enlace $NodeModulesVecino $NodeModules 'dependencias' | Out-Null
        }
    } else {
        New-Enlace $NodeModulesVecino $NodeModules 'dependencias' | Out-Null
    }
}

# ---------------------------------------------------------------------------
# 2. Entrada en cordis.patch.yml del perfil
# ---------------------------------------------------------------------------
$patch = Leer-Texto $PatchPerfil
if ($patch -match "id:\s*$([regex]::Escape($IdEntrada))\b") {
    Write-Host "La entrada '$IdEntrada' ya existe en cordis.patch.yml" -ForegroundColor DarkGray
} else {
    $entrada = @(
        '',
        '# VectorW (vOS v6.0): cache semantica de firma W 4D + predictor de consultas.',
        '# Nucleo de Jose Ricardo Mantilla Mantilla (PePiuoX) - https://github.com/PePiuoX',
        "- id: $IdEntrada",
        "  name: `"$NombrePlugin`"",
        '  config:',
        "    rutaCore: `"$($RutaCore -replace '\\', '/')`"",
        '    umbralSimilitud: 0.15',
        '    maxEntradas: 2000',
        '    ordenMarkov: 2'
    ) -join "`n"
    $separador = if ($patch.EndsWith("`n") -or $patch.Length -eq 0) { '' } else { "`n" }
    Escribir-Texto $PatchPerfil ($patch + $separador + $entrada + "`n")
    Write-Host "Entrada '$IdEntrada' anadida a cordis.patch.yml" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Listo. Siguientes pasos:' -ForegroundColor Cyan
Write-Host '  1. Reinicia DeepSeek Harness (el loader monta el plugin al arrancar).'
Write-Host "  2. Ajusta rutaCore en $PatchPerfil si vectorW_py esta en otra ruta."
Write-Host '  3. Verifica con la herramienta vector_stats.'
