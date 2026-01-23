# QA manual - Calculadora manual (Bolus)

## Checks mínimos

1. **Manual + 15g carbs → NO aparece “Proteínas muy altas”.**
   - Activa **Entrada manual**.
   - Deja Proteínas/Fibra/Grasas en 0.
   - Ingresa 15g de carbohidratos y calcula.
   - Verifica que no aparezca el aviso de “Proteínas muy altas”.

2. **Manual + protein_g=70 → aparece aviso (si corresponde).**
   - Activa **Entrada manual**.
   - Ingresa Proteínas = 70g.
   - Calcula y confirma que el aviso se muestra si el umbral aplica.

3. **Manual + fat_g alto → pronóstico marcado como lento (si existe).**
   - Activa **Entrada manual**.
   - Ingresa Grasas con un valor alto (p. ej. 50g).
   - Calcula y verifica que el pronóstico muestre absorción lenta si el sistema lo soporta.

4. **Cambiar meal_slot → protein/fiber/fat vuelven a 0.**
   - Activa **Entrada manual** y pon valores distintos de 0.
   - Cambia el `meal_slot` (Desayuno/Comida/Cena/Snack).
   - Verifica que los campos de macros vuelven a 0 y que los avisos anteriores desaparecen.

5. **Repetir cálculo → forecast no usa valores antiguos.**
   - Haz un cálculo con macros manuales altos.
   - Pulsa **Nueva comida**, deja macros en 0 y recalcula.
   - Verifica que el pronóstico/avisos no arrastran los valores previos.
