#!/usr/bin/env python3
"""
Script para diagnosticar el estado del sistema de aprendizaje de absorción.
Ejecutar: python scripts/check_meal_learning.py
"""
import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import datetime, timedelta


async def main():
    from sqlalchemy import text
    from app.core.db import init_db, get_engine

    init_db()
    engine = get_engine()

    if not engine:
        print("❌ No hay conexión a base de datos")
        return

    async with engine.connect() as conn:
        print("=" * 60)
        print("🔍 DIAGNÓSTICO DEL SISTEMA DE APRENDIZAJE DE ABSORCIÓN")
        print("=" * 60)

        # 1. Contar clusters
        print("\n📊 TABLA: meal_clusters")
        try:
            result = await conn.execute(text("SELECT COUNT(*) FROM meal_clusters"))
            total_clusters = result.scalar()
            print(f"   Total clusters: {total_clusters}")

            if total_clusters > 0:
                # Clusters por confianza
                result = await conn.execute(text("""
                    SELECT confidence, COUNT(*) as cnt, AVG(n_ok) as avg_n_ok
                    FROM meal_clusters
                    GROUP BY confidence
                    ORDER BY cnt DESC
                """))
                rows = result.fetchall()
                print("\n   Por nivel de confianza:")
                for row in rows:
                    print(f"      - {row.confidence}: {row.cnt} clusters (avg n_ok: {row.avg_n_ok:.1f})")

                # Clusters que SÍ cumplen criterio
                result = await conn.execute(text("""
                    SELECT COUNT(*) FROM meal_clusters
                    WHERE n_ok >= 5 AND confidence IN ('medium', 'high')
                """))
                usable = result.scalar()
                print(f"\n   ✅ Clusters USABLES (n_ok >= 5 y confidence medium/high): {usable}")

                # Top clusters
                result = await conn.execute(text("""
                    SELECT cluster_key, n_ok, confidence, absorption_duration_min, peak_min
                    FROM meal_clusters
                    ORDER BY n_ok DESC
                    LIMIT 5
                """))
                print("\n   Top 5 clusters por experiencias:")
                for row in result.fetchall():
                    status = "✅" if row.n_ok >= 5 and row.confidence in ('medium', 'high') else "⏳"
                    print(f"      {status} {row.cluster_key[:50]}...")
                    print(f"         n_ok={row.n_ok}, confidence={row.confidence}, duration={row.absorption_duration_min}min")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        # 2. Contar experiencias
        print("\n📊 TABLA: meal_experiences")
        try:
            result = await conn.execute(text("SELECT COUNT(*) FROM meal_experiences"))
            total_exp = result.scalar()
            print(f"   Total experiencias: {total_exp}")

            if total_exp > 0:
                # Por status
                result = await conn.execute(text("""
                    SELECT window_status, COUNT(*) as cnt
                    FROM meal_experiences
                    GROUP BY window_status
                """))
                print("\n   Por window_status:")
                for row in result.fetchall():
                    emoji = "✅" if row.window_status == "ok" else "❌"
                    print(f"      {emoji} {row.window_status}: {row.cnt}")

                # Por event_kind
                result = await conn.execute(text("""
                    SELECT event_kind, COUNT(*) as cnt
                    FROM meal_experiences
                    GROUP BY event_kind
                """))
                print("\n   Por event_kind:")
                for row in result.fetchall():
                    print(f"      - {row.event_kind}: {row.cnt}")

                # Últimas experiencias
                result = await conn.execute(text("""
                    SELECT created_at, carbs_g, event_kind, window_status, discard_reason
                    FROM meal_experiences
                    ORDER BY created_at DESC
                    LIMIT 5
                """))
                print("\n   Últimas 5 experiencias:")
                for row in result.fetchall():
                    status = "✅" if row.window_status == "ok" else "❌"
                    print(f"      {status} {row.created_at}: {row.carbs_g}g, {row.event_kind}")
                    if row.discard_reason:
                        print(f"         Razón: {row.discard_reason}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        # 3. Tratamientos recientes
        print("\n📊 TABLA: treatments (últimos 7 días)")
        try:
            cutoff = datetime.utcnow() - timedelta(days=7)
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM treatments
                WHERE created_at >= :cutoff AND carbs > 0
            """), {"cutoff": cutoff})
            recent = result.scalar()
            print(f"   Tratamientos con carbs (7d): {recent}")

            # Cuántos ya tienen experiencia
            result = await conn.execute(text("""
                SELECT COUNT(DISTINCT t.id)
                FROM treatments t
                JOIN meal_experiences e ON e.treatment_id = t.id
                WHERE t.created_at >= :cutoff
            """), {"cutoff": cutoff})
            with_exp = result.scalar()
            print(f"   Ya evaluados: {with_exp}")
            print(f"   Pendientes: {recent - with_exp}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        # 4. Configuración de usuarios
        print("\n📊 CONFIGURACIÓN DE USUARIOS")
        try:
            result = await conn.execute(text("""
                SELECT username,
                       settings_json->'learning'->>'absorption_learning_enabled' as learning_enabled
                FROM user_settings
            """))
            for row in result.fetchall():
                status = "✅" if row.learning_enabled in ('true', 'True', None) else "❌"
                enabled = row.learning_enabled or "True (default)"
                print(f"   {status} {row.username}: absorption_learning_enabled = {enabled}")
        except Exception as e:
            print(f"   ❌ Error leyendo settings: {e}")

        # 5. Recomendaciones
        print("\n" + "=" * 60)
        print("📋 RECOMENDACIONES")
        print("=" * 60)

        if total_clusters == 0:
            print("""
⚠️ NO HAY CLUSTERS CREADOS

Posibles causas:
1. El job de meal_learning no ha corrido aún
2. No hay tratamientos con suficientes datos CGM
3. Todas las experiencias fueron excluidas

Acciones:
1. Verificar que el job está corriendo:
   GET /api/jobs/status

2. Ejecutar manualmente:
   POST /api/learning/run-meal-learning

3. Verificar que Nightscout tiene datos CGM de las últimas 72h
""")
        elif usable == 0:
            print(f"""
⚠️ HAY {total_clusters} CLUSTERS PERO NINGUNO ES USABLE

Criterio: n_ok >= 5 y confidence in (medium, high)

Acciones:
1. Esperar más comidas (~5 por tipo similar)
2. O reducir el umbral temporalmente en código:
   should_use_learned_curve(cluster, min_ok=3)  # Default es 5
""")
        else:
            print(f"""
✅ SISTEMA FUNCIONANDO

Clusters usables: {usable}/{total_clusters}

Si aún ves "uses base curve", es porque:
1. La comida actual no coincide con ningún cluster existente
2. Los macros caen en un bucket diferente

Buckets de macros:
- Carbs: 0, 10, 20, 30... (intervalos de 10g)
- Protein: 0, 10, 20... (intervalos de 10g)
- Fat: 0, 10, 20... (intervalos de 10g)
- Fiber: 0, 5, 10... (intervalos de 5g)
""")


if __name__ == "__main__":
    asyncio.run(main())
