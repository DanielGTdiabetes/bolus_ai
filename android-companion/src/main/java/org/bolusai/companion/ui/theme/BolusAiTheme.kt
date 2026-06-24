package org.bolusai.companion.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Ink = Color(0xFF14213D)
private val Blue = Color(0xFF1261A0)
private val Cyan = Color(0xFF008F8C)
private val Warm = Color(0xFFFF8A5B)

private val LightColors = lightColorScheme(
    primary = Blue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD8ECFF),
    onPrimaryContainer = Ink,
    secondary = Cyan,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFBDEFEA),
    tertiary = Warm,
    background = Color(0xFFF5F8FC),
    onBackground = Ink,
    surface = Color.White,
    onSurface = Ink,
    surfaceVariant = Color(0xFFE8EEF6),
    onSurfaceVariant = Color(0xFF48566A),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF83C5FF),
    onPrimary = Color(0xFF003354),
    primaryContainer = Color(0xFF074A78),
    secondary = Color(0xFF63D8D0),
    tertiary = Color(0xFFFFB59A),
    background = Color(0xFF09111F),
    onBackground = Color(0xFFE8EEF8),
    surface = Color(0xFF111C2E),
    onSurface = Color(0xFFE8EEF8),
    surfaceVariant = Color(0xFF1D2A3E),
    onSurfaceVariant = Color(0xFFBBC7D8),
)

private val BolusTypography = Typography(
    headlineMedium = TextStyle(
        fontSize = 30.sp,
        lineHeight = 36.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = (-0.5).sp,
    ),
    headlineSmall = TextStyle(
        fontSize = 24.sp,
        lineHeight = 30.sp,
        fontWeight = FontWeight.Bold,
    ),
    titleLarge = TextStyle(
        fontSize = 20.sp,
        lineHeight = 26.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    titleMedium = TextStyle(
        fontSize = 16.sp,
        lineHeight = 22.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 24.sp),
    labelLarge = TextStyle(
        fontSize = 14.sp,
        lineHeight = 20.sp,
        fontWeight = FontWeight.SemiBold,
    ),
)

private val BolusShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(18.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(32.dp),
)

@Composable
fun BolusAiTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = BolusTypography,
        shapes = BolusShapes,
        content = content,
    )
}
