# Servidor propio LAN + estadísticas para «MOBA2»

Sí se puede, y es más fácil de lo que parece: **el servidor de partida ya está dentro del teléfono**.
Este documento es el resultado del análisis estático de la APK v1.1 (`com.temka.dota2mobile`) y el plan
para levantar tu propio backend con amigos y estadísticas.

---

## 1. Cómo funciona el multijugador (lo que hay en el binario)

| Pieza | Evidencia en `dump.cs` | Significado |
|---|---|---|
| Servidor de partida en el cliente | `Dota.Gameplay.MatchServer`, `MatchHost`, `MatchSetup`, `MatchConfig` | El **teléfono que hospeda simula la partida**. No hay servidor de juego dedicado que emular. |
| Transporte | `LiteNetPipe` sobre **LiteNetLib** (UDP), `INetPipe`, `LoopbackNet` | Tráfico UDP directo entre dispositivos. |
| Parámetros fijos | `NetConfig`: `Protocol = 6`, `DefaultPort = 27015`, `ConnectionKey = "moba2"`, `Mtu = 1164`, `MaxMembers = 16`, `DisconnectTimeoutMs = 15000` | Puerto y handshake conocidos: **27015/udp**. |
| Salas | `LobbyState` (`HostMember`, `Difficulty`, `Code`, `Members`), `LobbyMember` (`Member`, `Name`, `Slot`, `Ready`, `Connected`), `LobbyCodec`, `LobbyCmdKind` (`SetSlot`, `SetReady`, `SetDifficulty`, `Start`) | La sala es un código de 6 caracteres + estado de slots. |
| Integridad | `NetHandshake`, `NetGuard` (`ValidCommand`, `ValidRules`, `CleanName`, `SameSecret`), `AntiCheat`/`AntiCheatConfig` | Validación de comandos y anti-cheat del lado del host. |
| Servicio online | `OnlineService` → `POST /v1/play`, `/v1/lobbies/join` devuelven `PlayResp { host, port, ticket, sessionKey, expiresAt, lobby, rejoin }` | **El backend solo sirve para descubrir el host y emitir el ticket.** El juego en sí no pasa por ahí. |

**Conclusión:** un servidor propio no necesita simular el juego. Solo tiene que responder
«el host está en `IP:27015`, aquí tienes el ticket» y recoger los reportes de partida.

---

## 2. API que el cliente espera (reconstruida)

Base detectada: `https://177-3-221-114.sslip.io` (único endpoint del binario).

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| POST | `/v1/auth/device` | `{deviceId, secret, name}` | `{userId, name, token, expiresAt}` |
| GET | `/v1/me` | — | `{userId, name, nextRename, nameSet}` |
| POST/PUT | `/v1/me/name` | `{name}` | `{name, problem, ok}` |
| GET | `/v1/names/check?n=` | — | `{name, problem, ok}` |
| PUT | `/v1/me/profile` | `{avatarHero}` | perfil |
| GET | `/v1/users/me/profile` | — | perfil |
| GET | `/v1/users/me/heroes` | — | estadísticas por héroe |
| POST | `/v1/play` | `{name, version, protocol}` | `PlayResp` |
| POST | `/v1/lobbies` | idem | `PlayResp` |
| POST | `/v1/lobbies/join` | `{code, name, version, protocol}` | `PlayResp` |
| GET | `/v1/matches?user=me&limit=N` | — | historial |
| POST | *url de reportes* | reporte de partida firmado | 2xx |

Errores: `Problem {title, status}`. Autenticación: `Authorization: Bearer <token>`.

### Reportes de partida (de aquí salen las estadísticas)
- `MatchReporter.Start(dir, url, key)` + `MatchReporter.Queue`, `MatchReportQueue` (con `RetryDelays`, `MaxAge`, `Dir`): **la cola guarda en disco y reintenta**, así que funciona sin internet y sube después.
- Firma: `MatchReportSignature` → cabeceras **`X-Dota-Timestamp`** y **`X-Dota-Signature`** con prefijo `v1=` y MAC de 32 bytes (HMAC-SHA256 con la clave del servidor).
- Claves del JSON: `matchId`, `hero`, `team`, `result`, `kills`, `deaths`, `assists`, `duration`.
- Se puede forzar destino por argumentos de arranque: **`-dotareporturl`** y **`-dotareportdir`**.

---

## 3. Claves de arranque (la puerta de entrada a LAN)

`NetSession` lee estas claves (`PlayerPrefs`/argumentos):

```
dota.net.host    dota.net.name    dota.net.code    dota.net.token    dota.net.loop    dota.net.diag
```

`dota.net.loop` activa `LoopbackNet` (partida local sin red) y `dota.net.diag` saca diagnóstico.
Con `dota.net.host` apuntando a la IP LAN del anfitrión se puede **entrar directo sin pasar por el backend**.

---

## 4. Plan por fases

**Fase 0 — LAN directa, sin servidor (la prueba más barata).**
Arrancar la app con el host forzado y ver en `logcat` si conecta:
```bash
adb shell am start -n com.temka.dota2mobile/org.apkvision.dota2mobile.LauncherActivity \
  --es unity "-dota.net.host 192.168.1.50 -dota.net.name Amigo"
adb logcat | grep -iE "dota|net|apkvision"
```
Si el handshake UDP (`ConnectionKey "moba2"`, protocolo 6) se completa, **ya tienes LAN con amigos sin tocar nada más**.

**Fase 1 — servidor de salas + estadísticas (incluido en este paquete).**
`server.py` implementa toda la tabla del punto 2, con SQLite y panel web. Los teléfonos apuntan a `http://TU-IP:8080`.

**Fase 2 — apuntar el cliente a tu servidor.** Tres caminos, de menos a más invasivo:
1. **Argumentos** (`dota.net.host` + `-dotareporturl`): no requiere modificar la APK. Solo para LAN y reportes.
2. **Redirección con CA de sistema** (requiere root): entrada en `/etc/hosts` para `177-3-221-114.sslip.io` → tu IP + certificado propio instalado como CA de sistema. Sirve para cuentas y salas sin parchear el binario.
3. **Parche del literal** en `global-metadata.dat` (`https://177-3-221-114.sslip.io` → tu dominio, misma longitud o menos) y reempaquetado con apktool + firma propia. Es el camino limpio a largo plazo; el cliente nuevo no podrá instalarse encima del de APKVISION (firma distinta), así que conviene desinstalar antes.

**Fase 3 — estadísticas.**
El panel ya muestra clasificación, winrate por héroe, K/D/A medio y últimas partidas. Siguientes pasos naturales: ELO/MMR, MMR por héroe, historial completo por jugador, y perfil público en `/v1/users/<id>/profile`.

---

## 5. Limitaciones y avisos

- **La firma del reporte usa una clave del servidor original.** No la conocemos: nuestros reportes se guardan con `signatureOk=false`. Si el cliente exige una respuesta válida, se puede devolver 200 igual (lo normal) y las estadísticas funcionan; para firmar de verdad habría que sustituir la clave en el cliente.
- **La partida es P2P:** si el anfitrión está en otra red, necesitas abrir 27015/udp o una VPN tipo Tailscale/ZeroTier. En la misma Wi-Fi funciona directo.
- **El servidor propio no hace de anfitrión**: alguien tiene que hospedar desde la app (el host simula). Un «dedicado» real exigiría portar `MatchServer` a Linux, que es otro proyecto.
- **Legal:** la app usa contenido de Valve (héroes, ítems, textos, modelos). Mantén el servidor **privado, sin exposición a internet y sin monetización**. Los datos y el panel son para tu grupo de amigos.
- No expongas el puerto del panel a internet sin contraseña: hoy no tiene autenticación de administración.

---

## 6. Qué hay en el paquete

| Fichero | Contenido |
|---|---|
| `server.py` | Servidor completo, **sin dependencias** (solo librería estándar): API `/v1/*`, SQLite, panel de estadísticas, verificación de firma, salas con código y ticket. |
| `PLAN-servidor-lan.md` | Este documento |
| `README.md` | Arranque rápido y pruebas |

```bash
python3 server.py --host-ip 192.168.1.50 --port 8080 --udp-port 27015 --db moba2.db
# API:      http://192.168.1.50:8080
# Panel:    http://192.168.1.50:8080/
# Partida:  192.168.1.50:27015/udp  (el host sigue siendo el teléfono que crea la sala)
```
