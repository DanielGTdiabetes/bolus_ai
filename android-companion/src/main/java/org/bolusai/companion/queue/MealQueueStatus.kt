package org.bolusai.companion.queue

enum class MealQueueStatus {
    DETECTED,
    QUEUED,
    SENDING,
    SENT,
    DUPLICATE,
    FAILED,
    NEEDS_RETRY,
    UPDATE_DETECTED,
}
