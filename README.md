# MOBA2 — servidor propio + parches para «Dota 2 Mobile» (fan port)

Servidor LAN con estadísticas (MMR, héroes, historial) y sistema de parcheo de la APK
`com.temka.dota2mobile` v1.1 para apuntarla a tu propio backend.

## Arranque rápido

```bash
python server.py --host-ip 192.168.1.180 --trace logs/trace.jsonl   # API + panel en :8080
python seed_demo.py --url http://127.0.0.1:8080                     # datos de ejemplo
python -m unittest discover -s tests -v                             # 14 pruebas
```

Panel: `http://IP:8080/` · API: `/v1/*` (compatible con `OnlineService` del cliente).

## Parchear la APK

```bash
python patch_dota2m.py --apk Dota-2-Mobile-v1.1-APKVISION.apk --ip 192.168.1.105 \
  --apktool apktool.jar --signer uber-apk-signer.jar --es lang/es.json --allow-http
```

- `--es lang/es.json` — paquete de idioma español (UI, tienda, HUD).
- `--allow-http` — parchea `libunity.so` (`insecureHttpOption=AlwaysAllowed`) para permitir `http://`.
- URL larga (p. ej. un túnel HTTPS) soportada: el reescritor de metadata crece el blob de literales.
- Verificación al final: hashes de `language.json`, URL nueva presente, URL original ausente.

## Diagnóstico

```bash
python doctor.py --url http://192.168.1.105:8080 --apk dist/dota2mobile-patched-*.apk
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

## Aviso

Proyecto para uso privado entre amigos. La app original usa contenido de Valve y es un port
no oficial: no redistribuir ni monetizar.
