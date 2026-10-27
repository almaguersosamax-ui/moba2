# Informe de análisis — «Dota 2 Mobile» v1.1 (APKVISION)

Análisis estático de la APK descargada de `dl.apkvision.org`. Fecha del análisis: 26 de octubre de 2026.
Todo el trabajo se hizo **sin ejecutar la app**: descarga, desempaquetado, decompilado Java (jadx),
decodificado de recursos (apktool) y volcado del código C# (Il2CppDumper).

---

## 1. Resumen ejecutivo

- Es un **juego MOBA para Android hecho por fans** (autor original en clave `temka`), construido en **Unity 6.2 (6000.2.14f1) con IL2CPP**, y **reempaquetado por el sitio APKVISION**, que le añadió su propia capa de arranque, un *splash* y una **traducción al inglés por sustitución de metadatos**.
- **No es la app oficial de Valve** y **no es el binario original del autor**: la firma es de `CN=APKVISION.ORG`.
- Reutiliza **contenido de Dota 2 de Valve**: 129 héroes (`npc_dota_hero_*`), 545 ítems, 666 habilidades, rutas de modelos de Valve (`models/heroes/terrorblade/demon.vmdl`) y los ficheros de localización del cliente (44.067 claves `DOTA_*`). Riesgo de propiedad intelectual alto.
- **Privacidad: aceptable.** Solo 3 permisos normales (`INTERNET`, `ACCESS_WIFI_STATE`, `WAKE_LOCK`), **sin SDKs de publicidad ni de analítica** (0 coincidencias de AppLovin, Unity Ads, Adjust, Facebook, Firebase, AppsFlyer, IronSource…).
- **Red: un único backend propio hardcodeado**, `https://177-3-221-114.sslip.io`. No hay telemetría hacia terceros detectada. Las partidas online usan **LiteNetLib (UDP)** contra un anfitrión/servidor de partida.
- El código C# **no está ofuscado**: se recuperaron 9.228 tipos, de los cuales 1.535 son del juego (`Dota.Gameplay`, `Dota.Client`, `Dota.Data`, `Dota.App`, `Dota.UI`).

**Veredicto:** técnicamente es un trabajo serio y bastante limpio para ser un proyecto de fans; el riesgo no es el malware, es **la legalidad del contenido de Valve** y **la falta de trazabilidad de la firma de APKVISION**.

---

## 2. Ficha técnica

| Campo | Valor |
|---|---|
| Fichero | `Dota-2-Mobile-v1.1-APKVISION.apk` |
| Tamaño | 517.741.536 bytes (493,8 MiB) |
| SHA-256 | `16df8b634cb7a3e19fed8660b0cb05c263879bc2a8c921385be51b323d2a0be1` |
| MD5 | `87faa2df9bc3462cfaff120ca243b7f2` |
| Package | `com.temka.dota2mobile` |
| Nombre visible | Dota 2 Mobile |
| versionName / versionCode | 1.1 / 2 |
| minSdk / targetSdk / compileSdk | 28 (Android 9) / 36 / 36 |
| ABI | `arm64-v8a` únicamente |
| Motor | Unity 6000.2.14f1 (Unity 6.2), IL2CPP, URP, Input System 1.16, Newtonsoft.Json |
| Entradas en el ZIP | 22.490 |
| Firma | v1 (`META-INF/CERT.RSA`) + bloque de firma v2/v3. Certificado autofirmado `CN=APKVISION.ORG`, SHA-256 `A5:4B:28:D5:...:D8:D1:D8`, válido 2024→3023 |

### Permisos declarados
```
android.permission.INTERNET
android.permission.ACCESS_WIFI_STATE
android.permission.WAKE_LOCK
com.temka.dota2mobile.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION   (nivel firma, generado por AndroidX)
```
No hay almacenamiento, contactos, ubicación, cámara, micrófono, teléfono ni `QUERY_ALL_PACKAGES`.

### Distribución del peso
| Rama | Tamaño |
|---|---|
| `assets/bin` (datos Unity + bundles) | 903,6 MB |
| `lib` (nativas) | 112,0 MB |
| `assets/GameData` (JSON del juego) | 27,3 MB |
| `assets/apkvision` (capa del reempaquetador) | 3,9 MB |
| `res`, `META-INF`, resto | ~12 MB |

Nativas: `libil2cpp.so` 88,7 MB · `libunity.so` 21,5 MB · `libc++_shared.so` · `lib_burst_generated.so` · `libgame.so` · `libmain.so`.

---

## 3. Arquitectura: capa del reempaquetador (Java/Kotlin) + juego (C#)

La APK tiene dos mundos: una **capa Android propia de APKVISION** (pequeña) y **el juego real en IL2CPP**.

### 3.1 Capa APKVISION (`org.apkvision.dota2mobile`)
- `Entry` (`android:name` de la aplicación): solo registra callbacks de ciclo de vida y expone `configureTls()`, que **restringe las conexiones a `apkvision.org` por HTTPS**.
- `LauncherActivity`: pantalla de progreso en ruso/inglés («Preparando textos del juego… Sin descarga, todo local»).
- `GameActivity`: la actividad de Unity (`android.app.lib_name = game`), landscape, `singleTask`.
- `LanguageAssets`: el núcleo del truco. Lee `assets/apkvision/language.json` (manifiesto con SHA-256) y **extrae a `files/il2cpp`** la metadata de IL2CPP, eligiendo:
  - idioma del sistema **ruso** → `global-metadata.dat` **original** (13,6 MB, `13220b30…`);
  - **cualquier otro idioma** → `global-metadata.dat` **parcheado en inglés** que viene dentro de `assets/apkvision/en-assets.apk` (14,2 MB, `a5d8ed8b…`).
  Cada fichero se valida por SHA-256 antes de usarse (integridad correcta, no hay descarga remota).
- Paquete `apkvision` (clases con nombres cirílicos ofuscados `C0013…C0017`, `sVMbOPAtE`, `YnLbgyrEk`): decodificadores de cadenas y un **overlay de splash** (imagen redondeada mostrada una vez, con `SharedPreferences`) que puede abrir una URL (`Intent.ACTION_VIEW`).
- `bitter.jnibridge`: puente JNI auxiliar, sin capacidades relevantes.

**Conclusión de la capa:** no hay *mod menu*, no hay inyección de anuncios, no hay descarga de código, no hay permisos ocultos. Su función es arranque + traducción + aviso de actualizaciones.

### 3.2 Juego (`Dota.*`, C# volcado)
| Ensamblado | Tipos | Rol |
|---|---|---|
| `Dota.Gameplay` | 1.068 | Simulación: héroes, habilidades (`AntimageBlink`, `AeonDiskLogic`…), ítems, creeps, torres, reglas |
| `Dota.Client` | 33 | `GameClient`, `ClientWorld`, `NetSession`, `NetRulesClient`, `LocalRulesClient`, `OnlineService`, `MatchLog`, `DotaSpeech`, `DotaCrashReport`, `BenchReport` |
| `Dota.Data` | 34 | Modelos cargados de `assets/GameData`: `GameData`, `HeroDef`, `ItemDef`, `AbilityDef`, `MapData`, `BotData`, `CosmeticsDef` |
| `Dota.UI` | 68 | HUD (habilidades, ítems, chat wheel, courier, timers de campamento) |
| `Dota.App` | 9 | `GameBootstrap`, `MenuBootstrap`, `AppFlow`, `LoadingScreen`, `DotaBench*` |

### 3.3 Multijugador y anti-cheat
- `MatchServer`, `MatchHost`, `MatchSetup`, `MatchConfig`, `MatchStartInfo` → el teléfono puede **hospedar** la partida.
- Transporte: `LiteNetPipe` sobre **LiteNetLib (UDP)**; abstracción `INetPipe` con `LoopbackNet` para práctica offline.
- Salas: `LobbyState`, `LobbyCmd`, `LobbyCodec`, `LobbyMember`.
- Integridad: `NetHandshake`, `NetGuard` (`ValidCommand`, `WhyInvalid`, `ValidRules`, `CleanName`, `RandomU64`, `SameSecret`), `AntiCheat` + `AntiCheatConfig` (`OnCommand`, `ReferencedEntity`, `UnknownReference`, `CheckReference`), `NetClientMetrics`.
- Reportes de partida firmados: `MatchReporter`, `MatchReportQueue`, `MatchReportSignature` (envío a un servicio online).

---

## 4. Red y datos

- **Único endpoint de backend en todo el binario:** `https://177-3-221-114.sslip.io`
  `sslip.io` es un DNS comodín que resuelve a la IP embebida → **177.3.221.114**, un VPS de hosting externo (Brasil). Sin dominio propio, sin certificado de marca: la identidad del operador no es verificable.
- No se encontraron dominios de analítica, publicidad ni de Valve/Steam. Los únicos otros `http(s)` del binario son documentación de Unity/.NET, esquemas XML y `https://localhost/`.
- El manifiesto **no declara `usesCleartextTraffic` ni `networkSecurityConfig`**; con `targetSdk 36` el tráfico en claro queda bloqueado por defecto. El backend usa HTTPS.
- `Entry.configureTls()` valida host, esquema y puerto antes de conectar (buena práctica), aunque solo aplica al chequeo de actualizaciones de `apkvision.org`.
- Sin rastreadores: `com/google/android/gms` aparece solo en helpers del *player* de Unity (`PlayAssetDeliveryUnityWrapper`, `FirebaseIdentifiersHelper`, `AndroidAppSetIdHelper`), no en SDKs de terceros.

**Datos que pueden salir del dispositivo:** identificadores de partida y reportes firmados hacia el backend propio, y el tráfico de sala/partida por UDP hacia el host. No hay evidencia estática de subida de contactos, ficheros o identificadores publicitarios.

---

## 5. Propiedad intelectual — el riesgo real

Evidencia encontrada en `assets/GameData` y en la metadata:

- `heroes.json` (1,5 MB): **129 héroes** con nombres internos de Valve (`npc_dota_hero_antimage`, `npc_dota_hero_axe`, `npc_dota_hero_crystal_maiden`…) y atributos (`HeroID`, `Role`, `Complexity`, `ModelScale`).
- `items.json`: **545 ítems**; `abilities.json`: **666 habilidades**; `map_dota.json` (1,16 MB): mapa con entidades; `bot_builds.json`, `bot_roles.json`, `neutral_items.json`, `portraits.json`.
- Localización copiada del cliente de Valve: `dota_english.json` con **44.067 claves** (`DOTA_ItemOnSale`, `DOTA_Tooltip_ability_*`), `items_russian.json` (5,6 MB), `dota_russian.json` (5,1 MB), `hero_lore_*`.
- Rutas de assets de Valve: `models/heroes/terrorblade/demon.vmdl`, `models/dev/error.vmdl` → **arte y modelos extraídos de Dota 2**.
- 1.831 apariciones de la cadena «Dota» y 98 de `DOTA_Item` en la metadata.

Es decir: el proyecto es un **port no autorizado** que usa nombre, héroes, ítems, textos y arte de Valve. Distribuirlo (o alojarlo, o monetizarlo) es infracción de marca y copyright; Valve ya ha retirado proyectos similares.

---

## 6. Cómo se decompiló (reproducible)

```bash
# 1) Descarga en paralelo (el servidor limita a ~130 KB/s por conexión)
python3 pdl.py                      # 124 bloques de 4 MB, 24 hilos → ~3 min

# 2) Recursos + smali
java -jar apktool_2.11.1.jar d -f -o decoded dota2mobile.apk

# 3) Java (dex → .java)
jadx-1.5.6/bin/jadx -d jadx_out --no-res --show-bad-code dota2mobile.apk

# 4) C# (IL2CPP → dump.cs + DummyDll)
dotnet Il2CppDumper.dll \
  decoded/lib/arm64-v8a/libil2cpp.so \
  decoded/assets/bin/Data/Managed/Metadata/global-metadata.dat \
  il2cpp_dump
```
Herramientas usadas: apktool 2.11.1, jadx 1.5.6, Il2CppDumper 6.7.46 (.NET 8), JDK 21. Resultados: `jadx.log` (63 avisos, ninguno bloqueante), `apktool.log` (sin errores).

**Para ir más allá** (lógica interna de métodos, no solo firmas): `il2cpp.h` + `script.json` generados se cargan en **Ghidra** (`ghidra_with_struct.py`) o **IDA** (`ida_with_struct.py`) para reconstruir el código nativo de `libil2cpp.so`.

---

## 7. Recomendaciones

1. **No la instales desde un agregador si puedes evitarlo.** La firma es de APKVISION, no del autor: el binario pudo ser alterado. Busca el canal oficial del desarrollador (`temka`) —Telegram/itch/GitHub— y compara hashes.
2. **Aísla su ejecución**: perfil de trabajo separado o dispositivo secundario; sin cuentas personales.
3. **Corta la red si solo quieres jugar offline**: la app funciona sin backend (práctica y `LoopbackNet`); sin red no hay tráfico a `177.3.221.114`.
4. **No redistribuyas** la APK ni el contenido extraído (héroes, textos, modelos): es material de Valve.
5. Si te interesa el proyecto como referencia técnica, lo valioso es `GameData/*.json` y el diseño de `MatchServer`/`NetGuard`/`AntiCheat`, **no** los assets.
6. Verifica actualizaciones por tu cuenta: los avisos de versión llegan desde `apkvision.org`.

---

## 8. Entregables

| Fichero | Contenido |
|---|---|
| `INFORME-dota2mobile.md` | Este informe |
| `dota2mobile_codigo.zip` | `jadx_out/sources` (Java, 25 MB), `AndroidManifest.xml`, `apktool.yml`, `res/`, smali de la capa APKVISION, `assets/GameData` (JSON del juego), `assets/apkvision/language.json` |
| `dota2mobile_il2cpp.zip` | `dump.cs` (966.894 líneas, 9.228 tipos), `DummyDll/` (61 ensamblados, incluidos `Dota.Gameplay/Client/Data/App`), `stringliteral.json` |
| APK original | `dota2mobile.apk` (517,7 MB) con hashes en la sección 2 |
