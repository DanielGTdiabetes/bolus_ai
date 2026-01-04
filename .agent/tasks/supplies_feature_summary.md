# Suministros (Stock Check)

## Funcionalidad Implementada
El usuario solicitó que el bot tuviese acceso al stock de suministros (agujas y sensores) para avisar proactivamente cuando queden pocos.
Confirmó que estos datos ya existen en el menú de "Suministros" (tabla `supply_items`).

He implementado lo siguiente:

1.  **Herramientas del Bot (`tools.py`)**:
    *   `check_supplies_stock`: Consulta la base de datos `supply_items` y devuelve una lista de items con advertencias si están por debajo del umbral (Agujas < 10, Sensores < 3, Reservorios < 3).
    *   `update_supply_quantity`: Permite al usuario (o al bot mediante comandos) actualizar el stock manualmente.

2.  **Registro de Capacidades (`registry.py`)**:
    *   Se registraron las nuevas herramientas en el bot.
    *   Se creó un nuevo **Job** (`supplies_check`) que ejecuta `bot_proactive.check_supplies_status`.

3.  **Lógica Proactiva (`proactive.py`)**:
    *   Se añadió la función `check_supplies_status` que:
        *   Verifica el stock.
        *   Envía un mensaje proactivo al usuario si detecta niveles bajos.
        *   Tiene un "cooldown" de ~21h para no spamear (aviso diario).

## Estado
- Código implementado y corregido (errores de sintaxis en `registry.py` resueltos).
- Servidor reiniciado correctamente para aplicar los cambios y registrar las nuevas herramientas.

## Próximos Pasos
- Verificar que el job se ejecute correctamente en el planificador (ya está registrado).
- El usuario puede probar preguntando "¿Cuántas agujas me quedan?" o esperar al aviso automático.
