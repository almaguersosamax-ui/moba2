"""Constantes del protocolo del cliente que NO se pueden renombrar.

Son cadenas literales que viajan en la petición HTTP o nombres de fichero dentro de la
APK: si se cambian, el servidor deja de entender al cliente (o no encuentra los datos).
Se aíslan aquí para que no aparezcan repartidas por el código.
"""

# Cabeceras del reporte de partida firmado (las envía el cliente tal cual).
SIGNATURE_HEADER = "X-Dota-Signature"
TIMESTAMP_HEADER = "X-Dota-Timestamp"

# Fichero de localización dentro de assets/GameData/localization/ (nombre real del APK).
LOCALE_FILE_EN = "dota_english.json"
