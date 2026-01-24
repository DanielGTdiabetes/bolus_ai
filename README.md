# 🩸 Bolus AI

Asistente inteligente para la gestión de diabetes tipo 1. Calcula tus bolos de insulina, analiza fotos de comida con IA y mantén tu historial sincronizado con Nightscout.

---

## 📖 Documentación Detallada
Para una explicación completa de cómo funciona la aplicación, consulta nuestro:
👉 **[MANUAL DE USUARIO](./docs/MANUAL_USUARIO.md)** (Incluye explicación de menús, lógica de cálculo, Smart Input y Rotación de Sitios).

---

## ✨ Características Principales

- **🤖 Autosens**: Detección automática de resistencia/sensibilidad en tiempo real.
- **📡 Dexcom Share Mirror**: Conexión directa con la nube de Dexcom para glucosa en tiempo real (sin necesidad de Nightscout).
- **🔮 Pronóstico Metabólico con Confianza**: Predicción avanzada que muestra el impacto de grasas/fibras con indicadores de confianza (Alta/Media/Baja).
- **🧠 Motor de Aprendizaje**: Sugerencias clínicas basadas en tus patrones (ej. "Baja tu ratio del desayuno").
- **📸 Análisis de Comida por IA**: Estima carbohidratos, grasas, proteínas y fibra a partir de una foto.
- **🛡️ Regla de Oro V2**: Sistema anti-pánico inteligente que evita falsas alarmas de hipo si hay comida pendiente.
- **📍 Mapa Corporal**: Rotación de sitios de inyección con memoria visual.
- **🍴 Modo Restaurante**: Seguimiento inteligente de comidas complejas ("micro-bolos").
- **🔄 Integración Nightscout**: Lectura en tiempo real + Subida de Tratamientos.
- **📊 Gestión de Basal**: Análisis de "Amanecer" y eficacia nocturna.

---
## 🏗 Arquitectura Híbrida (Alta Disponibilidad)

Bolus AI utiliza una arquitectura robusta de **Doble Instancia** para asegurar que nunca pierdas el servicio:

1.  **🏠 NAS (Principal):** Tu servidor local (Docker) es la instancia maestra. Gestiona el Bot de Telegram principal, almacena datos localmente y funciona sin latencia.
2.  **☁️ Render (Backup/Guardian):** Una instancia en la nube que monitoriza tu NAS. Si tu casa se queda sin internet o luz, puedes usar Render inmediatamente. Los datos se sincronizan automáticamente.

### 📚 Guías de Despliegue
- 👉 **[Instalación Principal en NAS](./NAS_SETUP.md)** (Recomendado)
- 👉 **[Instalación de Respaldo en Render](./RENDER_SETUP.md)**

---

## 🤖 Doble Bot de Telegram

Para soportar esta arquitectura, el sistema gestiona dos comportamientos del Bot:
- **Bot Principal (NAS):** Procesa tus fotos, cálculos y recordatorios. Usa Webhooks para máxima velocidad.
- **Bot Guardián (Render):** Monitoriza silenciósamente. Si detecta que el NAS cae, puede asumir el control o servir como punto de acceso de emergencia.

Consulta los detalles en: 👉 **[GUÍA DEL BOT TELEGRAM](./README_BOT.md)**

---

## ✨ Características Principales

- **🧠 Autosens & IA:** Detección automática de sensibilidad y análisis de fotos de comida.
- **🔄 Sincronización Bidireccional:** NAS -> Neon (Backup cada 4h) con "Válvula de Seguridad" para evitar sobrescrituras.
- **📍 Mapa Corporal:** Rotación de sitios de inyección con memoria visual.
- **🛡️ Regla de Oro V2:** Sistema anti-pánico inteligente.


### 📏 Truco del Bolígrafo (Calibración)
Si habilitas el análisis de imagen, puedes colocar tu **pluma de insulina** (modelo NovoPen Echo Plus o similar, color rojo metálico) junto al plato. La IA sabe que mide exactamente **16.5 cm** y la usará para calibrar el volumen real de la comida.

### 🤖 Autosens & Sugerencias
Olvídate de calcular si hoy estás más resistente. La app analiza las últimas 24h y ajusta dinámicamente tu ISF y Ratios (+10%, -5%...) para clavar el bolo. Además, el **Motor de Aprendizaje** revisa tus noches y comidas recurrentes para sugerirte cambios permanentes en tu terapia ("Tu desayuno de las 8am siempre acaba alto, sube el ratio").

### 🍽️ Sesión Restaurante (Seguridad en Exterior)
El modo restaurante te permite planificar una comida desde el menú, realizar un bolo inicial y luego ir añadiendo fotos de los platos reales. Al final, la app calcula si el bolo fue suficiente o si necesitas un pequeño ajuste, siempre vigilando tu Insulina Activa (IOB).

---

## 🔐 Seguridad y Usuarios

Para gestionar usuarios, contraseñas y accesos iniciales, consulta:
👉 **[Manual de Gestión de Usuarios](./USER_AUTH_GUIDE.md)**

---

## ⚖️ Descargo de Responsabilidad
Esta aplicación es una herramienta de apoyo y **no sustituye el criterio médico**. Los cálculos de la IA son estimaciones. Verifica siempre los datos antes de tomar cualquier decisión terapéutica.
