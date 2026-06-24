# Hermes MyFitnessPal -> Bolus AI Sync

Runbook operativo para replicar y recuperar la integracion de MyFitnessPal en el mini PC BMAX (`jarvis`).

## Objetivo

La ruta principal de nutricion queda:

```text
MyFitnessPal Android -> Bolus AI Companion -> trigger Tailscale BMAX -> Hermes MyFitnessPal web -> Bolus AI /api/integrations/nutrition
```

La ruta Android por Health Connect sigue existiendo como respaldo:

```text
MyFitnessPal Android -> Salud Conectada -> Bolus AI Companion -> Bolus AI
```

La razon de este diseno es que MyFitnessPal Android puede dejar de escribir en Salud Conectada sin error claro. Hermes lee el diario web directamente y envia las comidas a Bolus AI con huellas estables para deduplicar. Companion solo usa Health Connect como respaldo y limita la lectura automatica al dia local actual para evitar reenviar comidas antiguas.

## Estado Actual En BMAX

Host:

```text
jarvis
```

Directorio principal:

```text
/opt/hermes-mcp/myfitnesspal
```

Archivos relevantes:

```text
/opt/hermes-mcp/myfitnesspal/main.py
/opt/hermes-mcp/myfitnesspal/mfp_adapter.py
/opt/hermes-mcp/myfitnesspal/mfp_wrapper.py
/opt/hermes-mcp/myfitnesspal/cookie_auth.py
/opt/hermes-mcp/myfitnesspal/scripts/check_and_refresh.sh
/opt/hermes-mcp/myfitnesspal/scripts/refresh_cookies.py
/opt/hermes-mcp/myfitnesspal/scripts/sync_to_bolus.py
/opt/hermes-mcp/myfitnesspal/scripts/mfp_sync_trigger.py
/opt/hermes-mcp/myfitnesspal/.env
/home/dani/.hermes/.env
/home/dani/.hermes/state/mfp_bolus_sync.json
```

Servicios de usuario:

```bash
systemctl --user status hermes-mfp-refresh.timer
systemctl --user status hermes-mfp-sync-trigger.service
```

Temporizadores:

```text
hermes-mfp-refresh.timer      cada 6 horas: healthcheck y renovacion de cookies si hace falta
```

No debe existir un timer periodico para `sync_to_bolus.py`: leer el diario mientras
MyFitnessPal sigue abierto puede enviar una comida incompleta. La sincronizacion de
nutricion se inicia exclusivamente desde Companion tras confirmar la salida de la app.

Trigger bajo demanda:

```text
hermes-mfp-sync-trigger.service  escucha en 0.0.0.0:8776
GET  /healthz                    estado del trigger
POST /mfp/sync-now               ejecuta sync_to_bolus.py
```

En Companion la URL por defecto usa la IP Tailscale del BMAX:

```text
http://100.65.212.74:8776
```

## Variables De Entorno

En `/opt/hermes-mcp/myfitnesspal/.env`:

```env
MFP_COOKIES='...'
MFP_USERNAME='Dani_gt'
MFP_TIMEOUT_SECONDS=20
MFP_MAX_RETRIES=3
MFP_LOG_LEVEL=INFO
MFP_REQUEST_DEBUG=0
```

En `/home/dani/.hermes/.env`:

```env
BOLUS_AI_BASE_URL=http://192.168.0.110:8000
NUTRITION_INGEST_KEY=...
```

`NUTRITION_INGEST_KEY` tambien puede llamarse `NUTRITION_INGEST_SECRET` o `BOLUS_AI_NUTRITION_INGEST_KEY`. El sincronizador acepta cualquiera de esos nombres.

El trigger acepta la misma clave por `X-Ingest-Key`. Opcionalmente puede usarse una clave separada:

```env
HERMES_MFP_TRIGGER_KEY=...
```

No guardar cookies ni claves en Obsidian, GitHub, tickets o documentacion.

## Seguridad

### Cookies MyFitnessPal

`MFP_COOKIES` contiene cookies de sesion web. Debe tratarse como secreto.

Permisos recomendados:

```bash
chmod 0640 /opt/hermes-mcp/myfitnesspal/.env
chmod 0750 /opt/hermes-mcp/myfitnesspal
chmod 0660 /home/dani/.hermes/state/mfp_bolus_sync.json
```

El renovador:

- usa un perfil Chrome gestionado en `/home/dani/.hermes/browser-profiles/myfitnesspal`;
- extrae solo cookies del dominio `myfitnesspal.com`;
- filtra a nombres conocidos de sesion/Cloudflare;
- no imprime valores de cookies;
- valida `auth`, `diary` y `search` antes de escribir el `.env`;
- crea backup previo en `/opt/hermes-mcp/myfitnesspal/backups/`;
- falla si detecta captcha, Cloudflare challenge, bloqueo o consentimiento que requiere accion manual.

### Clave De Ingesta Bolus AI

El envio a Bolus AI usa:

```http
POST /api/integrations/nutrition
X-Ingest-Key: <NUTRITION_INGEST_KEY>
```

La clave debe coincidir con la configurada en el backend de Bolus AI (`NUTRITION_INGEST_KEY` o `NUTRITION_INGEST_SECRET`).

El payload incluye macros y lista de alimentos, pero no credenciales.

### Trigger Companion -> BMAX

El endpoint `POST /mfp/sync-now`:

- requiere `X-Ingest-Key` o `X-Hermes-Key`;
- rechaza llamadas sin clave con `401`;
- usa un lock local en `/home/dani/.hermes/state/mfp_sync_trigger.lock` para evitar ejecuciones solapadas;
- ejecuta `/opt/hermes-mcp/myfitnesspal/scripts/sync_to_bolus.py`;
- devuelve JSON con `success`, `returncode`, `duration_ms` y la cola final de salida sanitizada.

El servicio esta pensado para Tailscale, no para Internet abierto.

## Como Detecta Comidas Nuevas

Hermes usa un unico modo automatico: trigger bajo demanda desde Companion cuando
el usuario cierra MyFitnessPal.

Flujo:

1. Companion detecta que MyFitnessPal deja de estar en primer plano.
2. Espera 20 segundos para que MyFitnessPal guarde/sincronice.
3. Llama a `POST /mfp/sync-now` en BMAX por Tailscale.
4. Si Hermes no encuentra comida nueva, Companion repite una vez 75 segundos despues.
5. Hermes lee el diario de hoy.
6. Ignora comidas vacias.
7. Para cada comida calcula una huella estable:

```text
hermes-mfp:<fecha>:<meal>:<sha256 de alimentos + cantidades + macros>
```

8. Si esa huella no esta marcada como enviada, la envia.
9. Si Bolus AI no esta disponible o falta configuracion, la deja en cola.
10. Si el usuario modifica una comida en MyFitnessPal, cambia la huella y se reenvia como nueva version.

Por defecto sincroniza solo el dia actual para evitar importar historico y duplicar comidas que ya entraron por Salud Conectada.

Para sincronizar otro dia manualmente:

```bash
/opt/hermes-mcp/myfitnesspal/venv/bin/python \
  /opt/hermes-mcp/myfitnesspal/scripts/sync_to_bolus.py \
  --date 2026-06-20
```

Para forzar reenvio de un dia:

```bash
/opt/hermes-mcp/myfitnesspal/venv/bin/python \
  /opt/hermes-mcp/myfitnesspal/scripts/sync_to_bolus.py \
  --date 2026-06-20 \
  --force
```

Usar `--force` con cuidado: puede generar una actualizacion o duplicado si la comida ya existe por otra fuente.

## Payload Enviado A Bolus AI

El sincronizador envia formato compatible con Health Auto Export:

```json
{
  "source": "MyFitnessPal-Hermes",
  "provider": "hermes-myfitnesspal",
  "date": "2026-06-20",
  "meal": "breakfast",
  "meal_fingerprint": "hermes-mfp:2026-06-20:breakfast:...",
  "foods": [],
  "payload": {
    "data": {
      "metrics": [
        {
          "name": "carbohydrates",
          "data": [
            {
              "date": "2026-06-20 08:30:00 +0200",
              "qty": 9.0,
              "source": "MyFitnessPal-Hermes:breakfast",
              "meal_fingerprint": "hermes-mfp:2026-06-20:breakfast:..."
            }
          ]
        }
      ]
    }
  }
}
```

El backend deduplica primero por `meal_fingerprint` y despues por ventana temporal/macros. Si se manda la misma huella, se actualiza o se ignora segun corresponda.

## Horarios Por Defecto

MyFitnessPal no siempre expone hora real de registro por comida. Hermes asigna horas locales estables:

```text
breakfast/desayuno  08:30
lunch/comida        14:00
dinner/cena         21:00
snacks              17:30
```

Zona horaria por defecto:

```env
HERMES_MFP_BOLUS_TIMEZONE=Europe/Madrid
```

## Logs Y Diagnostico

Estado de timers:

```bash
systemctl --user list-timers 'hermes-mfp*' --all
systemctl --user status hermes-mfp-refresh.timer
systemctl --user status hermes-mfp-sync-trigger.service
```

Logs:

```bash
tail -100 /opt/hermes-mcp/myfitnesspal/logs/bolus_sync.log
tail -100 /opt/hermes-mcp/myfitnesspal/logs/auth.log
tail -100 /opt/hermes-mcp/myfitnesspal/logs/requests.log
tail -100 /opt/hermes-mcp/myfitnesspal/logs/errors.log
journalctl --user -u hermes-mfp-bolus-sync.service -n 100 --no-pager
journalctl --user -u hermes-mfp-refresh.service -n 100 --no-pager
```

Healthcheck MyFitnessPal:

```bash
/opt/hermes-mcp/myfitnesspal/scripts/healthcheck.sh
```

Lectura HTTP local:

```bash
curl -sS 'http://127.0.0.1:8766/mfp/health' | python3 -m json.tool
curl -sS 'http://127.0.0.1:8766/mfp/today' | python3 -m json.tool
```

Prueba seca de envio:

```bash
/opt/hermes-mcp/myfitnesspal/venv/bin/python \
  /opt/hermes-mcp/myfitnesspal/scripts/sync_to_bolus.py \
  --date "$(date +%F)" \
  --dry-run
```

## Renovacion De Cookies

Flujo normal:

```bash
/opt/hermes-mcp/myfitnesspal/scripts/check_and_refresh.sh
```

Comportamiento:

1. Ejecuta healthcheck.
2. Si `auth`, `diary` y `search` funcionan, no toca cookies.
3. Si falla, lanza Chrome/Chromium con perfil gestionado.
4. Si el perfil sigue logado, extrae cookies.
5. Si no hay sesion, puede intentar login controlado si hay credenciales locales y `MFP_ALLOW_AUTOMATED_LOGIN=1`.
6. Valida las cookies nuevas contra MyFitnessPal.
7. Solo si la validacion pasa, actualiza `.env`.

Forzar renovacion:

```bash
/opt/hermes-mcp/myfitnesspal/scripts/refresh_cookies.sh
```

Si aparece captcha, Cloudflare challenge, 2FA o consentimiento manual, el script no lo resuelve. Hay que abrir MyFitnessPal manualmente en el perfil gestionado o exportar cookies desde otro navegador.

## Recuperacion Si Fallan Cookies

1. Confirmar fallo:

```bash
/opt/hermes-mcp/myfitnesspal/scripts/healthcheck.sh
tail -100 /opt/hermes-mcp/myfitnesspal/logs/auth.log
```

2. Intentar renovacion automatica:

```bash
/opt/hermes-mcp/myfitnesspal/scripts/check_and_refresh.sh
```

3. Si falla por captcha/bloqueo/consentimiento:

```bash
google-chrome \
  --user-data-dir=/home/dani/.hermes/browser-profiles/myfitnesspal \
  https://www.myfitnesspal.com/es
```

Completar login/consentimiento manualmente y despues ejecutar:

```bash
/opt/hermes-mcp/myfitnesspal/scripts/refresh_cookies.sh
/opt/hermes-mcp/myfitnesspal/scripts/healthcheck.sh
```

4. Si no hay entorno grafico o el BMAX esta caido, exportar cookies desde otro equipo ya logado en MyFitnessPal y pegarlas en:

```text
/opt/hermes-mcp/myfitnesspal/.env
```

Formato:

```env
MFP_COOKIES='name=value; name2=value2'
```

Despues:

```bash
chmod 0640 /opt/hermes-mcp/myfitnesspal/.env
/opt/hermes-mcp/myfitnesspal/scripts/healthcheck.sh
systemctl --user restart hermes-mfp-sync-trigger.service
```

## Replicar En Otro Mini PC

### 1. Preparar sistema

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip rsync curl jq chromium
```

Chrome o Chromium es necesario para renovacion gestionada de cookies.

### 2. Copiar directorio del MCP

Desde el BMAX sano:

```bash
sudo rsync -a \
  --exclude 'venv' \
  --exclude 'logs/*' \
  --exclude '__pycache__' \
  /opt/hermes-mcp/myfitnesspal/ \
  nuevo-host:/tmp/myfitnesspal/
```

En el nuevo host:

```bash
sudo mkdir -p /opt/hermes-mcp/myfitnesspal
sudo rsync -a /tmp/myfitnesspal/ /opt/hermes-mcp/myfitnesspal/
sudo chown -R dani:dani /opt/hermes-mcp/myfitnesspal
chmod 0750 /opt/hermes-mcp/myfitnesspal
```

### 3. Crear entorno Python

```bash
cd /opt/hermes-mcp/myfitnesspal
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip wheel
venv/bin/pip install -r requirements.txt
```

### 4. Configurar secretos

Crear o copiar con canal seguro:

```text
/opt/hermes-mcp/myfitnesspal/.env
/home/dani/.hermes/.env
```

Minimo necesario:

```env
# /opt/hermes-mcp/myfitnesspal/.env
MFP_COOKIES='...'
MFP_USERNAME='Dani_gt'
MFP_TIMEOUT_SECONDS=20
MFP_MAX_RETRIES=3
MFP_LOG_LEVEL=INFO

# /home/dani/.hermes/.env
BOLUS_AI_BASE_URL=http://192.168.0.110:8000
NUTRITION_INGEST_KEY=...
```

Permisos:

```bash
chmod 0640 /opt/hermes-mcp/myfitnesspal/.env
chmod 0750 /opt/hermes-mcp/myfitnesspal
mkdir -p /home/dani/.hermes/state
chmod 0750 /home/dani/.hermes /home/dani/.hermes/state
```

### 5. Instalar timers de usuario

Crear:

```text
/home/dani/.config/systemd/user/hermes-mfp-refresh.service
/home/dani/.config/systemd/user/hermes-mfp-refresh.timer
/home/dani/.config/systemd/user/hermes-mfp-bolus-sync.service
/home/dani/.config/systemd/user/hermes-mfp-sync-trigger.service
```

Contenido actual de `hermes-mfp-refresh.service`:

```ini
[Unit]
Description=Hermes MyFitnessPal cookie healthcheck and refresh

[Service]
Type=oneshot
WorkingDirectory=/opt/hermes-mcp/myfitnesspal
ExecStart=/opt/hermes-mcp/myfitnesspal/scripts/check_and_refresh.sh
Environment=APP_DIR=/opt/hermes-mcp/myfitnesspal
```

Contenido actual de `hermes-mfp-refresh.timer`:

```ini
[Unit]
Description=Run Hermes MyFitnessPal cookie healthcheck and refresh every 6 hours

[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
```

Contenido actual de `hermes-mfp-bolus-sync.service`:

```ini
[Unit]
Description=Hermes MyFitnessPal to Bolus AI nutrition sync
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/hermes-mcp/myfitnesspal
ExecStart=/opt/hermes-mcp/myfitnesspal/venv/bin/python /opt/hermes-mcp/myfitnesspal/scripts/sync_to_bolus.py
Environment=APP_DIR=/opt/hermes-mcp/myfitnesspal
```

Contenido actual de `hermes-mfp-sync-trigger.service`:

```ini
[Unit]
Description=Hermes MyFitnessPal sync trigger endpoint
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/hermes-mcp/myfitnesspal
ExecStart=/opt/hermes-mcp/myfitnesspal/venv/bin/python /opt/hermes-mcp/myfitnesspal/scripts/mfp_sync_trigger.py
Environment=APP_DIR=/opt/hermes-mcp/myfitnesspal
Environment=MFP_SYNC_TRIGGER_PORT=8776
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Activar:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hermes-mfp-refresh.timer
systemctl --user enable --now hermes-mfp-sync-trigger.service
systemctl --user disable --now hermes-mfp-bolus-sync.timer 2>/dev/null || true
loginctl enable-linger dani
```

### 6. Validar

```bash
/opt/hermes-mcp/myfitnesspal/scripts/healthcheck.sh
curl -sS 'http://127.0.0.1:8766/mfp/health' | python3 -m json.tool
curl -sS 'http://100.65.212.74:8776/healthz' | python3 -m json.tool
/opt/hermes-mcp/myfitnesspal/venv/bin/python /opt/hermes-mcp/myfitnesspal/scripts/sync_to_bolus.py --dry-run
systemctl --user list-timers 'hermes-mfp*' --all
```

No activar el envio real hasta que:

- `healthcheck.sh` pase;
- `BOLUS_AI_BASE_URL` responda;
- `NUTRITION_INGEST_KEY` este configurada;
- `sync_to_bolus.py --dry-run` construya las comidas esperadas.

## Si Falla El BMAX

Orden recomendado:

1. Mantener Bolus AI Companion activo: sigue intentando Salud Conectada y permite entrada manual.
2. Levantar este MCP en otro mini PC usando la seccion de replicacion.
3. Copiar cookies si aun son validas, o hacer login manual para regenerarlas.
4. Configurar `NUTRITION_INGEST_KEY`.
5. Ejecutar `sync_to_bolus.py --dry-run`.
6. Activar timers.

## Riesgos Pendientes

- MyFitnessPal no ofrece API publica estable; scraping/cookies puede romperse por cambios de HTML, Cloudflare, captcha o 2FA.
- Si MyFitnessPal Android vuelve a escribir en Salud Conectada, pueden llegar datos por dos fuentes. El backend deduplica por huella y por ventana temporal/macros, pero conviene revisar el historial si se ven duplicados.
- El sincronizador no esta activo al 100% hasta configurar `NUTRITION_INGEST_KEY` en Hermes.
- La cola local contiene alimentos y macros; no contiene secretos, pero aun asi debe tener permisos restringidos.

## Mejoras Recomendadas

- Monitor Telegram si `healthcheck` falla dos ciclos seguidos.
- Monitor Telegram si hay comidas pendientes mas de 15 minutos.
- Endpoint de estado en Bolus AI mostrando ultima comida, origen y ultimo intento Hermes.
- Backup cifrado del directorio `/opt/hermes-mcp/myfitnesspal` excluyendo logs pesados.
- Procedimiento mensual de prueba de recuperacion en otro host.
