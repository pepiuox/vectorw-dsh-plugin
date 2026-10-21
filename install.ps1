# install.ps1 — OBSOLETO. No instala nada a propósito.
#
# La versión anterior de este script creaba un enlace en node_modules y escribía
# a mano una fila en el cordis.patch.yml del perfil. Ese enfoque causaba dos
# fallos reales:
#
#   1. La fila quedaba CREADA pero NO HABILITADA, y DSH la reportaba como
#      "incompatible" por el rango de peerDependencies. Resultado: el plugin
#      aparecía en el perfil pero no se podía habilitar.
#   2. Node no resolvía los imports del plugin al estar fuera del perfil.
#
# El camino soportado es dejar que DeepSeek Harness instale el bundle con
# `plugin_manager` (acción `install_bundle`), que además deja la fila
# habilitada y gestionable desde Ajustes > Plugins.
#
# Uso correcto:
#
#   Dentro de DeepSeek Harness, pide al agente:
#       instala el bundle de "<ruta absoluta a esta carpeta>"
#
#   Después, verifica el estado con:
#       pwsh -File .\verificar-plugin.ps1
#
# Los scripts que sí son útiles:
#   verificar-plugin.ps1   diagnóstico de instalación y compatibilidad
#   pruebas/               batería de verificación del algoritmo y del montaje

[CmdletBinding()]
param([switch] $Forzar)

Write-Host 'install.ps1 está obsoleto: escribir a mano el perfil provoca que el plugin' -ForegroundColor Yellow
Write-Host 'quede deshabilitado y que Node no resuelva sus imports.' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Instala desde dentro de DeepSeek Harness, pidiendo:' -ForegroundColor Cyan
Write-Host "    instala el bundle de `"$((Split-Path -Parent $MyInvocation.MyCommand.Path))`"" -ForegroundColor White
Write-Host ''
Write-Host 'Y luego verifica con:' -ForegroundColor Cyan
Write-Host '    pwsh -File .\verificar-plugin.ps1' -ForegroundColor White
Write-Host ''

if (-not $Forzar) {
    Write-Host 'No se ha modificado ningún archivo.' -ForegroundColor Green
    exit 0
}

# Escape explícito para quien sepa lo que hace.
Write-Host 'Ejecutando el diagnóstico (no escribe nada):' -ForegroundColor DarkGray
& (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'verificar-plugin.ps1')
