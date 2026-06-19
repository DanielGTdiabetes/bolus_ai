package org.bolusai.companion.queue

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(entities = [MealQueueItem::class], version = 1, exportSchema = false)
abstract class BolusCompanionDatabase : RoomDatabase() {
    abstract fun mealQueueDao(): MealQueueDao

    companion object {
        @Volatile
        private var instance: BolusCompanionDatabase? = null

        fun get(context: Context): BolusCompanionDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    BolusCompanionDatabase::class.java,
                    "bolus_companion.db",
                ).build().also { instance = it }
            }
    }
}
