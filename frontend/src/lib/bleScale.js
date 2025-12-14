
const SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
const RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"; // Write
const TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"; // Notify

const CMD_START = "gwc";
const CMD_TARE = "st";

let device = null;
let server = null;
let rxChar = null; // We write to this
let txChar = null; // We receive from this

let onDataCallback = null;

// Stability logic
const STABLE_WINDOW_MS = 1000;
const STABLE_THRESHOLD_G = 3;
let history = [];

export function isBleSupported() {
    return Boolean(navigator.bluetooth);
}

export function setOnData(cb) {
    onDataCallback = cb;
}

export async function connectScale() {
    if (!isBleSupported()) throw new Error("Bluetooth no soportado en este navegador.");

    console.log("Requesting Bluetooth Device...");
    device = await navigator.bluetooth.requestDevice({
        filters: [{ namePrefix: "PROZIS" }, { name: "PROZIS Bit Scale" }],
        optionalServices: [SERVICE_UUID]
    });

    device.addEventListener('gattserverdisconnected', onDisconnected);

    console.log("Connecting to GATT Server...");
    server = await device.gatt.connect();

    console.log("Getting Service...");
    const service = await server.getPrimaryService(SERVICE_UUID);

    console.log("Getting Characteristics...");
    rxChar = await service.getCharacteristic(RX_CHAR_UUID);
    txChar = await service.getCharacteristic(TX_CHAR_UUID);

    console.log("Starting Notifications...");
    await txChar.startNotifications();
    txChar.addEventListener('characteristicvaluechanged', handleNotifications);

    // Start stream automatically
    await startStream();

    return device.name || "Báscula Prozis";
}

export async function disconnectScale() {
    if (device && device.gatt.connected) {
        device.gatt.disconnect();
    }
}

function onDisconnected() {
    console.log('Scale disconnected');
    if (onDataCallback) {
        // Signal disconnection
        onDataCallback({ connected: false });
    }
}

export async function startStream() {
    if (!rxChar) return;
    const encoder = new TextEncoder();
    console.log("Sending START command...");
    try {
        await rxChar.writeValue(encoder.encode(CMD_START));
    } catch (e) {
        console.warn("Retrying start with newline", e);
        await rxChar.writeValue(encoder.encode(CMD_START + "\n"));
    }
}

export async function tare() {
    if (!rxChar) return;
    const encoder = new TextEncoder();
    console.log("Tare...");
    await rxChar.writeValue(encoder.encode(CMD_TARE));
}


let lastValidGrams = 0;
let lastDebugTime = 0;

function handleNotifications(event) {
    const value = event.target.value;
    // Parse data
    const len = value.byteLength;
    if (len < 4) return;

    const view = new DataView(value.buffer);

    // 1) LECTURA BATERÍA
    const batt = view.getUint8(1);

    // 2) LECTURA PESO (INT16 BIG-ENDIAN)
    // Fix 1: Use false for bigEndian (or simply omit 2nd arg as default is big-endian, but explicit is better)
    const raw = view.getInt16(len - 2, false);

    // 3) ESCALA (Décimas de gramo -> Gramos)
    const calculatedGrams = raw / 10;

    // 4) CLAMP DURO (0 - 2000g)
    let grams = calculatedGrams;
    let inRange = true;

    if (grams < 0 || grams > 2000) {
        inRange = false;
        // Maintain last valid value
        grams = lastValidGrams;
    } else {
        lastValidGrams = grams;
    }

    // 5) DEBUG CONTROLADO
    const debug = window.location.search.includes('bledebug=1');
    if (debug) {
        const now = Date.now();
        if (now - lastDebugTime > 1000) {
            // Log hex of last few bytes
            const hex = [];
            for (let i = 0; i < len; i++) hex.push(view.getUint8(i).toString(16).padStart(2, '0'));
            console.log(`[BLE DEBUG] Raw: ${raw}, Calc: ${calculatedGrams}, Final: ${grams}, Hex: ${hex.join(' ')}`);
            lastDebugTime = now;
        }
    }

    // Stability Logic
    const now = Date.now();
    // Only push to history if in range, otherwise we might detect stability on "frozen" out-of-range value?
    // User said "Marcar stable = false" if out of range.

    let stable = false;

    if (inRange) {
        history.push({ t: now, g: grams });
        history = history.filter(h => now - h.t <= STABLE_WINDOW_MS);

        if (history.length > 5) {
            const vals = history.map(h => h.g);
            const min = Math.min(...vals);
            const max = Math.max(...vals);
            if ((max - min) <= STABLE_THRESHOLD_G) {
                stable = true;
            }
        }
    } else {
        // Out of range -> Unstable
        stable = false;
        // Clear history to avoid mixing bad states
        history = [];
    }

    if (onDataCallback) {
        onDataCallback({
            connected: true,
            grams,
            battery: batt,
            stable,
            raw: value
        });
    }
}
