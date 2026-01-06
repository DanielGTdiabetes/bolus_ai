# Flujo de Borrador de Nutrición (Drafts)

## Problema
Las apps de nutrición (MyFitnessPal, Health Auto Export) a menudo envían datos fragmentados cuando se activan vía Shortcuts en iOS.
Ejemplo: El usuario añade 100g de pollo, la app sincroniza. El usuario sigue añadiendo 50g de pan, la app sincroniza de nuevo.
Resultado anterior: Se creaban 2 eventos separados (Bolo, luego otro Bolo?).
Resultado deseado: Unificar en una sola "Comida en curso".

## Solución: Buffer / Draft
El backend intercepta las actualizaciones recientes (< 45 min) y las almacena en un fichero temporal (`nutrition_drafts.json`).
El Bot notifica que hay una "Comida en curso" y espera confirmación manual.

### Reglas de Merge (Unificación)

La lógica (`NutritionDraftService`) decide cómo tratar un nuevo dato entrante:

1. **REPLACE (Sustitución)**:
   - Si el nuevo dato es **CUMULATIVO** (el total ha subido significativamente).
   - Si es casi idéntico al anterior (corrección o duplicado).
   - "Pizza (40g)" -> Llega "Pizza + Flan (60g)" -> Guardamos 60g.

2. **ADD (Suma)**:
   - Si el nuevo dato es **PEQUEÑO** (< 20g carbs) y distinto al anterior.
   - "Pizza (40g)" -> Llega "Flan (15g)" por separado -> Guardamos 55g.

### API Endpoints

- `POST /api/integrations/nutrition`: Ingesta (ahora soporta drafts).
- `GET /api/nutrition/draft`: Ver estado actual.
- `POST /api/nutrition/draft/close`: Confirmar y crear tratamiento final.
- `POST /api/nutrition/draft/discard`: Cancelar.

### Variables de Entorno

- `NUTRITION_DRAFT_WINDOW_MIN`: Duración de ventana (default: 30 min).
- `NUTRITION_INGEST_SECRET`: Clave opcional para asegurar el webhook.

### Interacción con Bot

1. Usuario registra comida en APP Externa.
2. Bot recibe Draft: "📝 Comida en curso: 40g Carbs... [Confirmar Ahora]".
3. Si el usuario sigue añadiendo comida, el Bot actualiza el mensaje (o envía uno nuevo): "📝 Actualizado: 55g Carbs...".
4. Usuario pulsa "Confirmar Ahora" -> Se crea el evento en DB y el Bot sugiere el cálculo de insulina.
