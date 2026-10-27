> **MOBA2** es el nombre del proyecto (servidor + parches). La aplicación que se analiza y
> parchea es el fan-port **MOBA2** (`<paquete de la app>` v1.1, distribuida por
> APKVISION). Los identificadores técnicos de la app —paquete, claves `net.*`,
> `online.*`, textos `CLAVE_*` y ficheros `*_english.json`— se conservan tal cual porque
> son parte del binario original.

# MOBA2 — servidor propio + parches para «MOBA2» (fan port)

Servidor LAN con estadísticas (MMR, héroes, historial) y sistema de parcheo de la APK
`<paquete de la app>` v1.1 para apuntarla a tu propio backend.

## Descargas

| Qué | Dónde |
|---|---|
| APK original `moba-fan-make-v1.1.apk` (518 MB) | Google Drive: https://drive.google.com/file/d/19gtSXaINFGl1WHcSkknaS_tojj2yhsbn/view |
| Misma APK como *release asset* | https://github.com/almaguersosamax-ui/moba2/releases/tag/v1.1 |
| Proyecto completo (servidor + parches) | Drive › carpeta **MOBA2**: https://drive.google.com/drive/folders/17skIiLofOLvKWQje5P9Sw1cYs_JAmA9x |

SHA-256 de la APK: `16df8b634cb7a3e19fed8660b0cb05c263879bc2a8c921385be51b323d2a0be1`
MD5: `87faa2df9bc3462cfaff120ca243b7f2`

## Arranque rápido

```bash
python server.py --host-ip 192.168.1.180 --trace logs/trace.jsonl   # API + panel en :8080
python seed_demo.py --url http://127.0.0.1:8080                     # datos de ejemplo
python -m unittest discover -s tests -v                             # 14 pruebas
```

Panel: `http://IP:8080/` · API: `/v1/*` (compatible con `OnlineService` del cliente).

## Parchear la APK

```bash
python patch_moba2.py --apk moba-fan-make-v1.1.apk --ip 192.168.1.105 \
  --apktool apktool.jar --signer uber-apk-signer.jar --es lang/es.json --allow-http
```

- `--es lang/es.json` — paquete de idioma español (UI, tienda, HUD).
- `--allow-http` — parchea `libunity.so` (`insecureHttpOption=AlwaysAllowed`) para permitir `http://`.
- URL larga (p. ej. un túnel HTTPS) soportada: el reescritor de metadata crece el blob de literales.
- Verificación al final: hashes de `language.json`, URL nueva presente, URL original ausente.

## Diagnóstico

```bash
python doctor.py --url http://192.168.1.105:8080 --apk dist/moba2-patched-*.apk
```
Comprueba IPs locales, servidor, puerto, contenido de la APK y el parche de `libunity.so`.

## Estado

| Pieza | Estado |
|---|---|
| Cuentas por dispositivo, nombres, perfiles | ✅ |
| Salas (código de 4 letras, ticket Base64, host = IP del anfitrión) | ✅ |
| Ingesta de reportes, ELO/MMR, estadísticas, panel | ✅ (14 pruebas) |
| Parche de URL + español + `libunity` | ✅ |
| Ticket `ConnectTicket` v2 (AES+MAC) | 🟠 estructura recuperada; pendiente confirmar cabecera |

## Requisitos

Python 3.9+ (solo stdlib), Java 8+ para el parcheo, `apktool.jar` y `uber-apk-signer.jar`
(no incluidos por tamaño; descárgalos de sus releases).

