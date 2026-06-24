package org.bolusai.companion.scale

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.nio.charset.StandardCharsets
import java.util.UUID

@SuppressLint("MissingPermission")
class ProzisScaleManager(context: Context) {
    private val appContext = context.applicationContext
    private val bluetoothManager = appContext.getSystemService(BluetoothManager::class.java)
    private val adapter: BluetoothAdapter? get() = bluetoothManager?.adapter
    private val mutableState = MutableStateFlow(ScaleState())
    val state: StateFlow<ScaleState> = mutableState.asStateFlow()
    private val mainHandler = Handler(Looper.getMainLooper())

    private var scanCallback: ScanCallback? = null
    private var gatt: BluetoothGatt? = null
    private var writeCharacteristic: BluetoothGattCharacteristic? = null
    private val weightHistory = ArrayDeque<Pair<Long, Int>>()
    private var lastValidGrams = 0

    fun bluetoothAvailable(): Boolean = adapter?.isEnabled == true

    fun connect() {
        if (!bluetoothAvailable()) {
            mutableState.value = ScaleState(message = "Activa Bluetooth para conectar la báscula")
            return
        }
        disconnect()
        mutableState.value = ScaleState(scanning = true, message = "Buscando báscula Prozis…")
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                val name = result.device.name.orEmpty()
                if (!name.startsWith("PROZIS", ignoreCase = true)) return
                stopScan()
                mutableState.value = mutableState.value.copy(
                    scanning = false,
                    connecting = true,
                    deviceName = name,
                    message = "Conectando con $name…",
                )
                gatt = result.device.connectGatt(appContext, false, gattCallback, BluetoothDeviceTransport)
            }

            override fun onScanFailed(errorCode: Int) {
                mutableState.value = ScaleState(message = "No se pudo buscar la báscula ($errorCode)")
                scanCallback = null
            }
        }
        scanCallback = callback
        adapter?.bluetoothLeScanner?.startScan(
            null,
            ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build(),
            callback,
        )
        mainHandler.postDelayed({
            if (scanCallback === callback) {
                stopScan()
                mutableState.value = ScaleState(message = "No se encontró la báscula. Comprueba que esté encendida.")
            }
        }, SCAN_TIMEOUT_MS)
    }

    fun disconnect() {
        stopScan()
        runCatching { gatt?.disconnect() }
        runCatching { gatt?.close() }
        gatt = null
        writeCharacteristic = null
        weightHistory.clear()
        mutableState.value = ScaleState()
    }

    fun tare() {
        writeCommand(CMD_TARE)
    }

    private fun startStream() {
        writeCommand(CMD_START)
    }

    private fun stopScan() {
        scanCallback?.let { callback ->
            runCatching { adapter?.bluetoothLeScanner?.stopScan(callback) }
        }
        scanCallback = null
    }

    private fun writeCommand(command: String) {
        val characteristic = writeCharacteristic ?: return
        val payload = command.toByteArray(StandardCharsets.UTF_8)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt?.writeCharacteristic(
                characteristic,
                payload,
                BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT,
            )
        } else {
            @Suppress("DEPRECATION")
            characteristic.value = payload
            @Suppress("DEPRECATION")
            gatt?.writeCharacteristic(characteristic)
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    mutableState.value = mutableState.value.copy(
                        scanning = false,
                        connecting = true,
                        message = "Configurando báscula…",
                    )
                    gatt.discoverServices()
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    writeCharacteristic = null
                    mutableState.value = ScaleState(message = "Báscula desconectada")
                }
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            val service: BluetoothGattService = gatt.getService(SERVICE_UUID) ?: run {
                mutableState.value = ScaleState(message = "Servicio de báscula no encontrado")
                return
            }
            writeCharacteristic = service.getCharacteristic(RX_UUID)
            val notify = service.getCharacteristic(TX_UUID) ?: run {
                mutableState.value = ScaleState(message = "Canal de peso no encontrado")
                return
            }
            gatt.setCharacteristicNotification(notify, true)
            val descriptor = notify.getDescriptor(CCCD_UUID)
            if (descriptor != null) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    gatt.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                } else {
                    @Suppress("DEPRECATION")
                    descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    @Suppress("DEPRECATION")
                    gatt.writeDescriptor(descriptor)
                }
            } else {
                markReady()
            }
        }

        override fun onDescriptorWrite(
            gatt: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int,
        ) {
            markReady()
        }

        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            handlePayload(characteristic.value)
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            handlePayload(value)
        }
    }

    private fun markReady() {
        mutableState.value = mutableState.value.copy(
            scanning = false,
            connecting = false,
            connected = true,
            message = "Báscula conectada",
        )
        tare()
        startStream()
    }

    private fun handlePayload(value: ByteArray) {
        val reading = ScalePayloadParser.parse(value)
        val inRange = reading != null
        val grams = reading?.grams?.also { lastValidGrams = it } ?: lastValidGrams
        val now = System.currentTimeMillis()
        if (inRange) {
            weightHistory.addLast(now to grams)
            while (weightHistory.isNotEmpty() && now - weightHistory.first().first > 1_000L) {
                weightHistory.removeFirst()
            }
        } else {
            weightHistory.clear()
        }
        val values = weightHistory.map { it.second }
        val stable = inRange && values.size > 5 && (values.maxOrNull()!! - values.minOrNull()!!) <= 3
        mutableState.value = mutableState.value.copy(
            connected = true,
            grams = grams,
            batteryPercent = reading?.batteryPercent ?: mutableState.value.batteryPercent,
            stable = stable,
            message = if (stable) "Peso estable" else "Pesando…",
        )
    }

    companion object {
        private val SERVICE_UUID = UUID.fromString("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
        private val RX_UUID = UUID.fromString("6e400002-b5a3-f393-e0a9-e50e24dcca9e")
        private val TX_UUID = UUID.fromString("6e400003-b5a3-f393-e0a9-e50e24dcca9e")
        private val CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        private const val CMD_START = "gwc"
        private const val CMD_TARE = "st"
        private const val SCAN_TIMEOUT_MS = 15_000L
        private val BluetoothDeviceTransport =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) android.bluetooth.BluetoothDevice.TRANSPORT_LE else 0
    }
}
