# 📄 Procedimiento de mantenimiento – Cambios de usuario y contraseña

**Proyecto:** `bolus_ai`
**Ubicación del código:** `d:\bolus_ai\bolus_ai`

---

## 1️⃣ Objetivo
Documentar paso a paso qué archivos y qué fragmentos de código deben modificarse cuando se necesite **cambiar el nombre de usuario** o **reestablecer la contraseña** del sistema. Esto permite que, al cerrar la sesión actual, cualquier colaborador (incluido yo mismo) pueda aplicar los cambios sin ambigüedades.

---

## 2️⃣ Componentes involucrados

| Área | Archivo | Funcionalidad |
|------|---------|---------------|
| **Backend – autenticación** | `backend/app/api/auth.py` | Endpoints `/login`, `/me`, `/change-password`. |
| **Backend – almacenamiento** | `backend/app/core/datastore.py` | Persistencia en `users.json`. |
| **Frontend – Páginas** | `frontend/src/pages/LoginPage.jsx` | Pantalla de inicio de sesión. |
| **Frontend – Perfil** | `frontend/src/pages/ChangePasswordPage.jsx` | Cambio de contraseña seguro. |
| **Frontend – API** | `frontend/src/lib/api.ts` | Funciones `loginRequest`, `changePassword`. |

---

## 3️⃣ Pasos para cambiar el nombre de usuario (admin)

1. **Editar el archivo de usuarios**
   - Si la app ya está desplegada, el archivo está en el volumen de datos (`DATA_DIR`).
   - Si es local: `backend/data/users.json`.
   ```json
   {
     "username": "admin",
     "password_hash": "...",
     "role": "admin"
   }
   ```
2. **Reiniciar el servicio** para asegurar que los cambios se cargan (en Render esto ocurre al hacer Deploy).

---

## 4️⃣ Pasos para resetear la contraseña

### 4.1 Desde la Aplicación (Recomendado)
1. Inicia sesión.
2. Ve a **Perfil** (icono de usuario arriba a la izquierda).
3. Selecciona **Cambiar Contraseña**.
4. Introduce la contraseña actual y la nueva. El sistema validará la seguridad.

### 4.2 Manualmente (Sin acceso)
Si has olvidado la contraseña de administrador:
1. Genera un nuevo hash en tu PC local usando Python:
   ```bash
   python -c "from app.core.security import hash_password; print(hash_password('TuNuevaContraseña'))"
   ```
2. Accede al archivo `users.json` en tu servidor o volumen.
3. Reemplaza el `password_hash` del usuario por el nuevo generado.

---

## 5️⃣ Resumen de archivos técnicos

| Acción | Archivo |
|--------|---------|
| Lógica de Login | `frontend/src/pages/LoginPage.jsx` |
| Lógica de Cambio PWD | `frontend/src/pages/ChangePasswordPage.jsx` |
| Hash de contraseñas | `backend/app/core/security.py` |
| Semilla inicial | `backend/app/core/datastore.py` (método `ensure_seed_admin`) |

---

## 7️⃣ Checklist rápido antes de cerrar la sesión
- [ ] **Backup** del archivo `users.json` (copia de seguridad).
- [ ] **Commit** de los cambios (username o hash).
- [ ] **Deploy** en Render (push → espera a que el build termine).
- [ ] **Probar**: abrir la app en modo incognito, intentar login con el nuevo usuario/contraseña.
- [ ] **Verificar** que el menú de usuario sigue funcionando (logout → login).

---

### 📌 Nota final
Esta documentación está pensada para que cualquier colaborador (incluido yo mismo) pueda aplicar los cambios sin necesidad de buscar en el código. Si en el futuro se añaden nuevos campos al modelo de usuario (por ejemplo, `email` o `2FA`), basta con extender `UserStore` y actualizar este documento siguiendo la misma estructura.

¡Listo! Cuando vuelvas a abrir la sesión, tendrás todo lo necesario para actualizar usuarios y contraseñas de forma segura y sin sorpresas. 🚀
