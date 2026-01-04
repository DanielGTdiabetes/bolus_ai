# Fix Build Error: Component Imports

## Problema
El build falló con `Could not resolve "../components/ui/Card"`.
Causa: En `ManualCalculatorPage.jsx`, intenté importar `Card` y `Button` desde archivos inexistentes, cuando en realidad son exportaciones nombradas dentro de `components/ui/Atoms.jsx`.

## Solución
Se corrigió la sentencia de importación en `ManualCalculatorPage.jsx`:
**Antes:**
```javascript
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
```
**Ahora:**
```javascript
import { Card, Button } from '../components/ui/Atoms';
```

## Estado
Corregido y listo para verificar.
