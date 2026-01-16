-- ====================================================================================
-- SCRIPT DE CORRECCIÓN DE IDENTIDAD (FIX ENTITIES)
-- Descripción: Reasigna todos los datos (Platos, Ajustes, Historial) de un usuario antiguo
--              al nuevo usuario 'admin' del NAS.
-- Uso: Ejecutar en la base de datos PostgreSQL.
-- ====================================================================================

DO $$
DECLARE
    target_user text := 'admin';
    old_user text;
    count_favs integer;
BEGIN
    RAISE NOTICE 'Iniciando corrección de identidad...';

    -- 1. DETECTAR EL USUARIO ANTIGUO (EL QUE TENGA MÁS PLATOS FAVORITOS)
    -- Buscamos usuarios que NO sean 'admin' y cogemos el que tenga más datos.
    SELECT user_id, count(*) 
    INTO old_user, count_favs 
    FROM favorite_foods 
    WHERE user_id != target_user 
    GROUP BY user_id 
    ORDER BY count(*) DESC 
    LIMIT 1;

    -- Si no encontramos en Favoritos, buscamos en Ajustes
    IF old_user IS NULL THEN
        SELECT user_id INTO old_user FROM user_settings WHERE user_id != target_user LIMIT 1;
    END IF;

    IF old_user IS NOT NULL THEN
        RAISE NOTICE '✅ Detectado usuario antiguo con ID: % (Contiene datos)', old_user;
        
        -- 2. LIMPIEZA PREVENTIVA
        -- "Apartamos" los datos vacíos que se hayan creado automáticamente para 'admin'
        -- para evitar errores de clave duplicada al mover los datos viejos.

        -- Borrar ajustes vacíos de admin (si existen)
        DELETE FROM user_settings WHERE user_id = target_user;
        
        -- Borrar favoritos de admin SOLO si ya existen en el usuario viejo (evitar duplicados)
        DELETE FROM favorite_foods 
        WHERE user_id = target_user 
        AND name IN (SELECT name FROM favorite_foods WHERE user_id = old_user);

        -- Borrar suministros duplicados
        DELETE FROM supply_items
        WHERE user_id = target_user
        AND item_key IN (SELECT item_key FROM supply_items WHERE user_id = old_user);

        -- Borrar estado de inyección duplicado
        DELETE FROM injection_states
        WHERE user_id = target_user
        AND plan IN (SELECT plan FROM injection_states WHERE user_id = old_user);

        -- 3. REASIGNACIÓN MASIVA (EL MIGOLLO)
        -- Ahora sí, movemos todo lo del viejo nombre al nuevo nombre 'admin'

        UPDATE favorite_foods SET user_id = target_user WHERE user_id = old_user;
        RAISE NOTICE ' -> Platos Favoritos migrados.';

        UPDATE user_settings SET user_id = target_user WHERE user_id = old_user;
        RAISE NOTICE ' -> Ajustes personales migrados (Tus menús deberían volver).';

        UPDATE supply_items SET user_id = target_user WHERE user_id = old_user;
        RAISE NOTICE ' -> Inventario migrado.';
        
        UPDATE injection_states SET user_id = target_user WHERE user_id = old_user;
        RAISE NOTICE ' -> Historial de sitios de inyección migrado.';

        -- Opcional: Historial de tratamientos (si usan user_id)
        UPDATE treatments SET user_id = target_user WHERE user_id = old_user;
        RAISE NOTICE ' -> Tratamientos vinculados migrados.';

        RAISE NOTICE '🎉 ÉXITO: Tu identidad ha sido corregida. Ahora eres % y tienes todos tus datos antiguos.', target_user;
    
    ELSE
        RAISE NOTICE '⚠️ No se encontraron datos huérfanos de otros usuarios. ¿Quizás la base de datos está vacía?';
        RAISE NOTICE 'Verifica que la importación (dump) se realizó correctamente.';
    END IF;

END $$;
