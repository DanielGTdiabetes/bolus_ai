# 📄 Procedimiento de mantenimiento – Cambios de usuario y contraseña

**Proyecto:** `bolus_ai`
**Ubicación del código:** `d:\bolus_ai\bolus_ai`

---

## 1️⃣ Objetivo
Documentar paso a paso qué archivos y qué fragmentos de código deben modificarse cuando se necesite **cambiar el nombre de usuario** o **reestablecer la contraseña** del sistema. Esto permite que, al cerrar la sesión actual, cualquier colaborador (incluido yo mismo) pueda aplicar los cambios sin ambigüedades.

---

## 2️⃣ Componentes involucrados

| Área | Archivo | Funcionalidad |
|------|---------|---------------|
| **Backend – autenticación** | `backend/app/api/auth.py` | Endpoints `/login`, `/me`, `/change-password`. |
| **Backend – almacenamiento de usuarios** | `backend/app/core/datastore.py` (clase `UserStore`) | Persiste usuarios en `data/users.json`. |
| **Frontend – UI de login** | `frontend/src/main.js` | Función `renderLogin()` y lógica de arranque (`initApp`). |
| **Frontend – API cliente** | `frontend/src/lib/api.ts` | Función `login()` y `storeToken()`. |
| **Frontend – estilos** | `frontend/src/style.css` | Estilos del formulario de login. |

---

## 3️⃣ Pasos para **cambiar el nombre de usuario** (admin)

1. **Abrir el archivo de usuarios**
   - Ruta: `backend/app/data/users.json` (se crea automáticamente la primera vez que se ejecuta `ensure_seed_admin()`).
   - Cada registro tiene la forma:
   ```json
   {
     "username": "admin",
     "password_hash": "<hash>",
     "role": "admin",
     "needs_password_change": false
   }
   ```
2. **Editar el campo `username`**
   - Cambia `"admin"` por el nuevo nombre deseado, por ejemplo `"dani"`.
3. **Actualizar el seed (si la app nunca ha sido iniciada)**
   - Si el archivo `users.json` no existe, el método `ensure_seed_admin()` crea un usuario con `username = "admin"` y contraseña `"admin"` (solo para desarrollo).
   - Para cambiar el seed, edita `backend/app/core/datastore.py` → método `ensure_seed_admin()` y modifica el diccionario `seed_user` con el nuevo nombre y/o contraseña (hash generado con `hash_password`).
4. **Commit y despliegue**
   - `git add backend/app/data/users.json` (o el archivo modificado).
   - `git commit -m "Update default admin username"`
   - `git push` → Render redeployará automáticamente.

---

## 4️⃣ Pasos para **resetear la contraseña** (admin o cualquier usuario)

### 4.1 Desde la UI (recomendado)
1. **Login con el usuario actual** (si aún recuerdas la contraseña).
2. **Abrir el menú de usuario** (icono en la esquina superior izquierda).
3. **Seleccionar “Cambiar contraseña”** → se muestra un `prompt` (actualmente un `alert` placeholder).
4. **Implementar la lógica** (opcional):
   ```javascript
   // En main.js, dentro del handler del botón "Cambiar contraseña"
   const oldPwd = prompt("Contraseña actual:");
   const newPwd = prompt("Nueva contraseña (mínimo 8 caracteres):");
   await apiFetch("/api/auth/change-password", {
     method: "POST",
     body: JSON.stringify({ old_password: oldPwd, new_password: newPwd })
   });
   alert("Contraseña actualizada");
   ```
   > **Nota:** La UI todavía muestra un `alert` placeholder; el código anterior es la forma definitiva.

### 4.2 Manualmente (cuando no se conoce la contraseña)
1. **Generar un nuevo hash** con la herramienta de hashing que ya está en el proyecto (`hash_password`).
   - En la terminal, abre Python REPL dentro del entorno del proyecto:
   ```bash
   python
   >>> from app.core.security import hash_password
   >>> hash_password("nueva_contraseña_segura")
   '$pbkdf2-sha256$29000$...'
   ```
2. **Editar `users.json`**
   - Busca el registro del usuario y reemplaza el valor de `"password_hash"` por el hash generado.
3. **Commit y despliegue** (igual que en el paso 3).

---

## 5️⃣ Actualizaciones en el **frontend** (si cambias el nombre de usuario)
### 🔐 Seguridad básica
- El sistema utiliza **usuario y contraseña** para autenticarse.
- Los usuarios pueden **cambiar su contraseña en cualquier momento** desde el menú de usuario (icono en la esquina superior izquierda) → “Cambiar contraseña”.
- El proceso de cambio de contraseña llama al endpoint `/api/auth/change-password` con los campos `old_password` y `new_password`.
- Después de cambiar la contraseña, se muestra un mensaje de confirmación.
- No hay cambios de código necesarios; la UI usa el endpoint `/login` que acepta cualquier `username`.
- Si deseas **pre‑rellenar** el campo de usuario con el nuevo nombre (solo para conveniencia en desarrollo), modifica en `renderLogin()`:
  ```javascript
  document.getElementById("login-username").value = "nuevo_usuario";
  ```

---

## 6️⃣ Resumen de archivos a tocar

| Acción | Archivo | Comentario |
|--------|---------|------------|
| Cambiar nombre de usuario (seed) | `backend/app/core/datastore.py` → `ensure_seed_admin()` | Modificar `seed_user["username"]`. |
| Cambiar nombre de usuario (persistido) | `backend/app/data/users.json` | Editar campo `username`. |
| Resetear contraseña (manual) | `backend/app/data/users.json` | Reemplazar `password_hash` con hash nuevo. |
| Cambiar contraseña vía UI | `frontend/src/main.js` (handler del botón) | Implementar llamada a `/api/auth/change-password`. |
| Generar hash (para paso manual) | Terminal Python REPL (usa `app.core.security.hash_password`). | No es archivo, solo comando. |

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
